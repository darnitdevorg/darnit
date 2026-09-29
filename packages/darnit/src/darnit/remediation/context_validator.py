"""Context validator for remediation requirements.

Requirements are declared in TOML (``requires_context``) and checked here
before a remediation runs. Values come from the context resolver
(feature 042): a key is ready only when its value is usable -- confirmed by
a person, or concluded in this run for an ``auto_detect = true`` key. A
candidate (a detected value, or a stored value without a confirmation) is
shown to the person as data and never used as the key's value.

Example workflow:
    1. Orchestrator loads remediation config with `requires_context`
    2. Validator resolves each required key's standing
    3. If not ready -> return prompts with candidates for the person to review
    4. If ready -> proceed with remediation
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from darnit.config.context_schema import ContextSource, ContextValue, ResolvedValue, Standing
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
    *,
    target: str | None = None,
) -> ContextCheckResult:
    """Check whether every required context key has a usable value.

    Decided by the key's standing (feature 042, FR-006), never by a stored
    ``source`` field:

    - confirmed: ready, unless the value names one of the key's hint source
      files (a path stored instead of the values in it);
    - concluded (an ``auto_detect = true`` key detected in this run): ready
      unless the requirement asks to prompt for detected values or the
      detection's confidence is below the requirement's threshold;
    - candidate or unknown: never ready. A candidate is returned in
      ``auto_detected`` for display only.

    Args:
        requirements: List of ContextRequirement from remediation config
        local_path: Path to the repository
        framework: FrameworkConfig for context definitions (default: the
            repository's framework)
        owner: Repository owner, for detection
        repo: Repository name, for detection
        target: Repository identity the operator named, for operator-side
            confirmations

    Returns:
        ContextCheckResult with ready status and any needed prompts
    """
    from darnit.config.context_resolve import resolve_context
    from darnit.config.context_storage import framework_definitions, get_context_definitions

    result = ContextCheckResult()
    if not requirements:
        return result

    definitions = framework_definitions(framework) if framework is not None else get_context_definitions(local_path)
    wanted = {req.key for req in requirements}
    resolved = resolve_context(
        local_path,
        {key: d for key, d in definitions.items() if key in wanted},
        target=target,
        owner=owner,
        repo=repo,
    )

    for req in requirements:
        value = resolved.get(req.key)
        if _ready(value, req, _get_context_definition(req.key, framework)):
            continue
        result.ready = False
        result.missing_context.append(req.key)
        current_value = None
        if value is not None and value.value is not None and value.standing is not Standing.CONFIRMED:
            result.auto_detected[req.key] = value.value
            current_value = ContextValue(
                source=ContextSource.AUTO_DETECTED,
                value=value.value,
                detection_method=value.origin.method if value.origin else None,
                confidence=value.origin.confidence if value.origin and value.origin.confidence is not None else 0.0,
            )
        result.prompts.append(
            format_context_prompt(
                context_key=req.key,
                definition=_get_context_definition(req.key, framework),
                requirement=req,
                current_value=current_value,
                local_path=local_path,
            )
        )

    return result


def _ready(
    value: ResolvedValue | None, requirement: ContextRequirement, definition: ContextDefinitionConfig | None
) -> bool:
    if value is None:
        return False
    if value.standing is Standing.CONFIRMED:
        return not _names_hint_source(value.value, definition)
    if value.standing is Standing.CONCLUDED:
        confidence = value.origin.confidence if value.origin and value.origin.confidence is not None else 0.0
        return not requirement.prompt_if_auto_detected and confidence >= requirement.confidence_threshold
    return False


_HINT_SOURCE_NAMES = frozenset({"CODEOWNERS", ".github/CODEOWNERS", "MAINTAINERS", "MAINTAINERS.md"})


def _names_hint_source(value: object, definition: ContextDefinitionConfig | None) -> bool:
    """Whether ``value`` is a file name where the key's values should have been read from."""
    if not isinstance(value, str):
        return False
    names = _HINT_SOURCE_NAMES | set(definition.hint_sources if definition else [])
    if value in names:
        logger.info("Stored value '%s' names a file rather than its values; treating it as missing", value)
        return True
    return False


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
    lines = []

    # Header
    lines.append(f"⚠️ **Context confirmation required: `{context_key}`**")
    lines.append("")
    lines.append("🚨 **DO NOT** directly edit `.project/` files! Use `confirm_project_data()` instead.")
    lines.append("")
    lines.append("🛑 **AI Agents:** You MUST ask the user for this value. Do NOT guess or infer from repository owner, git history, or other sources.")
    lines.append("")

    # Warning from requirement
    if requirement.warning:
        lines.append(f"⚠️ {requirement.warning}")
        lines.append("")

    # Get hint_sources from definition (TOML-driven, no hardcoding)
    hint_sources = definition.hint_sources if definition else []
    allow_sieve_hints = definition.allow_sieve_hints if definition else False

    # Check for authoritative files from hint_sources
    existing_hint_files: list[str] = []
    if local_path and hint_sources:
        repo_path = Path(local_path)
        for candidate in hint_sources:
            if (repo_path / candidate).exists():
                existing_hint_files.append(candidate)

    # Cascading prompt logic:
    # 1. If authoritative file exists → suggest referencing file (short-circuit)
    # 2. If no file but sieve hints allowed → show detected values for confirmation
    # 3. If no hints at all → ask user directly

    if existing_hint_files:
        # Case 1: Authoritative file exists - parse and show values as suggestions
        lines.append("📁 **Found authoritative source(s):**")
        for f in existing_hint_files:
            lines.append(f"   - `{f}`")
        lines.append("")

        # Parse the file to extract actual values for user review
        parsed_values = _parse_hint_file(repo_path / existing_hint_files[0])
        if parsed_values:
            lines.append("**Values found in file (review and confirm with user):**")
            for val in parsed_values[:10]:
                lines.append(f"   - `{val}`")
            if len(parsed_values) > 10:
                lines.append(f"   - ... and {len(parsed_values) - 10} more")
            lines.append("")

        lines.append("**⚠️ Ask the user to confirm or correct these values, then use:**")
        lines.append("```")
        lines.append(f"confirm_project_data({context_key}=<user-confirmed values>)")
        lines.append("```")
        lines.append("")
    elif allow_sieve_hints and current_value is not None and isinstance(current_value, ContextValue):
        # Case 2: No authoritative file, but sieve found hints - show for confirmation
        lines.append("🔍 **Detected potential values (please confirm):**")
        # Note: source is already a string due to use_enum_values=True in ContextValue
        lines.append(f"   Source: {current_value.source}, Confidence: {current_value.confidence:.0%}")
        if isinstance(current_value.value, list):
            for item in current_value.value[:10]:
                lines.append(f"   - {item}")
            if len(current_value.value) > 10:
                lines.append(f"   - ... and {len(current_value.value) - 10} more")
        else:
            lines.append(f"   {current_value.value}")
        lines.append("")
        lines.append("**⚠️ Ask the user to confirm or correct these values, then use:**")
        lines.append("```")
        lines.append(f"confirm_project_data({context_key}=<user-confirmed values>)")
        lines.append("```")
        lines.append("")
    else:
        # Case 3: No hints at all - ask user directly
        if hint_sources:
            lines.append(f"📭 **No authoritative file found** ({', '.join(hint_sources[:3])})")
        else:
            lines.append(f"📭 **No hints available for `{context_key}`**")
        lines.append("")
        lines.append(f"**Ask the user:** What is the value for `{context_key}`?")
        lines.append("")

    # Prompt and hint from definition
    if definition:
        lines.append(f"**{definition.prompt}**")
        if definition.hint:
            lines.append(f"💡 {definition.hint}")
        if definition.examples:
            lines.append(f"📝 Examples: {', '.join(definition.examples[:3])}")
        lines.append("")

    # Generic instructions (only if we haven't already shown a specific command)
    # This handles the "ask user directly" case (Case 3)
    if not existing_hint_files and not (allow_sieve_hints and current_value is not None):
        lines.append("**After the user provides the value, use:**")
        lines.append("```")
        # Show example based on context type
        if definition and definition.examples:
            example = definition.examples[0]
            lines.append(f'confirm_project_data({context_key}={example})')
        else:
            lines.append(f'confirm_project_data({context_key}=<value>)')
        lines.append("```")

    return "\n".join(lines)


def _parse_hint_file(file_path: Path) -> list[str] | None:
    """Parse a hint source file to extract values.

    Uses the appropriate parser based on filename (CODEOWNERS → codeowners parser,
    .md → markdown list parser, etc.).

    Args:
        file_path: Path to the hint file

    Returns:
        List of extracted values, or None if nothing found
    """
    from darnit.context.collection import parse_codeowners, parse_markdown_list

    name = file_path.name.upper()
    if name in ("CODEOWNERS", "MAINTAINERS"):
        result = parse_codeowners(file_path)
    else:
        result = parse_markdown_list(file_path)
    return result or None


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


__all__ = [
    "ContextCheckResult",
    "check_context_requirements",
    "format_context_prompt",
    "get_context_requirements_for_category",
]
