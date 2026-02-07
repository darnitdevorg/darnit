"""Built-in audit tool for any framework.

Provides a generic audit tool that works with any TOML-defined framework.
Implementations can use this instead of writing their own audit tool.

Usage in TOML:
    [mcp.tools.audit]
    builtin = "audit"
    description = "Run compliance audit"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("server.tools.builtin_audit")


async def builtin_audit(
    local_path: str = ".",
    level: int = 3,
    output_format: str = "markdown",
    tags: str | list[str] | None = None,
    *,
    _framework_name: str = "",
) -> str:
    """Run a compliance audit on a repository.

    Loads controls from the framework TOML, runs each through the sieve
    verification pipeline, and returns a formatted report.

    Args:
        local_path: Path to the repository to audit.
        level: Maximum maturity level to check (default: 3).
        output_format: Output format - "markdown", "json", or "sarif".
        tags: Filter controls by tags (e.g., "domain=AC", "level=1").
        _framework_name: Internal - set by the factory at registration time.

    Returns:
        Formatted audit report.
    """
    import json as json_mod

    from darnit.config import (
        load_controls_from_effective,
        load_effective_config_by_name,
    )
    from darnit.core.discovery import get_implementation
    from darnit.sieve import CheckContext, SieveOrchestrator
    from darnit.sieve.registry import get_control_registry

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"Error: Repository path not found: {repo_path}"

    if not _framework_name:
        return "Error: No framework name configured for this audit tool."

    # Load effective config (framework TOML merged with user .baseline.toml)
    try:
        config = load_effective_config_by_name(_framework_name, repo_path)
    except Exception as e:
        return f"Error loading framework config '{_framework_name}': {e}"

    # Load TOML-defined controls
    try:
        toml_controls = load_controls_from_effective(config)
    except Exception as e:
        return f"Error loading controls: {e}"

    # Register and load Python-defined controls if implementation exists
    impl = get_implementation(_framework_name)
    if impl and hasattr(impl, "register_controls"):
        try:
            impl.register_controls()
        except Exception as e:
            logger.warning(f"Error registering Python controls: {e}")

    # Merge Python-defined controls that aren't in TOML
    registry = get_control_registry()
    toml_ids = {c.control_id for c in toml_controls}
    python_controls = [
        spec
        for spec in registry.get_all_specs()
        if spec.control_id not in toml_ids
    ]

    all_controls = toml_controls + python_controls

    # Filter by level
    all_controls = [c for c in all_controls if (c.level or 0) <= level]

    # Filter by tags if specified
    if tags:
        try:
            from darnit.filtering import filter_controls, parse_tags_arg

            parsed_tags = parse_tags_arg(tags) if isinstance(tags, str) else tags
            all_controls = filter_controls(all_controls, parsed_tags)
        except ImportError:
            logger.debug("Filtering module not available, skipping tag filter")
        except Exception as e:
            return f"Error filtering controls: {e}"

    all_controls.sort(key=lambda c: c.control_id)

    if not all_controls:
        return "No controls found for the requested level and filters."

    # Detect owner/repo for context
    from darnit.core.utils import detect_owner_repo

    owner, repo = detect_owner_repo(str(repo_path))

    # Run sieve verification
    orchestrator = SieveOrchestrator()
    results: list[dict[str, Any]] = []

    for control in all_controls:
        context = CheckContext(
            owner=owner,
            repo=repo,
            local_path=str(repo_path),
            default_branch="main",
            control_id=control.control_id,
            control_metadata={
                "name": control.name,
                "description": control.description,
            },
        )
        result = orchestrator.verify(control, context)
        results.append(result.to_legacy_dict())

    # Format output
    if output_format == "json":
        return json_mod.dumps(results, indent=2, default=str)

    return _format_audit_report(
        framework_name=_framework_name,
        repo_path=str(repo_path),
        level=level,
        results=results,
    )



def _format_audit_report(
    framework_name: str,
    repo_path: str,
    level: int,
    results: list[dict[str, Any]],
) -> str:
    """Format audit results as a markdown report."""
    passed = [r for r in results if r.get("status") == "PASS"]
    failed = [r for r in results if r.get("status") == "FAIL"]
    warned = [r for r in results if r.get("status") == "WARN"]
    other = [r for r in results if r.get("status") not in ("PASS", "FAIL", "WARN")]

    lines: list[str] = []
    lines.append(f"# {framework_name} Audit Report")
    lines.append("")
    lines.append(f"**Path:** {repo_path}")
    lines.append(f"**Level Assessed:** {level}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Pass | {len(passed)} |")
    lines.append(f"| Fail | {len(failed)} |")
    if warned:
        lines.append(f"| Needs Verification | {len(warned)} |")
    if other:
        lines.append(f"| Other | {len(other)} |")
    lines.append(f"| **Total** | **{len(results)}** |")
    lines.append("")

    # Detailed results
    lines.append("## Results")
    lines.append("")

    if failed:
        lines.append(f"### FAIL ({len(failed)})")
        lines.append("")
        for r in failed:
            cid = r.get("id", "?")
            lvl = r.get("level", "?")
            detail = r.get("details", "No details")
            lines.append(f"- **{cid}** (L{lvl}): {detail}")
        lines.append("")

    if warned:
        lines.append(f"### NEEDS VERIFICATION ({len(warned)})")
        lines.append("")
        for r in warned:
            cid = r.get("id", "?")
            lvl = r.get("level", "?")
            detail = r.get("details", "")
            lines.append(f"- **{cid}** (L{lvl}): {detail}")
        lines.append("")

    if passed:
        lines.append(f"### PASS ({len(passed)})")
        lines.append("")
        for r in passed:
            cid = r.get("id", "?")
            lvl = r.get("level", "?")
            detail = r.get("details", "")
            lines.append(f"- **{cid}** (L{lvl}): {detail}")
        lines.append("")

    if other:
        lines.append(f"### OTHER ({len(other)})")
        lines.append("")
        for r in other:
            cid = r.get("id", "?")
            lvl = r.get("level", "?")
            status = r.get("status", "?")
            detail = r.get("details", "")
            lines.append(f"- **{cid}** (L{lvl}) [{status}]: {detail}")
        lines.append("")

    # Remediation guidance
    if failed:
        lines.append("## Remediation")
        lines.append("")
        lines.append(
            "Run the `remediate` tool to auto-fix controls with "
            "TOML-defined templates."
        )
        lines.append("")

    return "\n".join(lines)


__all__ = ["builtin_audit"]
