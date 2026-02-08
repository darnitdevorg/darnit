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
    verification pipeline via run_sieve_audit(), and returns a formatted report.

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
    from darnit.sieve.registry import get_control_registry
    from darnit.tools.audit import (
        calculate_compliance,
        format_results_markdown,
        run_sieve_audit,
    )

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
    all_controls.sort(key=lambda c: c.control_id)

    if not all_controls:
        return "No controls found for the requested level and filters."

    # Detect owner/repo for context
    from darnit.core.utils import detect_owner_repo

    owner, repo = detect_owner_repo(str(repo_path))

    # Normalize tags
    tags_list: list[str] | None = None
    if tags:
        if isinstance(tags, str):
            tags_list = [tags]
        else:
            tags_list = list(tags)

    # Delegate to canonical audit pipeline
    results, summary = run_sieve_audit(
        owner=owner,
        repo=repo,
        local_path=str(repo_path),
        default_branch="main",
        level=level,
        controls=all_controls,
        tags=tags_list,
        apply_user_config=True,
        stop_on_llm=True,
    )

    # Format output
    if output_format == "json":
        return json_mod.dumps(results, indent=2, default=str)

    # Use implementation display_name for report title
    report_title = f"{impl.display_name} Audit Report" if impl else "Compliance Audit Report"

    compliance = calculate_compliance(results, level)
    return format_results_markdown(
        owner=owner,
        repo=repo,
        results=results,
        summary=summary,
        compliance=compliance,
        level=level,
        local_path=str(repo_path),
        report_title=report_title,
    )


__all__ = ["builtin_audit"]
