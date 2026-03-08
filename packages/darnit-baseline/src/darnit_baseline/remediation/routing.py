"""Write-back routing classification for org-wide audits.

Classifies remediation actions as targeting either the org `.project` repo
(shared metadata) or the individual repo's `.project/` folder (repo-specific).

Example:
    from darnit_baseline.remediation.routing import classify_writeback

    classification = classify_writeback("security.contact", org_config)
    # Returns "org" or "repo"
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Fields that are org-level when present in the org .project config.
# These are shared metadata that typically belongs in the org's .project repo.
_ORG_LEVEL_FIELDS = {
    "security.contact",
    "security.policy",
    "maintainers",
    "governance.codeowners",
    "governance.contributing",
    "governance.governance_doc",
}

# Fields that are always repo-level regardless of org config.
# These are repo-specific artifacts or overrides.
_ALWAYS_REPO_FIELDS = {
    "SECURITY.md",
    "CODEOWNERS",
    ".github/CODEOWNERS",
    "CONTRIBUTING.md",
    "ci_provider",
    "has_releases",
    "is_library",
    "has_compiled_assets",
    "has_subprojects",
}


def classify_writeback(
    field_or_artifact: str,
    org_config: dict[str, Any] | None = None,
) -> str:
    """Classify a remediation action as 'org' or 'repo'.

    Args:
        field_or_artifact: The field path (e.g., "security.contact") or
            artifact name (e.g., "SECURITY.md") being remediated.
        org_config: The org-level .project config as a dict, or None if
            no org config exists.

    Returns:
        "org" if the field belongs in the org .project repo,
        "repo" if it belongs in the individual repo's .project/ folder.
    """
    # Always-repo fields don't need org config check
    if field_or_artifact in _ALWAYS_REPO_FIELDS:
        return "repo"

    # If no org config, everything goes to repo
    if not org_config:
        return "repo"

    # Check if the field exists at the org level
    if field_or_artifact in _ORG_LEVEL_FIELDS:
        # Check if the org config actually has this field populated
        if _field_exists_in_config(field_or_artifact, org_config):
            return "org"

    return "repo"


def classify_remediation_actions(
    actions: list[dict[str, Any]],
    org_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Classify a list of remediation actions with routing labels.

    Args:
        actions: List of remediation action dicts, each with at least
            a "field" or "artifact" key.
        org_config: The org-level .project config.

    Returns:
        The same actions list with an added "routing" key ("org" or "repo").
    """
    for action in actions:
        field = action.get("field") or action.get("artifact", "")
        action["routing"] = classify_writeback(field, org_config)
    return actions


def format_routing_report(
    actions: list[dict[str, Any]],
    owner: str,
) -> str:
    """Format write-back routing classification as markdown.

    Args:
        actions: Classified remediation actions (with "routing" key).
        owner: GitHub org/user for display.

    Returns:
        Markdown section for the audit report.
    """
    if not actions:
        return ""

    lines = [
        "## Write-back Routing",
        "",
        "The following remediation actions are classified by target:",
        "",
    ]

    org_actions = [a for a in actions if a.get("routing") == "org"]
    repo_actions = [a for a in actions if a.get("routing") == "repo"]

    if org_actions:
        lines.append(f"### Org-level (`{owner}/.project`)")
        lines.append("")
        for action in org_actions:
            desc = action.get("description", action.get("field", ""))
            lines.append(f"- [org] {desc}")
        lines.append("")

    if repo_actions:
        lines.append("### Repo-level (per-repo `.project/`)")
        lines.append("")
        for action in repo_actions:
            desc = action.get("description", action.get("field", ""))
            lines.append(f"- [repo] {desc}")
        lines.append("")

    return "\n".join(lines)


def _field_exists_in_config(field_path: str, config: dict[str, Any]) -> bool:
    """Check if a dotted field path exists in a nested config dict.

    Args:
        field_path: Dotted path like "security.contact"
        config: Nested dict to check

    Returns:
        True if the field exists and is not None/empty
    """
    parts = field_path.split(".")
    current = config
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    # Consider empty strings, None, and empty lists as "not existing"
    return not (current is None or current == "" or current == [])
