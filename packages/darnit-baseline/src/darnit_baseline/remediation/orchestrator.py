"""Remediation orchestrator for OpenSSF Baseline compliance.

This module coordinates the application of multiple remediations
based on audit findings.
"""

import inspect
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from darnit.core.logging import get_logger
from darnit.core.models import AuditResult
from darnit.core.utils import (
    validate_local_path,
    detect_repo_from_git,
    get_git_commit,
    get_git_ref,
)
from darnit.config.loader import load_project_config
from darnit.tools import (
    prepare_audit,
    run_checks,
    summarize_results,
    calculate_compliance,
)

from .registry import REMEDIATION_REGISTRY, get_control_to_category_map
from .actions import create_security_policy, create_contributing_guide
from darnit.remediation.github import enable_branch_protection

logger = get_logger("remediation.orchestrator")


def _run_baseline_checks(
    owner: Optional[str],
    repo: Optional[str],
    local_path: str,
    level: int = 3,
    use_sieve: bool = True,
) -> Tuple[Optional[AuditResult], Optional[str]]:
    """Run baseline checks and return audit result or error.

    Args:
        owner: GitHub owner/organization
        repo: Repository name
        local_path: Path to local repository
        level: Maximum OSPS level to check (1, 2, or 3)
        use_sieve: Use progressive verification pipeline (default True)

    Returns:
        Tuple of (AuditResult, None) on success or (None, error_message) on failure
    """
    # Prepare audit
    owner, repo, resolved_path, default_branch, error = prepare_audit(owner, repo, local_path)
    if error:
        return None, error

    # Run checks
    all_results = run_checks(owner, repo, resolved_path, default_branch, level, use_sieve=use_sieve)

    # Calculate summary
    summary = summarize_results(all_results)
    compliance = calculate_compliance(all_results, level)

    # Get git info
    commit = get_git_commit(resolved_path)
    ref = get_git_ref(resolved_path)

    # Load project config if exists
    project_config = None
    try:
        project_config = load_project_config(resolved_path)
    except (IOError, OSError):
        pass

    # Create audit result
    result = AuditResult(
        owner=owner,
        repo=repo,
        local_path=resolved_path,
        level=level,
        default_branch=default_branch,
        all_results=all_results,
        summary=summary,
        level_compliance=compliance,
        timestamp=datetime.now().isoformat(),
        project_config=project_config,
        config_was_created=False,
        config_was_updated=False,
        config_changes=[],
        skipped_controls={},
        commit=commit,
        ref=ref,
    )

    return result, None


def _apply_remediation(
    category: str,
    local_path: str,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    dry_run: bool = True
) -> Dict[str, Any]:
    """Apply a single remediation category.

    Args:
        category: Remediation category name
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name
        dry_run: If True, only show what would be done

    Returns:
        Dict with category, status, and result details
    """
    if category not in REMEDIATION_REGISTRY:
        return {
            "category": category,
            "status": "error",
            "message": f"Unknown remediation category: {category}. Valid: {list(REMEDIATION_REGISTRY.keys())}"
        }

    info = REMEDIATION_REGISTRY[category]
    func_name = info["function"]

    # Map function names to actual functions
    func_map = {
        "enable_branch_protection": enable_branch_protection,
        "create_security_policy": create_security_policy,
        "create_contributing_guide": create_contributing_guide,
        # Add other remediation functions here as they're implemented
    }

    func = func_map.get(func_name)
    if not func:
        return {
            "category": category,
            "status": "error",
            "message": f"Remediation function '{func_name}' not yet implemented"
        }

    if dry_run:
        return {
            "category": category,
            "status": "would_apply",
            "description": info["description"],
            "controls": info["controls"],
            "function": func_name,
            "requires_api": info["requires_api"]
        }

    try:
        # Call the remediation function with appropriate parameters
        kwargs = {"local_path": local_path}
        sig = inspect.signature(func)

        if "owner" in sig.parameters:
            kwargs["owner"] = owner
        if "repo" in sig.parameters:
            kwargs["repo"] = repo
        if "dry_run" in sig.parameters:
            kwargs["dry_run"] = False

        result = func(**kwargs)

        logger.info(f"Applied remediation: {category}")
        return {
            "category": category,
            "status": "applied",
            "description": info["description"],
            "controls": info["controls"],
            "result": result[:500] if len(result) > 500 else result
        }
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, IOError, OSError) as e:
        logger.error(f"Remediation {category} failed: {e}")
        return {
            "category": category,
            "status": "error",
            "description": info["description"],
            "message": str(e)
        }


def _determine_remediations_for_failures(failures: List[Dict[str, Any]]) -> List[str]:
    """Determine which remediation categories apply to the given failures.

    Args:
        failures: List of failed check results

    Returns:
        Sorted list of applicable remediation category names
    """
    control_map = get_control_to_category_map()
    categories = set()

    for failure in failures:
        control_id = failure.get("id", "")
        if control_id in control_map:
            categories.add(control_map[control_id])

    return sorted(categories)


def remediate_audit_findings(
    local_path: str = ".",
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    categories: Optional[List[str]] = None,
    dry_run: bool = True
) -> str:
    """
    Apply automated remediations for failed audit controls.

    This function can fix common compliance gaps automatically. By default it runs in
    dry_run mode to show what would be changed without making modifications.

    Available remediation categories:
    - branch_protection: Enable branch protection (OSPS-AC-03.01, AC-03.02, QA-07.01)
    - status_checks: Configure required status checks (OSPS-QA-03.01)
    - security_policy: Create SECURITY.md (OSPS-VM-01.01, VM-02.01, VM-03.01)
    - codeowners: Create CODEOWNERS (OSPS-GV-01.01, GV-01.02, GV-04.01)
    - governance: Create GOVERNANCE.md (OSPS-GV-01.01, GV-01.02)
    - contributing: Create CONTRIBUTING.md (OSPS-GV-03.01, GV-03.02)
    - dco_enforcement: Configure DCO (OSPS-LE-01.01)
    - bug_report_template: Create bug report template (OSPS-DO-02.01)
    - dependabot: Configure Dependabot (OSPS-VM-05.*)
    - support_doc: Create SUPPORT.md (OSPS-DO-03.01)

    Args:
        local_path: Absolute path to repository
        owner: GitHub org/user (auto-detected if not provided)
        repo: Repository name (auto-detected if not provided)
        categories: List of remediation categories to apply, or ["all"] for all available
        dry_run: If True (default), show what would be changed without applying

    Returns:
        Markdown-formatted summary of applied or planned remediations
    """
    # Validate path
    resolved_path, path_error = validate_local_path(local_path)
    if path_error:
        return f"❌ Error: {path_error}"
    local_path = resolved_path

    # Auto-detect owner/repo
    detected = detect_repo_from_git(local_path)
    if not owner or not repo:
        if detected:
            owner = owner or detected.get("owner")
            repo = repo or detected.get("repo")

    # Determine categories to apply
    if not categories:
        # Run audit to find failures and determine applicable remediations
        audit_result, error = _run_baseline_checks(
            owner=owner, repo=repo, local_path=local_path, use_sieve=True
        )
        if error:
            return f"❌ Error running audit: {error}"

        failures = [r for r in audit_result.all_results if r.get("status") == "FAIL"]
        categories = _determine_remediations_for_failures(failures)

        if not categories:
            return "✅ No remediations needed - no failures with available auto-fixes."
    elif categories == ["all"]:
        categories = list(REMEDIATION_REGISTRY.keys())

    # Apply remediations
    results = []
    for category in categories:
        result = _apply_remediation(
            category=category,
            local_path=local_path,
            owner=owner,
            repo=repo,
            dry_run=dry_run
        )
        results.append(result)

    # Build output
    md = []
    mode = "Preview (dry run)" if dry_run else "Applied"
    md.append(f"# Remediation {mode}")
    md.append(f"**Repository:** {owner}/{repo}" if owner and repo else f"**Path:** {local_path}")
    md.append("")

    applied = [r for r in results if r.get("status") == "applied"]
    would_apply = [r for r in results if r.get("status") == "would_apply"]
    errors = [r for r in results if r.get("status") == "error"]

    if dry_run:
        md.append(f"## Would Apply ({len(would_apply)} remediations)")
        md.append("")
        for r in would_apply:
            controls_str = ", ".join(r.get("controls", []))
            api_note = " *(requires GitHub API)*" if r.get("requires_api") else ""
            md.append(f"### {r['category']}{api_note}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            md.append(f"- **Controls:** {controls_str}")
            md.append(f"- **Function:** `{r.get('function', 'N/A')}()`")
            md.append("")

        md.append("---")
        md.append("")
        md.append("**To apply these remediations:**")
        cats_str = ", ".join(f'"{c}"' for c in categories)
        md.append("```python")
        md.append("remediate_audit_findings(")
        md.append(f'    local_path="{local_path}",')
        md.append(f"    categories=[{cats_str}],")
        md.append("    dry_run=False")
        md.append(")")
        md.append("```")
    else:
        if applied:
            md.append(f"## ✅ Applied ({len(applied)} remediations)")
            md.append("")
            for r in applied:
                controls_str = ", ".join(r.get("controls", []))
                md.append(f"### {r['category']}")
                md.append(f"- **Description:** {r.get('description', 'N/A')}")
                md.append(f"- **Controls fixed:** {controls_str}")
                md.append("")

    if errors:
        md.append(f"## ❌ Errors ({len(errors)})")
        md.append("")
        for r in errors:
            md.append(f"- **{r['category']}**: {r.get('message', 'Unknown error')}")
        md.append("")

    return "\n".join(md)


__all__ = [
    "remediate_audit_findings",
    "_apply_remediation",
    "_determine_remediations_for_failures",
    "_run_baseline_checks",
]
