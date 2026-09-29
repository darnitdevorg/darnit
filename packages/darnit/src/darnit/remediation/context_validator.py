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

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from darnit.config.context_schema import ResolvedValue, Standing
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
        candidates: The unusable keys' candidates, for display as data only
    """
    ready: bool = True
    missing_context: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    auto_detected: dict[str, Any] = field(default_factory=dict)
    candidates: dict[str, ResolvedValue] = field(default_factory=dict)


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
      ``auto_detected`` and ``candidates`` for display only.

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
        candidate = None
        if value is not None and value.value is not None and value.standing is not Standing.CONFIRMED:
            result.auto_detected[req.key] = value.value
            result.candidates[req.key] = candidate = value
        result.prompts.append(
            format_context_prompt(
                context_key=req.key,
                definition=_get_context_definition(req.key, framework),
                requirement=req,
                candidate=candidate,
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
    candidate: ResolvedValue | None = None,
    local_path: str | None = None,
) -> str:
    """A prompt asking the person for one context key (feature 042, FR-013, FR-014).

    A candidate is shown as labelled, unconfirmed data with its origin and
    digest. The commands hold placeholders only, never a candidate value or
    a configuration example; examples are shown as a format.

    Args:
        context_key: The context key name (e.g., "maintainers")
        definition: The ContextDefinitionConfig from TOML (if available)
        requirement: The ContextRequirement with threshold and warning
        candidate: The key's unconfirmed value, if any, from the resolver
        local_path: Path to repository (used to name hint source files present)

    Returns:
        Formatted prompt string for the user
    """
    from darnit.config.context_resolve import candidate_payload, confirmation_template

    shown = candidate_payload(candidate)
    lines = [
        f"**Context confirmation required: `{context_key}`**",
        "",
        "**DO NOT** directly edit `.project/` files! Use `confirm_project_data()` instead.",
        "",
        "**AI Agents:** You MUST ask the user for this value. Do NOT guess or infer it from repository "
        "owner, git history, or other sources.",
        "",
    ]
    if requirement.warning:
        lines += [f"Warning: {requirement.warning}", ""]

    if definition:
        lines.append(f"**{definition.prompt}**")
        if definition.hint:
            lines.append(f"Hint: {definition.hint}")
        if definition.type == "enum" and definition.values:
            lines.append(f"Allowed values: {', '.join(definition.values)}")
        if definition.examples and definition.type not in ("enum", "boolean"):
            lines.append(f"Format (not an answer): {' or '.join(definition.examples)}")
        lines.append("")

    sources = definition.hint_sources if definition and local_path else []
    hint_files = [name for name in sources if (Path(local_path) / name).exists()]
    if hint_files:
        lines += [f"Files the person may consult: {', '.join(f'`{name}`' for name in hint_files)}", ""]

    if shown is not None:
        origin = shown["origin"] or {}
        confidence = f", confidence {origin['confidence']:.0%}" if origin.get("confidence") is not None else ""
        lines += [
            f"Candidate ({shown['label']}):",
            f"- value: {json.dumps(shown['value'])}",
            f"- origin: {origin.get('kind')} ({origin.get('method')}){confidence}",
            f"- digest: {shown['digest']}",
            "",
            "**After the person answers, use one of:**",
        ]
    else:
        lines += [f"**Ask the user:** What is the value for `{context_key}`?", "", "**After the person answers, use:**"]
    lines.append("```")
    lines.extend(confirmation_template(context_key, candidate=shown is not None).split("  OR  "))
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


__all__ = [
    "ContextCheckResult",
    "check_context_requirements",
    "format_context_prompt",
    "get_context_requirements_for_category",
]
