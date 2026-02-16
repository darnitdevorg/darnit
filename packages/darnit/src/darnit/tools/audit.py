"""Audit tool implementations.

This module provides the core audit functionality that can be used
either directly or through MCP tool registration.

Note: The full audit_openssf_baseline implementation remains in main.py
as the main MCP entry point. This module provides supporting functions
and can be used for programmatic access.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger
from darnit.core.utils import (
    detect_repo_from_git,
    validate_local_path,
)

logger = get_logger("tools.audit")

# Sieve system imports - lazy loaded
_sieve_components = None
_toml_controls_registered = False


def _get_sieve_components():
    """Lazily load sieve components."""
    global _sieve_components
    if _sieve_components is None:
        try:
            from darnit.sieve import (
                CheckContext,
                SieveOrchestrator,
                get_control_registry,
            )
            _sieve_components = {
                "SieveOrchestrator": SieveOrchestrator,
                "get_control_registry": get_control_registry,
                "CheckContext": CheckContext,
            }
        except ImportError:
            logger.warning("Sieve components not available")
            _sieve_components = {}
    return _sieve_components


def _register_toml_controls() -> int:
    """Load and register controls from the framework TOML file.

    This enables declarative control definitions from openssf-baseline.toml
    to be used alongside (or instead of) Python-defined controls.

    Returns:
        Number of controls registered from TOML
    """
    global _toml_controls_registered
    if _toml_controls_registered:
        return 0

    framework_path = _get_framework_config_path()
    if not framework_path:
        logger.debug("No framework TOML found, skipping TOML control registration")
        return 0

    try:
        from darnit.config import (
            load_controls_from_framework,
            load_framework_config,
        )
        from darnit.sieve.registry import register_control

        framework = load_framework_config(framework_path)
        controls = load_controls_from_framework(framework)

        registered = 0
        for control in controls:
            # TOML is the primary source of truth — overwrite Python-defined controls
            if register_control(control, overwrite=True):
                registered += 1
                logger.debug(f"Registered TOML control: {control.control_id}")

        _toml_controls_registered = True
        if registered > 0:
            logger.info(f"Registered {registered} controls from {framework_path.name}")
        return registered

    except ImportError as e:
        logger.debug(f"Config loader not available: {e}")
        return 0
    except Exception as e:
        logger.warning(f"Error loading TOML controls: {e}")
        return 0


# =============================================================================
# User Configuration Loading
# =============================================================================

_effective_config_cache: dict[str, Any] = {}


def _get_framework_config_path() -> Path | None:
    """Get path to the framework TOML file via plugin discovery.

    This uses the ComplianceImplementation protocol to get the framework
    config path, avoiding direct imports of implementation packages.

    Returns:
        Path to framework TOML file or None if not found
    """
    try:
        from darnit.core.discovery import get_default_implementation

        impl = get_default_implementation()
        if impl and hasattr(impl, "get_framework_config_path"):
            path = impl.get_framework_config_path()
            if path and path.exists():
                return path
            logger.debug(f"Framework config path from {impl.name} does not exist: {path}")
        elif impl:
            logger.debug(f"Implementation {impl.name} does not provide get_framework_config_path()")
        else:
            logger.debug("No compliance implementation found")

    except Exception as e:
        logger.debug(f"Error locating framework config: {e}")

    return None


def load_effective_audit_config(local_path: str) -> Any | None:
    """Load the effective configuration for auditing.

    This loads the framework config (openssf-baseline.toml) and merges it
    with any user config (.baseline.toml) found in the repository.

    Args:
        local_path: Path to the repository

    Returns:
        EffectiveConfig if successful, None otherwise
    """
    # Check cache first
    abs_path = str(Path(local_path).resolve())
    if abs_path in _effective_config_cache:
        return _effective_config_cache[abs_path]

    try:
        from darnit.config import (
            load_framework_config,
            load_user_config,
            merge_configs,
        )

        # Load framework config
        framework_path = _get_framework_config_path()
        if not framework_path:
            logger.debug("Framework config not found, using legacy checks only")
            return None

        framework = load_framework_config(framework_path)

        # Load user config if exists
        user = load_user_config(Path(local_path))

        # Merge configs
        effective = merge_configs(framework, user)

        # Cache the result
        _effective_config_cache[abs_path] = effective

        if user:
            logger.info(f"Loaded user config from {local_path}/.baseline.toml")
            excluded = effective.get_excluded_controls()
            if excluded:
                logger.info(f"User config excludes {len(excluded)} controls")

        return effective

    except Exception as e:
        logger.warning(f"Error loading effective config: {e}")
        return None


def clear_effective_config_cache():
    """Clear the effective config cache."""
    _effective_config_cache.clear()


def get_excluded_control_ids(local_path: str) -> dict[str, str]:
    """Get control IDs that are excluded via user config.

    Args:
        local_path: Path to the repository

    Returns:
        Dict mapping control_id to exclusion reason
    """
    effective = load_effective_audit_config(local_path)
    if effective:
        return effective.get_excluded_controls()
    return {}


def get_adapter_for_control(control_id: str, local_path: str) -> str | None:
    """Get the adapter name configured for a specific control.

    Args:
        control_id: Control identifier
        local_path: Path to the repository

    Returns:
        Adapter name if configured, None for builtin
    """
    effective = load_effective_audit_config(local_path)
    if effective:
        ctrl = effective.controls.get(control_id)
        if ctrl and ctrl.check_adapter != "builtin":
            return ctrl.check_adapter
    return None


@dataclass
class AuditOptions:
    """Options for running an audit."""
    level: int = 3
    auto_init_config: bool = True
    output_format: str = "markdown"  # markdown, json, sarif
    include_evidence: bool = True
    stop_on_llm: bool = True  # Return PENDING_LLM for LLM consultation


def prepare_audit(
    owner: str | None,
    repo: str | None,
    local_path: str
) -> tuple[str | None, str | None, str, str, str | None]:
    """Prepare for running an audit by validating and resolving inputs.

    Args:
        owner: GitHub org/user (optional, auto-detected if not provided)
        repo: Repository name (optional, auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Tuple of (owner, repo, resolved_path, default_branch, error_message)
        If error_message is not None, preparation failed.
    """
    # Validate local path
    resolved_path, error = validate_local_path(local_path, owner, repo)
    if error:
        return None, None, resolved_path, "main", error

    default_branch = "main"

    # If both owner and repo provided, use them directly
    if owner and repo:
        # Try to get default branch from git, but don't fail if we can't
        detected = detect_repo_from_git(resolved_path)
        if detected:
            default_branch = detected.get("default_branch", "main")
        return owner, repo, resolved_path, default_branch, None

    # Auto-detect owner/repo if not provided
    detected = detect_repo_from_git(resolved_path)
    if detected:
        owner = owner or detected["owner"]
        repo = repo or detected["repo"]
        default_branch = detected.get("default_branch", "main")
        return owner, repo, resolved_path, default_branch, None
    else:
        return None, None, resolved_path, default_branch, (
            "Could not auto-detect owner/repo. "
            "Please provide owner and repo parameters."
        )


def run_checks(
    owner: str,
    repo: str,
    local_path: str,
    default_branch: str,
    level: int = 3,
    stop_on_llm: bool = True,
    apply_user_config: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Run OSPS baseline checks at the specified level.

    Thin wrapper around run_sieve_audit() that returns the
    (results, skipped_controls) tuple expected by CLI and
    remediation orchestrator callers.

    Args:
        owner: GitHub org/user
        repo: Repository name
        local_path: Path to repository
        default_branch: Default branch name
        level: Maximum level to check (1, 2, or 3)
        stop_on_llm: Return PENDING_LLM for LLM consultation
        apply_user_config: Apply .baseline.toml user config overrides

    Returns:
        Tuple of (check_results, skipped_controls)
        where skipped_controls maps control_id to reason
    """
    skipped_controls = get_excluded_control_ids(local_path) if apply_user_config else {}

    results, _summary = run_sieve_audit(
        owner, repo, local_path, default_branch, level,
        apply_user_config=apply_user_config,
        stop_on_llm=stop_on_llm,
    )

    return results, skipped_controls


def run_sieve_audit(
    owner: str,
    repo: str,
    local_path: str,
    default_branch: str,
    level: int = 3,
    *,
    controls: list | None = None,
    tags: list[str] | None = None,
    apply_user_config: bool = True,
    stop_on_llm: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Run a sieve-based compliance audit — the canonical audit pipeline.

    All code paths that run audits MUST delegate to this function.
    No other module SHALL reimplement the sieve verification loop.

    This implements the 4-phase verification model:
    1. DETERMINISTIC - File existence, API checks, config lookups, external commands
    2. PATTERN - Regex matching, content analysis
    3. LLM - LLM-assisted analysis (returns PENDING_LLM for consultation)
    4. MANUAL - Always returns WARN with verification steps

    Args:
        owner: GitHub org/user
        repo: Repository name
        local_path: Path to repository
        default_branch: Default branch name
        level: Maximum level to check (1, 2, or 3)
        controls: Pre-loaded ControlSpec objects. If None, loads from
            TOML/registry automatically.
        tags: Tag filters to apply to controls (e.g., ["domain=AC"]).
        apply_user_config: Apply .baseline.toml user config exclusions.
        stop_on_llm: Return PENDING_LLM for LLM consultation.

    Returns:
        Tuple of (results, summary) where results is a list of check result
        dicts and summary contains status counts (PASS, FAIL, WARN, etc.).
    """
    sieve = _get_sieve_components()
    if not sieve:
        raise RuntimeError(
            "Sieve components not available. "
            "Ensure darnit is properly installed with all dependencies."
        )

    get_control_registry = sieve["get_control_registry"]
    SieveOrchestrator = sieve["SieveOrchestrator"]
    CheckContext = sieve["CheckContext"]

    # Load user config exclusions if enabled
    excluded_ids: set[str] = set()
    if apply_user_config:
        skipped = get_excluded_control_ids(local_path)
        excluded_ids = set(skipped.keys())
        if excluded_ids:
            logger.info(f"Skipping {len(excluded_ids)} controls per user config")

    # Resolve controls: use provided list or load from TOML/registry
    if controls is not None:
        all_controls = list(controls)
    else:
        # Register Python-defined controls via plugin system
        try:
            from darnit.core.discovery import get_default_implementation

            impl = get_default_implementation()
            if impl and hasattr(impl, "register_controls"):
                impl.register_controls()
                logger.debug(f"Registered Python control definitions from {impl.name}")
            elif impl:
                logger.debug(f"Implementation {impl.name} does not provide register_controls()")
            else:
                logger.debug("No compliance implementation found for control registration")
        except Exception as e:
            logger.debug(f"Python control modules not available: {e}")

        # Register controls from TOML framework definition (primary source of truth)
        _register_toml_controls()

        registry = get_control_registry()
        all_controls = []
        for lvl in range(1, level + 1):
            all_controls.extend(registry.get_specs_by_level(lvl))

    # Filter by level (applies to both provided and loaded controls)
    all_controls = [c for c in all_controls if (c.level or 0) <= level]

    # Filter by tags if specified
    if tags:
        try:
            from darnit.filtering import filter_controls, parse_tags_arg
            tag_filters = parse_tags_arg(tags) if isinstance(tags, (str, list)) else tags
            if isinstance(tag_filters, str):
                tag_filters = [tag_filters]
            all_controls = filter_controls(all_controls, tag_filters)
        except ImportError:
            logger.debug("Filtering module not available, skipping tag filter")

    orchestrator = SieveOrchestrator(stop_on_llm=stop_on_llm)
    all_results = []

    # Create UnifiedLocator for .project/-aware file resolution
    locator = None
    try:
        from darnit.locate import UnifiedLocator
        locator = UnifiedLocator(local_path)
        logger.debug("UnifiedLocator created for .project/ integration")
    except ImportError:
        logger.debug("UnifiedLocator not available, using direct file resolution")
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
        logger.warning(f"Failed to create UnifiedLocator: {e}")

    # Run sieve verification for each control
    for spec in all_controls:
        control_id = spec.control_id

        # Handle user config exclusions
        if control_id in excluded_ids:
            all_results.append({
                "id": control_id,
                "status": "N/A",
                "details": "Excluded via .baseline.toml",
                "level": spec.level or 1,
            })
            continue

        # Create check context
        context = CheckContext(
            owner=owner,
            repo=repo,
            local_path=local_path,
            default_branch=default_branch,
            control_id=control_id,
            control_metadata={
                "name": spec.name,
                "description": spec.description,
                "full": spec.metadata.get("full", ""),
            },
            locator=locator,
            locator_config=spec.locator_config,
        )

        # Run sieve verification
        sieve_result = orchestrator.verify(spec, context)

        # Convert to legacy dict format
        all_results.append(sieve_result.to_legacy_dict())

    summary = summarize_results(all_results)

    # Write results to cache so remediate can skip re-running the audit.
    # Failures here must never break the audit pipeline.
    try:
        from darnit.core.audit_cache import write_audit_cache
        from darnit.core.discovery import get_default_implementation as _get_impl

        fw_name = ""
        _impl = _get_impl()
        if _impl:
            fw_name = _impl.name
        write_audit_cache(local_path, all_results, summary, level, fw_name)
    except Exception as exc:
        logger.warning("Failed to write audit cache (non-fatal): %s", exc)

    return all_results, summary


def calculate_compliance(
    results: list[dict[str, Any]],
    level: int = 3
) -> dict[int, bool]:
    """Calculate level compliance from check results.

    A level is compliant only when every applicable control at that level
    has explicitly PASSED.  Controls that are WARN (needs verification),
    FAIL, ERROR, or PENDING_LLM are all treated as non-compliant because
    we cannot confirm the control is satisfied.  Only N/A controls are
    excluded from the calculation.

    Args:
        results: List of check results
        level: Maximum level to calculate

    Returns:
        Dict mapping level number to compliance status
    """
    compliance = {}

    for lvl in range(1, level + 1):
        level_results = [
            r for r in results
            if r.get("level", 1) == lvl and r.get("status") != "N/A"
        ]
        all_pass = all(r.get("status") == "PASS" for r in level_results)
        compliance[lvl] = all_pass and len(level_results) > 0

    return compliance


def summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    """Summarize check results by status.

    Args:
        results: List of check results

    Returns:
        Dict with status counts
    """
    summary = {
        "PASS": 0,
        "FAIL": 0,
        "WARN": 0,
        "N/A": 0,
        "ERROR": 0,
        "PENDING_LLM": 0,  # Sieve: awaiting LLM consultation
        "total": len(results)
    }

    for r in results:
        status = r.get("status", "ERROR")
        if status in summary:
            summary[status] += 1
        else:
            summary["ERROR"] += 1

    return summary


def _get_control_help(control_id: str) -> str | None:
    """Get help_md for a control from the framework config.

    Args:
        control_id: Control identifier (e.g., "OSPS-BR-04.01")

    Returns:
        Help markdown string or None if not found
    """
    try:
        framework_path = _get_framework_config_path()
        if not framework_path:
            return None

        from darnit.config import load_framework_config
        framework = load_framework_config(framework_path)

        if framework.controls and control_id in framework.controls:
            return framework.controls[control_id].help_md
    except Exception:
        pass
    return None


def format_results_markdown(
    owner: str,
    repo: str,
    results: list[dict[str, Any]],
    summary: dict[str, int],
    compliance: dict[int, bool],
    level: int,
    local_path: str | None = None,
    report_title: str = "Compliance Audit Report",
    remediation_map: dict[str, Any] | None = None,
) -> str:
    """Format audit results as Markdown.

    Args:
        owner: Repository owner
        repo: Repository name
        results: List of check results
        summary: Status summary
        compliance: Level compliance
        level: Maximum level checked
        local_path: Path to the repository (for pending context)
        report_title: Title for the report H1 heading.
        remediation_map: Implementation-provided mapping of control IDs to
            remediation tools. Structure:
            {
                "groups": [{"name": str, "tool": str, "description": str,
                            "control_ids": set[str]}],
                "bulk_tool": str,
                "bulk_description": str,
                "branch_name": str,
                "framework_name": str,
            }

    Returns:
        Markdown-formatted report
    """
    lines = [
        f"# {report_title}",
        "",
        f"**Repository:** {owner}/{repo}",
        f"**Level Assessed:** {level}",
        "",
        "## Summary",
        "",
        "| Status | Count | Meaning |",
        "|--------|-------|---------|",
        f"| ✅ Pass | {summary['PASS']} | Control satisfied |",
        f"| ❌ Fail | {summary['FAIL']} | **Control NOT satisfied - action required** |",
        f"| ⚠️ Needs Verification | {summary['WARN']} | **Could not verify automatically - manual review required** |",
        f"| 🤖 Pending LLM | {summary.get('PENDING_LLM', 0)} | Awaiting LLM analysis |",
        f"| ➖ N/A | {summary['N/A']} | Not applicable to this project |",
        f"| 🔴 Error | {summary['ERROR']} | Check could not run |",
        f"| **Total** | {summary['total']} | |",
        "",
        "> **Important:** Items marked ⚠️ Needs Verification are NOT informational warnings.",
        "> They represent controls that could not be automatically verified and **require manual review**",
        "> to determine compliance. Treat these as potential failures until verified.",
        "",
        "> **🔧 Remediation:** To fix failures, use the MCP tools provided by this server:",
        "> - `remediate_audit_findings()` - Auto-fix multiple issues",
        "> - `enable_branch_protection()` - Configure branch protection",
        "> - `create_security_policy()` - Generate SECURITY.md",
        "> ",
        "> **🔀 Git Workflow:** Use MCP tools for version control:",
        "> - `create_remediation_branch()` → `commit_remediation_changes()` → `create_remediation_pr()`",
        "> ",
        "> **Do NOT run `gh` or `git` commands directly.** Always use the MCP tools for remediation.",
        "",
        "## Level Compliance",
        "",
    ]

    for lvl in range(1, level + 1):
        if compliance.get(lvl, False):
            lines.append(f"- **Level {lvl}:** ✅ Compliant")
        else:
            # Show breakdown of what's blocking compliance
            lvl_results = [
                r for r in results
                if r.get("level", 1) == lvl and r.get("status") != "N/A"
            ]
            n_pass = sum(1 for r in lvl_results if r.get("status") == "PASS")
            n_fail = sum(1 for r in lvl_results if r.get("status") == "FAIL")
            n_warn = sum(1 for r in lvl_results if r.get("status") == "WARN")
            n_other = len(lvl_results) - n_pass - n_fail - n_warn
            parts = []
            if n_fail:
                parts.append(f"{n_fail} failed")
            if n_warn:
                parts.append(f"{n_warn} unverified")
            if n_other:
                parts.append(f"{n_other} error/pending")
            detail = ", ".join(parts) if parts else "no controls passed"
            lines.append(f"- **Level {lvl}:** ❌ Not Compliant ({detail})")

    lines.append("")
    lines.append("## Detailed Results")
    lines.append("")

    # Status display configuration with clear action-oriented labels
    status_config = {
        "FAIL": {"icon": "❌", "label": "FAIL - Action Required", "description": "These controls are NOT satisfied and must be addressed:"},
        "PENDING_LLM": {"icon": "🤖", "label": "PENDING LLM ANALYSIS", "description": "These controls require LLM-assisted analysis. Review the consultation prompts below:"},
        "WARN": {"icon": "⚠️", "label": "NEEDS VERIFICATION - Manual Review Required", "description": "These controls could not be automatically verified. They may be failing and require manual inspection:"},
        "ERROR": {"icon": "🔴", "label": "ERROR - Check Failed", "description": "These checks encountered errors and need investigation:"},
        "PASS": {"icon": "✅", "label": "PASS", "description": "These controls are satisfied:"},
        "N/A": {"icon": "➖", "label": "N/A", "description": "These controls don't apply to this project:"},
    }

    # Group by status
    for status in ["FAIL", "PENDING_LLM", "WARN", "ERROR", "PASS", "N/A"]:
        status_results = [r for r in results if r.get("status") == status]
        if status_results:
            config = status_config.get(status, {"icon": "", "label": status, "description": ""})
            lines.append(f"### {config['icon']} {config['label']} ({len(status_results)})")
            lines.append("")
            if config['description']:
                lines.append(f"*{config['description']}*")
                lines.append("")
            for r in status_results:
                control_id = r.get('id', '')
                details = r.get('details', 'No details')

                # Task 8.2: Annotate inferred PASSes with source control
                if status == "PASS" and "Inferred from" in details:
                    lines.append(f"- **{control_id}** (L{r.get('level', 1)}): {details} *(inferred)*")
                else:
                    lines.append(f"- **{control_id}** (L{r.get('level', 1)}): {details}")

                # Include help_md for failed controls to explain remediation options
                if status == "FAIL":
                    help_md = _get_control_help(control_id)
                    if help_md:
                        # Indent help text and add as a sub-item
                        help_lines = help_md.strip().split('\n')
                        lines.append("")
                        lines.append(f"  > **ℹ️ Note for {control_id}:**")
                        for help_line in help_lines[:10]:  # Limit to first 10 lines
                            lines.append(f"  > {help_line}")
                        if len(help_lines) > 10:
                            lines.append("  > *(truncated)*")
                        lines.append("")

                # Task 8.1: Show unmet when conditions for N/A controls
                if status == "N/A":
                    sieve_evidence = r.get("evidence") if isinstance(r.get("evidence"), dict) else None
                    when_clause = sieve_evidence.get("when") if sieve_evidence else None
                    if when_clause and isinstance(when_clause, dict):
                        conditions = ", ".join(
                            f"`{k}={v}`" for k, v in when_clause.items()
                        )
                        lines.append(f"  - Requires: {conditions}")

            lines.append("")

    # Add remediation section if there are failures
    fail_results = [r for r in results if r.get("status") == "FAIL"]
    if fail_results:
        lines.append("---")
        lines.append("")
        lines.append("## 🔧 Recommended Remediation")
        lines.append("")
        lines.append("**IMPORTANT: Use the MCP tools below to fix issues. Do NOT run shell commands directly.**")
        lines.append("")

        # Determine which remediation categories apply
        control_ids = {r.get("id", "") for r in fail_results}

        # Build remediation suggestions from implementation-provided map
        remediation_suggestions = []
        if remediation_map:
            for group in remediation_map.get("groups", []):
                matched = control_ids & set(group.get("control_ids", set()))
                if matched:
                    remediation_suggestions.append({
                        "tool": group["tool"],
                        "description": group["description"],
                        "controls": sorted(matched),
                    })

            # General bulk remediation for multiple issues
            bulk_tool = remediation_map.get("bulk_tool")
            if bulk_tool and len(fail_results) > 2:
                remediation_suggestions.insert(0, {
                    "tool": bulk_tool,
                    "description": remediation_map.get("bulk_description", "Auto-fix multiple issues"),
                    "controls": ["multiple"],
                })

        # Extract shared values from remediation_map
        bulk_tool_name = remediation_map.get("bulk_tool", "remediate_audit_findings") if remediation_map else "remediate_audit_findings"
        branch_name = remediation_map.get("branch_name", "fix/compliance") if remediation_map else "fix/compliance"
        framework_name = remediation_map.get("framework_name", "Compliance") if remediation_map else "Compliance"

        if remediation_suggestions:
            lines.append("### Available MCP Tools")
            lines.append("")
            for suggestion in remediation_suggestions:
                lines.append(f"**`{suggestion['tool']}()`** - {suggestion['description']}")
                if suggestion['controls'] != ["multiple"]:
                    lines.append(f"  - Fixes: {', '.join(suggestion['controls'])}")
                lines.append("")

            lines.append("### Example Usage")
            lines.append("")
            lines.append("```python")
            lines.append("# Fix all applicable issues automatically")
            lines.append(f'{bulk_tool_name}(local_path="/path/to/repo", dry_run=False)')
            lines.append("```")
            lines.append("")

        lines.append("### 🔀 Git Workflow for Remediations")
        lines.append("")
        lines.append("Use these MCP tools to manage remediation changes through Git:")
        lines.append("")
        lines.append("| Step | Tool | Description |")
        lines.append("|------|------|-------------|")
        lines.append("| 1 | `create_remediation_branch()` | Create a dedicated branch for fixes |")
        lines.append("| 2 | *remediation tools above* | Apply the fixes |")
        lines.append("| 3 | `commit_remediation_changes()` | Commit with auto-generated message |")
        lines.append("| 4 | `create_remediation_pr()` | Open PR with compliance summary |")
        lines.append("")
        lines.append("**Recommended workflow:**")
        lines.append("```python")
        lines.append("# 1. Create a branch for remediation work")
        lines.append(f'create_remediation_branch(branch_name="{branch_name}", local_path="/path/to/repo")')
        lines.append("")
        lines.append("# 2. Apply remediations (files will be created/modified)")
        lines.append(f'{bulk_tool_name}(local_path="/path/to/repo")')
        lines.append("")
        lines.append("# 3. Commit the changes")
        lines.append(f'commit_remediation_changes(message="Add {framework_name} compliance files", local_path="/path/to/repo")')
        lines.append("")
        lines.append("# 4. Open a pull request")
        lines.append(f'create_remediation_pr(title="{framework_name} Compliance", local_path="/path/to/repo")')
        lines.append("```")
        lines.append("")
        lines.append("Use `get_remediation_status()` at any time to check current git state and next steps.")
        lines.append("")

        lines.append("> ⚠️ **Never run `gh api`, `git`, or other shell commands directly for remediation.**")
        lines.append("> Always use the MCP tools provided by this server to ensure proper error handling")
        lines.append("> and consistent implementation.")
        lines.append("")

    # Add "Next Steps" section with ordered agent directives
    next_steps_lines = _get_next_steps_section(local_path, summary)
    if next_steps_lines:
        lines.extend(next_steps_lines)

    return "\n".join(lines)


def _get_next_steps_section(
    local_path: str | None,
    summary: dict[str, int],
) -> list[str]:
    """Get the "Next Steps" section with ordered agent directives.

    Produces imperative instructions for LLM agents:
    1. Collect pending context (if any) with ready-to-execute tool calls
    2. Remediate failures (if any)
    3. Review manual controls (if WARN results exist)

    Steps are numbered dynamically — only applicable steps appear.

    Args:
        local_path: Path to the repository
        summary: Status summary dict with FAIL, WARN counts etc.

    Returns:
        List of markdown lines, or empty list when no steps apply
    """
    # Determine which steps are needed
    has_failures = summary.get("FAIL", 0) > 0
    has_warnings = summary.get("WARN", 0) > 0

    # Check for pending context
    pending_context = []
    if local_path is not None:
        try:
            from darnit.config.context_storage import get_pending_context

            pending_context = get_pending_context(local_path)
        except ImportError:
            logger.debug("Context storage not available for next steps section")
        except Exception as e:
            logger.debug(f"Error getting pending context: {e}")

    has_pending_context = len(pending_context) > 0

    # No steps needed
    if not has_pending_context and not has_failures and not has_warnings:
        return []

    lines = [
        "---",
        "",
        "## Next Steps",
        "",
    ]

    step = 1

    # Step: Collect pending context
    if has_pending_context:
        lines.extend(_format_context_collection_step(
            step, pending_context, local_path or "."
        ))
        step += 1

    # Step: Remediate failures
    if has_failures:
        lines.append(f"**Step {step}: Remediate failures** ({summary['FAIL']} controls failed)")
        lines.append("")
        lines.append("```python")
        lines.append(f'remediate_audit_findings(local_path="{local_path}", dry_run=True)')
        lines.append("```")
        lines.append("")
        step += 1

    # Step: Manual review
    if has_warnings:
        lines.append(f"**Step {step}: Review manual controls** ({summary['WARN']} controls need verification)")
        lines.append("")
        lines.append("These controls could not be verified automatically. Review the ⚠️ items above")
        lines.append("and confirm whether they pass or fail for your project.")
        lines.append("")

    lines.append("---")
    lines.append("")

    return lines


def _format_context_collection_step(
    step: int,
    pending: list,
    local_path: str,
) -> list[str]:
    """Format the context collection step with grouped tool calls.

    Auto-detected values are combined into a single compound
    confirm_project_context() call. Unknown values are listed individually.

    Args:
        step: Step number for display
        pending: List of ContextPromptRequest items
        local_path: Path to the repository

    Returns:
        List of markdown lines for the context collection step
    """
    lines = []

    # Split into auto-detected vs unknown
    auto_detected = [p for p in pending if p.current_value is not None][:8]
    unknown = [p for p in pending if p.current_value is None][:8]

    lines.append(f"**Step {step}: Confirm project context** (improves audit accuracy)")
    lines.append("")

    # Auto-detected values: single compound tool call
    if auto_detected:
        lines.append("The following values were auto-detected. Verify and correct if needed, then execute:")
        lines.append("")
        lines.append("```python")
        lines.append("confirm_project_context(")
        lines.append(f'    local_path="{local_path}",')
        for item in auto_detected:
            value = item.current_value.value
            comment = f"  # {item.current_value.detection_method}" if hasattr(item.current_value, "detection_method") and item.current_value.detection_method else ""
            if isinstance(value, list):
                formatted = [f'"{v}"' for v in value]
                lines.append(f"    {item.key}=[{', '.join(formatted)}],{comment}")
            elif isinstance(value, bool):
                lines.append(f"    {item.key}={value},{comment}")
            elif isinstance(value, str):
                lines.append(f'    {item.key}="{value}",{comment}')
            else:
                lines.append(f"    {item.key}={value!r},{comment}")
        lines.append(")")
        lines.append("```")
        lines.append("")

    # Unknown values: individual prompts
    if unknown:
        lines.append("The following context needs your input:")
        lines.append("")
        for item in unknown:
            lines.append(f"- **{item.key}**: {item.definition.prompt}")
            if item.definition.values:
                values_str = ", ".join(f"`{v}`" for v in item.definition.values[:6])
                lines.append(f"  Options: {values_str}")
            elif item.definition.hint:
                lines.append(f"  *{item.definition.hint}*")
            lines.append("  ```python")
            lines.append(f'  confirm_project_context({item.key}="<ask user>")')
            lines.append("  ```")
            lines.append("")

    # Overflow indicator
    total_pending = len(pending)
    shown = len(auto_detected) + len(unknown)
    if total_pending > shown:
        lines.append(f"*...and {total_pending - shown} more. Use `get_pending_context()` to see all.*")
        lines.append("")

    # Re-audit directive
    lines.append(f'> After confirming context, re-run the audit for updated results: `audit_openssf_baseline(local_path="{local_path}")`')
    lines.append("")

    return lines


def list_available_checks() -> dict[str, list[dict[str, Any]]]:
    """List all available OSPS baseline checks.

    Returns:
        Dict with checks organized by level
    """
    # This is a summary of available checks
    # The actual check implementations are in the checks module
    return {
        "level_1": {
            "count": 24,
            "domains": ["AC", "BR", "DO", "GV", "LE", "QA", "VM"],
            "description": "Basic security hygiene for all projects"
        },
        "level_2": {
            "count": 18,
            "domains": ["AC", "BR", "DO", "GV", "LE", "QA", "SA", "VM"],
            "description": "Enhanced security for projects with moderate risk"
        },
        "level_3": {
            "count": 19,
            "domains": ["AC", "BR", "DO", "GV", "QA", "SA", "VM"],
            "description": "Comprehensive security for high-risk projects"
        },
        "total": 61,
        "specification": "OSPS v2025.10.10",
        "url": "https://baseline.openssf.org/versions/2025-10-10"
    }


__all__ = [
    "AuditOptions",
    "prepare_audit",
    "run_sieve_audit",
    "run_checks",
    "calculate_compliance",
    "summarize_results",
    "format_results_markdown",
    "list_available_checks",
    # User config integration
    "load_effective_audit_config",
    "get_excluded_control_ids",
    "get_adapter_for_control",
    "clear_effective_config_cache",
    # TOML framework support
    "_register_toml_controls",  # Internal but useful for testing
]
