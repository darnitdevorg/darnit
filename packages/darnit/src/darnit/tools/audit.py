"""Audit tool implementations.

This module provides the core audit functionality that can be used
either directly or through MCP tool registration.

Note: The full audit_openssf_baseline implementation remains in main.py
as the main MCP entry point. This module provides supporting functions
and can be used for programmatic access.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass

from darnit.core.logging import get_logger
from darnit.core.models import AuditResult, CheckStatus
from darnit.core.utils import (
    validate_local_path,
    detect_repo_from_git,
    get_git_commit,
    get_git_ref,
)

logger = get_logger("tools.audit")

# Check functions are loaded lazily from the registered implementation via plugin system
_check_functions = None


def _get_check_functions():
    """Lazily load check functions from the discovered implementation."""
    global _check_functions
    if _check_functions is None:
        from darnit.core.discovery import get_default_implementation

        impl = get_default_implementation()
        if impl:
            _check_functions = impl.get_check_functions()
            logger.info(f"Using check functions from {impl.name} v{impl.version}")
        else:
            logger.warning("No compliance implementation found. Install darnit-baseline or another implementation.")
            _check_functions = {
                "level1": lambda *args, **kwargs: [],
                "level2": lambda *args, **kwargs: [],
                "level3": lambda *args, **kwargs: [],
            }
    return _check_functions


# Sieve system imports - also lazy loaded
_sieve_components = None
_toml_controls_registered = False


def _get_sieve_components():
    """Lazily load sieve components."""
    global _sieve_components
    if _sieve_components is None:
        try:
            from darnit.sieve import (
                SieveOrchestrator,
                get_control_registry,
                CheckContext,
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
            load_framework_config,
            load_controls_from_framework,
        )
        from darnit.sieve.registry import register_control

        framework = load_framework_config(framework_path)
        controls = load_controls_from_framework(framework)

        registered = 0
        for control in controls:
            try:
                register_control(control)
                registered += 1
                logger.debug(f"Registered TOML control: {control.control_id}")
            except ValueError:
                # Control already registered (likely from Python)
                logger.debug(f"Skipping {control.control_id}: already registered")

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

_effective_config_cache: Dict[str, Any] = {}


def _get_framework_config_path() -> Optional[Path]:
    """Get path to the framework TOML file from the installed package.

    Returns:
        Path to openssf-baseline.toml or None if not found
    """
    try:
        import darnit_baseline
        # darnit_baseline.__file__ is like:
        # .../packages/darnit-baseline/src/darnit_baseline/__init__.py
        # We need: .../packages/darnit-baseline/openssf-baseline.toml
        init_path = Path(darnit_baseline.__file__)
        # Go up: __init__.py -> darnit_baseline -> src -> darnit-baseline
        package_root = init_path.parent.parent.parent

        # Try standard locations
        candidates = [
            package_root / "openssf-baseline.toml",
            init_path.parent / "openssf-baseline.toml",  # Inside package
            package_root / "src" / "openssf-baseline.toml",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

    except ImportError:
        logger.debug("darnit_baseline not installed")
    except Exception as e:
        logger.debug(f"Error locating framework config: {e}")

    return None


def load_effective_audit_config(local_path: str) -> Optional[Any]:
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
            EffectiveConfig,
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


def get_excluded_control_ids(local_path: str) -> Dict[str, str]:
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


def get_adapter_for_control(control_id: str, local_path: str) -> Optional[str]:
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
    use_sieve: bool = False  # Enable progressive verification pipeline
    stop_on_llm: bool = True  # Return PENDING_LLM for LLM consultation


def prepare_audit(
    owner: Optional[str],
    repo: Optional[str],
    local_path: str
) -> Tuple[Optional[str], Optional[str], str, str, Optional[str]]:
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
    use_sieve: bool = False,
    stop_on_llm: bool = True,
    apply_user_config: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Run OSPS baseline checks at the specified level.

    Args:
        owner: GitHub org/user
        repo: Repository name
        local_path: Path to repository
        default_branch: Default branch name
        level: Maximum level to check (1, 2, or 3)
        use_sieve: Enable progressive verification pipeline
        stop_on_llm: Return PENDING_LLM for LLM consultation (when use_sieve=True)
        apply_user_config: Apply .baseline.toml user config overrides

    Returns:
        Tuple of (check_results, skipped_controls)
        where skipped_controls maps control_id to reason
    """
    # Load user config exclusions if enabled
    skipped_controls: Dict[str, str] = {}
    excluded_ids: Set[str] = set()

    if apply_user_config:
        skipped_controls = get_excluded_control_ids(local_path)
        excluded_ids = set(skipped_controls.keys())
        if excluded_ids:
            logger.info(f"Skipping {len(excluded_ids)} controls per user config")

    if use_sieve:
        results = _run_sieve_checks(
            owner, repo, local_path, default_branch, level, stop_on_llm
        )
    else:
        # Legacy check execution
        results = []
        check_funcs = _get_check_functions()

        # Run Level 1 checks (always)
        if level >= 1:
            results.extend(check_funcs["level1"](owner, repo, local_path, default_branch))

        # Run Level 2 checks
        if level >= 2:
            results.extend(check_funcs["level2"](owner, repo, local_path, default_branch))

        # Run Level 3 checks
        if level >= 3:
            results.extend(check_funcs["level3"](owner, repo, local_path, default_branch))

    # Filter out excluded controls and mark them as N/A
    if excluded_ids:
        filtered_results = []
        for r in results:
            control_id = r.get("id", "")
            if control_id in excluded_ids:
                # Replace result with N/A status
                filtered_results.append({
                    "id": control_id,
                    "status": "N/A",
                    "details": f"Excluded via .baseline.toml: {skipped_controls.get(control_id, 'User override')}",
                    "level": r.get("level", 1),
                })
            else:
                filtered_results.append(r)
        results = filtered_results

    return results, skipped_controls


def run_checks_legacy(
    owner: str,
    repo: str,
    local_path: str,
    default_branch: str,
    level: int = 3,
    use_sieve: bool = False,
    stop_on_llm: bool = True,
) -> List[Dict[str, Any]]:
    """Run OSPS baseline checks (legacy API without user config).

    This is a backwards-compatible wrapper that ignores user config.

    Args:
        owner: GitHub org/user
        repo: Repository name
        local_path: Path to repository
        default_branch: Default branch name
        level: Maximum level to check (1, 2, or 3)
        use_sieve: Enable progressive verification pipeline
        stop_on_llm: Return PENDING_LLM for LLM consultation

    Returns:
        List of check results
    """
    results, _ = run_checks(
        owner, repo, local_path, default_branch,
        level, use_sieve, stop_on_llm,
        apply_user_config=False
    )
    return results


def _run_sieve_checks(
    owner: str,
    repo: str,
    local_path: str,
    default_branch: str,
    level: int,
    stop_on_llm: bool,
) -> List[Dict[str, Any]]:
    """Run checks using the progressive sieve verification pipeline.

    This implements the 4-phase verification model:
    1. DETERMINISTIC - File existence, API checks, config lookups, external commands
    2. PATTERN - Regex matching, content analysis
    3. LLM - LLM-assisted analysis (returns PENDING_LLM for consultation)
    4. MANUAL - Always returns WARN with verification steps

    Controls can be defined either in Python (via level1.py, level2.py, level3.py)
    or declaratively in TOML (via openssf-baseline.toml).

    Args:
        owner: GitHub org/user
        repo: Repository name
        local_path: Path to repository
        default_branch: Default branch name
        level: Maximum level to check (1, 2, or 3)
        stop_on_llm: Return PENDING_LLM for LLM consultation

    Returns:
        List of check results in legacy format
    """
    sieve = _get_sieve_components()
    if not sieve:
        logger.warning("Sieve components not available, falling back to legacy checks")
        # Use legacy execution directly (don't go through run_checks to avoid recursion)
        results = []
        check_funcs = _get_check_functions()
        if level >= 1:
            results.extend(check_funcs["level1"](owner, repo, local_path, default_branch))
        if level >= 2:
            results.extend(check_funcs["level2"](owner, repo, local_path, default_branch))
        if level >= 3:
            results.extend(check_funcs["level3"](owner, repo, local_path, default_branch))
        return results

    get_control_registry = sieve["get_control_registry"]
    SieveOrchestrator = sieve["SieveOrchestrator"]
    CheckContext = sieve["CheckContext"]

    # Register controls from TOML framework definition
    # This enables declarative control definitions alongside Python-defined controls
    _register_toml_controls()

    registry = get_control_registry()
    orchestrator = SieveOrchestrator(stop_on_llm=stop_on_llm)
    all_results = []

    # Get all control specs for requested levels
    sieve_control_ids = set()
    for lvl in range(1, level + 1):
        specs = registry.get_specs_by_level(lvl)
        sieve_control_ids.update(spec.control_id for spec in specs)

    # Run legacy checks for all levels
    check_funcs = _get_check_functions()
    legacy_results = []
    if level >= 1:
        legacy_results.extend(check_funcs["level1"](owner, repo, local_path, default_branch))
    if level >= 2:
        legacy_results.extend(check_funcs["level2"](owner, repo, local_path, default_branch))
    if level >= 3:
        legacy_results.extend(check_funcs["level3"](owner, repo, local_path, default_branch))

    # Process each result - use sieve when available, otherwise keep legacy
    processed_control_ids = set()

    for legacy_result in legacy_results:
        control_id = legacy_result.get("id", "")

        if control_id in processed_control_ids:
            continue

        if control_id in sieve_control_ids:
            # Use sieve for this control
            spec = registry.get(control_id)
            if spec:
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
                )

                # Run sieve verification
                sieve_result = orchestrator.verify(spec, context)

                # Convert to legacy format
                all_results.append(sieve_result.to_legacy_dict())
                processed_control_ids.add(control_id)
                continue

        # Keep legacy result for non-sieve controls
        all_results.append(legacy_result)
        processed_control_ids.add(control_id)

    return all_results


def calculate_compliance(
    results: List[Dict[str, Any]],
    level: int = 3
) -> Dict[int, bool]:
    """Calculate level compliance from check results.

    Args:
        results: List of check results
        level: Maximum level to calculate

    Returns:
        Dict mapping level number to compliance status
    """
    compliance = {}

    for lvl in range(1, level + 1):
        level_results = [r for r in results if r.get("level", 1) == lvl]
        level_failures = [r for r in level_results if r.get("status") == "FAIL"]
        compliance[lvl] = len(level_failures) == 0

    return compliance


def summarize_results(results: List[Dict[str, Any]]) -> Dict[str, int]:
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


def format_results_markdown(
    owner: str,
    repo: str,
    results: List[Dict[str, Any]],
    summary: Dict[str, int],
    compliance: Dict[int, bool],
    level: int
) -> str:
    """Format audit results as Markdown.

    Args:
        owner: Repository owner
        repo: Repository name
        results: List of check results
        summary: Status summary
        compliance: Level compliance
        level: Maximum level checked

    Returns:
        Markdown-formatted report
    """
    lines = [
        f"# OpenSSF Baseline Audit Report",
        f"",
        f"**Repository:** {owner}/{repo}",
        f"**Level Assessed:** {level}",
        f"",
        f"## Summary",
        f"",
        f"| Status | Count | Meaning |",
        f"|--------|-------|---------|",
        f"| ✅ Pass | {summary['PASS']} | Control satisfied |",
        f"| ❌ Fail | {summary['FAIL']} | **Control NOT satisfied - action required** |",
        f"| ⚠️ Needs Verification | {summary['WARN']} | **Could not verify automatically - manual review required** |",
        f"| 🤖 Pending LLM | {summary.get('PENDING_LLM', 0)} | Awaiting LLM analysis |",
        f"| ➖ N/A | {summary['N/A']} | Not applicable to this project |",
        f"| 🔴 Error | {summary['ERROR']} | Check could not run |",
        f"| **Total** | {summary['total']} | |",
        f"",
        f"> **Important:** Items marked ⚠️ Needs Verification are NOT informational warnings.",
        f"> They represent controls that could not be automatically verified and **require manual review**",
        f"> to determine compliance. Treat these as potential failures until verified.",
        f"",
        f"> **🔧 Remediation:** To fix failures, use the MCP tools provided by this server:",
        f"> - `remediate_audit_findings()` - Auto-fix multiple issues",
        f"> - `enable_branch_protection()` - Configure branch protection",
        f"> - `create_security_policy()` - Generate SECURITY.md",
        f"> ",
        f"> **🔀 Git Workflow:** Use MCP tools for version control:",
        f"> - `create_remediation_branch()` → `commit_remediation_changes()` → `create_remediation_pr()`",
        f"> ",
        f"> **Do NOT run `gh` or `git` commands directly.** Always use the MCP tools for remediation.",
        f"",
        f"## Level Compliance",
        f"",
    ]

    for lvl in range(1, level + 1):
        status = "✅ Compliant" if compliance.get(lvl, False) else "❌ Not Compliant"
        lines.append(f"- **Level {lvl}:** {status}")

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
                lines.append(f"- **{r['id']}** (L{r.get('level', 1)}): {r.get('details', 'No details')}")
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

        # Map controls to remediation tools
        remediation_suggestions = []

        # Branch protection controls
        branch_controls = {"OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-QA-07.01", "OSPS-QA-03.01"}
        if control_ids & branch_controls:
            remediation_suggestions.append({
                "tool": "enable_branch_protection",
                "description": "Configure branch protection rules",
                "controls": sorted(control_ids & branch_controls)
            })

        # Security policy controls
        security_controls = {"OSPS-VM-01.01", "OSPS-VM-02.01", "OSPS-VM-03.01"}
        if control_ids & security_controls:
            remediation_suggestions.append({
                "tool": "create_security_policy",
                "description": "Generate SECURITY.md with vulnerability reporting",
                "controls": sorted(control_ids & security_controls)
            })

        # General remediation for multiple issues
        if len(fail_results) > 2:
            remediation_suggestions.insert(0, {
                "tool": "remediate_audit_findings",
                "description": "Auto-fix multiple compliance issues at once",
                "controls": ["multiple"]
            })

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
            lines.append(f'remediate_audit_findings(local_path="/path/to/repo", dry_run=False)')
            lines.append("")
            lines.append("# Or fix specific categories")
            lines.append(f'enable_branch_protection(owner="{owner}", repo="{repo}")')
            lines.append("```")
            lines.append("")

        # Always show the git workflow section when there are failures
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
        lines.append(f'create_remediation_branch(branch_name="fix/openssf-baseline", local_path="/path/to/repo")')
        lines.append("")
        lines.append("# 2. Apply remediations (files will be created/modified)")
        lines.append(f'remediate_audit_findings(local_path="/path/to/repo")')
        lines.append("")
        lines.append("# 3. Commit the changes")
        lines.append(f'commit_remediation_changes(message="Add OpenSSF Baseline compliance files", local_path="/path/to/repo")')
        lines.append("")
        lines.append("# 4. Open a pull request")
        lines.append(f'create_remediation_pr(title="OpenSSF Baseline Compliance", local_path="/path/to/repo")')
        lines.append("```")
        lines.append("")
        lines.append("Use `get_remediation_status()` at any time to check current git state and next steps.")
        lines.append("")

        lines.append("> ⚠️ **Never run `gh api`, `git`, or other shell commands directly for remediation.**")
        lines.append("> Always use the MCP tools provided by this server to ensure proper error handling")
        lines.append("> and consistent implementation.")
        lines.append("")

    return "\n".join(lines)


def list_available_checks() -> Dict[str, List[Dict[str, Any]]]:
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
    "run_checks",
    "run_checks_legacy",
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
