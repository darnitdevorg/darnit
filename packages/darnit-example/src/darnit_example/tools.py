"""MCP tool handlers for the Project Hygiene Standard.

This module provides:
- example_hygiene_check: audit all PH controls via the sieve pipeline
- remediate_hygiene: auto-fix failing controls using TOML-defined templates
"""

from __future__ import annotations

from pathlib import Path

# =============================================================================
# Shared helpers
# =============================================================================


def _load_all_controls(repo_path: Path, level: int):
    """Load TOML + Python controls, filter by level, sort."""
    from darnit.config import (
        load_controls_from_effective,
        load_effective_config_by_name,
    )
    from darnit.core.discovery import get_implementation
    from darnit.sieve.registry import get_control_registry

    config = load_effective_config_by_name("example-hygiene", repo_path)
    toml_controls = load_controls_from_effective(config)

    impl = get_implementation("example-hygiene")
    if impl:
        impl.register_controls()

    registry = get_control_registry()
    toml_ids = {c.control_id for c in toml_controls}
    python_controls = [
        spec
        for spec in registry.get_all_specs()
        if spec.control_id.startswith("PH-") and spec.control_id not in toml_ids
    ]

    all_controls = toml_controls + python_controls
    all_controls = [c for c in all_controls if (c.level or 0) <= level]
    all_controls.sort(key=lambda c: c.control_id)
    return all_controls


def _run_audit(repo_path: Path, controls):
    """Run sieve on a list of controls, return legacy result dicts."""
    from darnit.sieve import CheckContext, SieveOrchestrator

    orchestrator = SieveOrchestrator()
    results: list[dict] = []

    for control in controls:
        context = CheckContext(
            owner="",
            repo=repo_path.name,
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

    return results


def _load_framework_config():
    """Load the example-hygiene TOML as a FrameworkConfig."""
    import tomllib

    from darnit.config.framework_schema import FrameworkConfig
    from darnit.core.discovery import get_implementation

    impl = get_implementation("example-hygiene")
    if not impl:
        msg = "example-hygiene implementation not found"
        raise RuntimeError(msg)

    toml_path = impl.get_framework_config_path()
    if not toml_path or not toml_path.exists():
        msg = f"Framework TOML not found: {toml_path}"
        raise RuntimeError(msg)

    with open(toml_path, "rb") as f:
        raw = tomllib.load(f)

    return FrameworkConfig(**raw)


# =============================================================================
# Audit tool
# =============================================================================


async def example_hygiene_check(
    local_path: str = ".",
    level: int = 2,
) -> str:
    """Run a project hygiene audit via the sieve pipeline.

    Loads all PH controls (both TOML-defined and Python-defined), runs each
    through the sieve orchestrator, and returns a markdown audit report.

    Args:
        local_path: Path to the repository to check.
        level: Maximum maturity level to check (1 or 2).

    Returns:
        Markdown-formatted audit report with pass/fail details.
    """
    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"Error: Repository path not found: {repo_path}"

    try:
        controls = _load_all_controls(repo_path, level)
    except Exception as e:
        return f"Error loading controls: {e}"

    if not controls:
        return "No controls found for the requested level."

    results = _run_audit(repo_path, controls)
    return _format_hygiene_report(str(repo_path), level, results)


# =============================================================================
# Remediation tool
# =============================================================================


async def remediate_hygiene(
    local_path: str = ".",
    dry_run: bool = True,
) -> str:
    """Auto-fix failing hygiene controls using TOML-defined templates.

    Runs the audit, then for each failing control that has a remediation
    config with file_create, uses the framework's RemediationExecutor to
    create the missing file from its template.

    Args:
        local_path: Path to the repository to remediate.
        dry_run: If True (default), show what would be created without writing.

    Returns:
        Markdown-formatted remediation report.
    """
    from darnit.config.framework_schema import (
        HandlerInvocation,
        RemediationConfig,
    )
    from darnit.remediation.executor import RemediationExecutor

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"Error: Repository path not found: {repo_path}"

    # Load framework config for templates + remediation configs
    try:
        fw = _load_framework_config()
    except Exception as e:
        return f"Error loading framework config: {e}"

    # Run audit to find failures
    try:
        controls = _load_all_controls(repo_path, level=2)
    except Exception as e:
        return f"Error loading controls: {e}"

    results = _run_audit(repo_path, controls)
    failed_ids = {r["id"] for r in results if r.get("status") == "FAIL"}

    if not failed_ids:
        return "All controls pass — nothing to remediate."

    # Set up executor with templates from TOML
    executor = RemediationExecutor(
        local_path=str(repo_path),
        repo=repo_path.name,
        templates=fw.templates,
    )

    # Remediation configs for Python-defined controls that aren't in the TOML
    # [controls] section but whose templates ARE in TOML [templates].
    _python_remediations: dict[str, RemediationConfig] = {
        "PH-CI-01": RemediationConfig(
            handlers=[
                HandlerInvocation(
                    handler="file_create",
                    path=".github/workflows/ci.yml",
                    template="ci_github_actions",
                    create_dirs=True,
                ),
            ],
        ),
        # PH-DOC-03 is fixed implicitly when PH-DOC-01 creates README.md
        # with the readme_standard template (which has description content).
    }

    # Apply remediations for each failed control
    remediation_results = []
    skipped = []

    for control_id in sorted(failed_ids):
        # Try TOML control config first, then Python-control fallback
        rem_cfg = None
        control_cfg = fw.controls.get(control_id)
        if control_cfg and control_cfg.remediation and control_cfg.remediation.handlers:
            rem_cfg = control_cfg.remediation
        elif control_id in _python_remediations:
            rem_cfg = _python_remediations[control_id]

        if rem_cfg is None:
            skipped.append((control_id, "no file_create remediation (fixed by another control)"))
            continue

        result = executor.execute(control_id, rem_cfg, dry_run=dry_run)
        remediation_results.append(result)

    return _format_remediation_report(
        str(repo_path), dry_run, remediation_results, skipped,
    )


# =============================================================================
# Formatters
# =============================================================================


def _format_hygiene_report(
    repo_path: str,
    level: int,
    results: list[dict],
) -> str:
    """Format audit results as a markdown report."""
    passed = [r for r in results if r.get("status") == "PASS"]
    failed = [r for r in results if r.get("status") == "FAIL"]
    other = [r for r in results if r.get("status") not in ("PASS", "FAIL")]

    lines: list[str] = []
    lines.append("# Project Hygiene Audit Report")
    lines.append("")
    lines.append(f"**Path:** {repo_path}")
    lines.append(f"**Level Assessed:** {level}")
    lines.append("")

    # -- Summary table --------------------------------------------------------
    lines.append("## Summary")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Pass | {len(passed)} |")
    lines.append(f"| Fail | {len(failed)} |")
    if other:
        lines.append(f"| Other | {len(other)} |")
    lines.append(f"| **Total** | **{len(results)}** |")
    lines.append("")

    # -- Results by status ----------------------------------------------------
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

    # -- Remediation guidance -------------------------------------------------
    if failed:
        lines.append("## Remediation")
        lines.append("")
        lines.append(
            "Run `remediate_hygiene` to auto-fix controls with "
            "TOML-defined templates."
        )
        lines.append("")
        lines.append("| Control | What to Create |")
        lines.append("|---------|---------------|")
        remediation_map = {
            "PH-DOC-01": "README.md",
            "PH-DOC-02": "LICENSE",
            "PH-DOC-03": "Add a description section to README.md",
            "PH-SEC-01": "SECURITY.md",
            "PH-CFG-01": ".gitignore",
            "PH-CFG-02": ".editorconfig",
            "PH-QA-01": "CONTRIBUTING.md",
            "PH-CI-01": ".github/workflows/ci.yml",
        }
        for r in failed:
            cid = r.get("id", "?")
            fix = remediation_map.get(cid, "See control description")
            lines.append(f"| {cid} | {fix} |")
        lines.append("")

    return "\n".join(lines)


def _format_remediation_report(
    repo_path: str,
    dry_run: bool,
    results: list,
    skipped: list[tuple[str, str]],
) -> str:
    """Format remediation results as markdown."""
    mode = "DRY RUN" if dry_run else "APPLIED"
    succeeded = [r for r in results if r.success]
    errored = [r for r in results if not r.success]

    lines: list[str] = []
    lines.append(f"# Hygiene Remediation Report ({mode})")
    lines.append("")
    lines.append(f"**Path:** {repo_path}")
    lines.append("")

    if succeeded:
        verb = "Would create" if dry_run else "Created"
        lines.append(f"## {verb} ({len(succeeded)})")
        lines.append("")
        for r in succeeded:
            lines.append(f"- **{r.control_id}**: {r.message}")
        lines.append("")

    if errored:
        lines.append(f"## Errors ({len(errored)})")
        lines.append("")
        for r in errored:
            lines.append(f"- **{r.control_id}**: {r.message}")
        lines.append("")

    if skipped:
        lines.append(f"## Skipped ({len(skipped)})")
        lines.append("")
        for cid, reason in skipped:
            lines.append(f"- **{cid}**: {reason}")
        lines.append("")

    if not dry_run and succeeded:
        lines.append(
            "Run `example_hygiene_check` to verify the fixes."
        )
        lines.append("")

    if dry_run and succeeded:
        lines.append(
            "Run `remediate_hygiene` with `dry_run=false` to apply these changes."
        )
        lines.append("")

    return "\n".join(lines)
