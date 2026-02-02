"""Context validator for remediation requirements.

This module provides a generic validator that checks context requirements before
running remediations. Instead of hardcoding confirmation logic in each remediation
function, requirements are declared in TOML and this validator handles prompting.

The validator now integrates with the context sieve for progressive auto-detection:
1. Check if context is already confirmed in .project.yaml
2. If missing, use context sieve to auto-detect from multiple sources
3. Show auto-detected values with confidence scores for user confirmation
4. Only proceed when confidence meets threshold or user confirms

Example workflow:
    1. Orchestrator loads remediation config with `requires_context`
    2. Validator checks storage, then tries sieve auto-detection
    3. If not ready → return prompts WITH auto-detected suggestions
    4. If ready → proceed with remediation
"""

from dataclasses import dataclass, field
from typing import Any

from darnit.config.context_schema import ContextSource, ContextValue
from darnit.config.context_storage import get_context_value
from darnit.config.framework_schema import (
    ContextDefinitionConfig,
    ContextRequirement,
    FrameworkConfig,
)
from darnit.core.logging import get_logger

logger = get_logger("remediation.context_validator")


@dataclass
class ContextCheckResult:
    """Result of checking context requirements before remediation.

    Attributes:
        ready: True if all requirements are satisfied and remediation can proceed
        missing_context: List of context keys that need confirmation
        prompts: User-friendly prompt messages for missing context
        auto_detected: Values that were auto-detected (may need confirmation)
    """
    ready: bool = True
    missing_context: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    auto_detected: dict[str, Any] = field(default_factory=dict)


def check_context_requirements(
    requirements: list[ContextRequirement],
    local_path: str,
    framework: FrameworkConfig | None = None,
    owner: str | None = None,
    repo: str | None = None,
) -> ContextCheckResult:
    """Check if all required context is confirmed for a remediation.

    For each requirement:
    1. Get current value from context storage
    2. If None → try context sieve auto-detection
    3. If AUTO_DETECTED and prompt_if_auto_detected → needs confirmation
    4. If confidence < threshold → needs confirmation
    5. Otherwise → ready to proceed

    Args:
        requirements: List of ContextRequirement from remediation config
        local_path: Path to the repository
        framework: Optional FrameworkConfig for context definitions
        owner: GitHub owner (optional, enables API-based auto-detection)
        repo: GitHub repo name (optional, enables API-based auto-detection)

    Returns:
        ContextCheckResult with ready status and any needed prompts
    """
    result = ContextCheckResult()

    for req in requirements:
        context_value = get_context_value(local_path, req.key, "governance")

        # Check 1: Is context missing entirely?
        if context_value is None:
            # NEW: Try context sieve auto-detection before giving up
            detected_value = _try_sieve_detection(req.key, local_path, owner, repo)

            if detected_value is not None:
                # Found via sieve - use it as a ContextValue for consistency
                context_value = detected_value
                # Store in auto_detected for prompt display
                result.auto_detected[req.key] = detected_value.value
                logger.debug(
                    f"Auto-detected {req.key} via sieve: "
                    f"{detected_value.value} ({detected_value.confidence:.0%} confidence)"
                )
            else:
                # No auto-detection available
                result.ready = False
                result.missing_context.append(req.key)
                prompt = format_context_prompt(
                    context_key=req.key,
                    definition=_get_context_definition(req.key, framework),
                    requirement=req,
                    current_value=None,
                    local_path=local_path,
                )
                result.prompts.append(prompt)
                continue

        # Check 2: Is it auto-detected and should we prompt?
        if context_value.source == ContextSource.AUTO_DETECTED and req.prompt_if_auto_detected:
            result.ready = False
            result.missing_context.append(req.key)
            result.auto_detected[req.key] = context_value.value
            prompt = format_context_prompt(
                context_key=req.key,
                definition=_get_context_definition(req.key, framework),
                requirement=req,
                current_value=context_value,
                local_path=local_path,
            )
            result.prompts.append(prompt)
            continue

        # Check 3: Is confidence below threshold?
        if context_value.confidence < req.confidence_threshold:
            result.ready = False
            result.missing_context.append(req.key)
            if context_value.source == ContextSource.AUTO_DETECTED:
                result.auto_detected[req.key] = context_value.value
            prompt = format_context_prompt(
                context_key=req.key,
                definition=_get_context_definition(req.key, framework),
                requirement=req,
                current_value=context_value,
                local_path=local_path,
            )
            result.prompts.append(prompt)
            continue

        # Context is confirmed and meets threshold - good to go

    return result


def format_context_prompt(
    context_key: str,
    definition: ContextDefinitionConfig | None,
    requirement: ContextRequirement,
    current_value: Any | None,
    local_path: str | None = None,
) -> str:
    """Generate a user-friendly prompt from TOML definition + requirement settings.

    Args:
        context_key: The context key name (e.g., "maintainers")
        definition: The ContextDefinitionConfig from TOML (if available)
        requirement: The ContextRequirement with threshold and warning
        current_value: Current value (if auto-detected)
        local_path: Path to repository (used to check for existing files)

    Returns:
        Formatted prompt string for the user
    """
    from pathlib import Path

    lines = []

    # Header
    lines.append(f"⚠️ **Context confirmation required: `{context_key}`**")
    lines.append("")
    lines.append("🚨 **DO NOT** directly edit `.project/` files! Use `confirm_project_context()` instead.")
    lines.append("")
    lines.append("🛑 **AI Agents:** You MUST ask the user for this value. Do NOT guess or infer from repository owner, git history, or other sources.")
    lines.append("")

    # Warning from requirement
    if requirement.warning:
        lines.append(f"⚠️ {requirement.warning}")
        lines.append("")

    # For maintainers, check for existing governance files that can be referenced
    existing_maintainer_files: list[str] = []
    if context_key == "maintainers" and local_path:
        repo_path = Path(local_path)
        for candidate in ["CODEOWNERS", ".github/CODEOWNERS", "MAINTAINERS.md", "MAINTAINERS"]:
            if (repo_path / candidate).exists():
                existing_maintainer_files.append(candidate)

    # For maintainers: only show authoritative file references OR ask user
    # Never show auto-detected values - they are too easy for AI to guess
    if context_key == "maintainers":
        if existing_maintainer_files:
            lines.append("📁 **Found authoritative source(s):**")
            for f in existing_maintainer_files:
                lines.append(f"   - `{f}`")
            lines.append("")
            lines.append("**Use this command to reference the file:**")
            lines.append("```")
            lines.append(f'confirm_project_context(maintainers="{existing_maintainer_files[0]}")')
            lines.append("```")
            lines.append("")
        else:
            lines.append("📭 **No maintainer file found** (CODEOWNERS, MAINTAINERS.md, etc.)")
            lines.append("")
            lines.append("**Ask the user:** Who are the maintainers of this project?")
            lines.append("")
            lines.append("**After the user provides names, use:**")
            lines.append("```")
            lines.append('confirm_project_context(maintainers=["@user1", "@user2"])')
            lines.append("```")
            lines.append("")
        # Skip showing auto-detected values for maintainers - return early
    else:
        # Show existing files that can be referenced (PREFERRED option)
        if existing_maintainer_files:
            lines.append("📁 **Existing maintainer files found:**")
            for f in existing_maintainer_files:
                lines.append(f"   - `{f}`")
            lines.append("")
            lines.append("💡 **Recommended:** Reference an existing file instead of duplicating data:")
            lines.append("```")
            lines.append(f'confirm_project_context(maintainers="{existing_maintainer_files[0]}")')
            lines.append("```")
            lines.append("")
            lines.append("This ensures maintainer data stays in sync with the authoritative source.")
            lines.append("")

        # Show current value if auto-detected (as ALTERNATIVE, not primary)
        if current_value is not None:
            if isinstance(current_value, ContextValue):
                if existing_maintainer_files:
                    lines.append("---")
                    lines.append("")
                    lines.append("**Alternative:** Specify maintainers explicitly (not recommended if files exist):")
                    lines.append("")
                lines.append(f"🔍 **Auto-detected value** (confidence: {current_value.confidence:.0%}):")
                if isinstance(current_value.value, list):
                    for item in current_value.value[:10]:  # Limit to 10 items
                        lines.append(f"   - {item}")
                    if len(current_value.value) > 10:
                        lines.append(f"   - ... and {len(current_value.value) - 10} more")
                else:
                    lines.append(f"   {current_value.value}")
                lines.append("")

    # Prompt and hint from definition
    if definition:
        lines.append(f"**{definition.prompt}**")
        if definition.hint:
            lines.append(f"💡 {definition.hint}")
        if definition.examples:
            lines.append(f"📝 Examples: {', '.join(definition.examples[:3])}")
        lines.append("")

    # Instructions (skip for maintainers - already handled above)
    if context_key != "maintainers" and not existing_maintainer_files:
        lines.append("**To proceed, confirm the context using:**")
        lines.append("```")
        if context_key == "security_contact":
            lines.append('confirm_project_context(security_contact="security@example.com")')
        else:
            lines.append(f'confirm_project_context({context_key}=<value>)')
        lines.append("```")

    return "\n".join(lines)


def _get_context_definition(
    context_key: str,
    framework: FrameworkConfig | None,
) -> ContextDefinitionConfig | None:
    """Get context definition from framework config.

    Args:
        context_key: The context key name
        framework: The FrameworkConfig with context definitions

    Returns:
        ContextDefinitionConfig if found, None otherwise
    """
    if framework is None:
        return None

    return framework.context.get_definition(context_key)


def get_context_requirements_for_category(
    category: str,
    control_id: str | None = None,
    framework: FrameworkConfig | None = None,
    registry: dict[str, Any] | None = None,
) -> list[ContextRequirement]:
    """Get context requirements for a remediation category.

    Checks both TOML (via framework) and Python registry (fallback).
    Priority: TOML > Python registry

    Args:
        category: Remediation category name (e.g., "codeowners")
        control_id: Optional control ID for TOML lookup
        framework: Optional FrameworkConfig for TOML requirements
        registry: Optional Python registry dict

    Returns:
        List of ContextRequirement for this category
    """
    requirements: list[ContextRequirement] = []

    # Try TOML first (primary source)
    if framework and control_id:
        control = framework.controls.get(control_id)
        if control and control.remediation and control.remediation.requires_context:
            requirements.extend(control.remediation.requires_context)

    # Fall back to Python registry if no TOML requirements
    if not requirements and registry:
        category_info = registry.get(category, {})
        req_list = category_info.get("requires_context", [])
        for req_dict in req_list:
            requirements.append(ContextRequirement(**req_dict))

    return requirements


def _try_sieve_detection(
    key: str,
    local_path: str,
    owner: str | None,
    repo: str | None,
) -> ContextValue | None:
    """Try to auto-detect context using the context sieve.

    This is called when context is missing from storage. The sieve
    uses progressive detection:
    1. Deterministic (explicit files like MAINTAINERS.md)
    2. Heuristic (git history, package.json authors)
    3. API (GitHub collaborators)

    NOTE: Some context keys are intentionally NOT auto-detected to prevent
    AI agents from guessing values. For example, "maintainers" must come
    from authoritative sources (CODEOWNERS, MAINTAINERS.md) or user input.

    Args:
        key: Context key to detect (e.g., "maintainers")
        local_path: Path to the repository
        owner: GitHub owner (optional)
        repo: GitHub repo name (optional)

    Returns:
        ContextValue with auto-detected value if found, None otherwise
    """
    # Never auto-detect maintainers - too easy for AI to guess wrong.
    # AI agents will see repo owner and assume they're the maintainer.
    # Instead, require either an authoritative file or explicit user input.
    if key == "maintainers":
        logger.debug(
            f"Skipping auto-detection for '{key}' - requires authoritative source or user input"
        )
        return None

    try:
        from darnit.context import get_context_sieve

        sieve = get_context_sieve()
        result = sieve.detect(key, local_path, owner, repo)

        if result.is_usable:
            # Convert sieve result to ContextValue
            return ContextValue.auto_detected(
                value=result.value,
                method=f"context_sieve ({len(result.signals)} signals)",
                confidence=result.confidence,
            )
    except ImportError:
        logger.debug("Context sieve not available, skipping auto-detection")
    except Exception as e:
        logger.warning(f"Context sieve detection failed for '{key}': {e}")

    return None


__all__ = [
    "ContextCheckResult",
    "check_context_requirements",
    "format_context_prompt",
    "get_context_requirements_for_category",
]
