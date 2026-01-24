"""Remediation orchestrator for OpenSSF Baseline compliance.

This module coordinates the application of multiple remediations
based on audit findings. It supports both declarative TOML-based
remediations and legacy Python function remediations.
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
from darnit.config.framework_schema import FrameworkConfig, TemplateConfig
from darnit.remediation.executor import RemediationExecutor
from darnit.tools import (
    prepare_audit,
    run_checks,
    summarize_results,
    calculate_compliance,
)

from darnit.sieve.project_context import is_control_applicable
from darnit.config.resolver import update_config_after_file_create

from .registry import REMEDIATION_REGISTRY, get_control_to_category_map
from ..config.mappings import CONTROL_REFERENCE_MAPPING
from .actions import (
    create_security_policy,
    create_contributing_guide,
    create_codeowners,
    create_governance_doc,
    create_dependabot_config,
    create_support_doc,
    create_bug_report_template,
    configure_dco_enforcement,
)
from darnit.remediation.github import enable_branch_protection

logger = get_logger("remediation.orchestrator")


# =============================================================================
# Framework Loading
# =============================================================================

_cached_framework: Optional[FrameworkConfig] = None


def _get_framework_config() -> Optional[FrameworkConfig]:
    """Load the OpenSSF Baseline framework config from TOML.

    Returns:
        FrameworkConfig if loaded successfully, None otherwise
    """
    global _cached_framework
    if _cached_framework is not None:
        return _cached_framework

    try:
        import sys
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib

        # Use the package's get_framework_path() function
        from darnit_baseline import get_framework_path
        toml_path = get_framework_path()

        if not toml_path.exists():
            logger.debug(f"Framework TOML not found at {toml_path}")
            return None

        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        _cached_framework = FrameworkConfig(**data)
        logger.debug(f"Loaded framework config from {toml_path}")
        return _cached_framework

    except (OSError, IOError) as e:
        logger.debug(f"Failed to load framework TOML: {e}")
        return None
    except (ValueError, TypeError, KeyError) as e:
        logger.debug(f"Failed to parse framework TOML: {e}")
        return None


def _get_declarative_remediation(
    control_id: str,
) -> Tuple[Optional[Any], Optional[Dict[str, TemplateConfig]]]:
    """Get declarative remediation config for a control.

    Args:
        control_id: The control ID (e.g., "OSPS-VM-02.01")

    Returns:
        Tuple of (RemediationConfig, templates_dict) or (None, None)
    """
    framework = _get_framework_config()
    if not framework:
        return None, None

    control = framework.controls.get(control_id)
    if not control or not control.remediation:
        return None, None

    # Check if this has a declarative remediation type
    remediation = control.remediation
    if remediation.file_create or remediation.exec or remediation.api_call:
        return remediation, framework.templates

    return None, None


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

    This function first checks if controls are applicable (via .project.yaml),
    then attempts to use declarative remediation from TOML,
    and finally falls back to legacy Python functions.

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
    controls = info["controls"]

    # Check if any of the controls are applicable (respects .project.yaml overrides)
    skipped_controls = []
    applicable_controls = []
    for control_id in controls:
        applicable, reason = is_control_applicable(local_path, control_id)
        if applicable:
            applicable_controls.append(control_id)
        else:
            skipped_controls.append({"id": control_id, "reason": reason})
            logger.debug(f"Control {control_id} skipped: {reason}")

    # If all controls are skipped, return early
    if not applicable_controls and skipped_controls:
        return {
            "category": category,
            "status": "skipped",
            "description": info["description"],
            "controls": controls,
            "skipped_controls": skipped_controls,
            "message": f"All controls marked as N/A in .project.yaml",
        }

    # Try declarative remediation first (only for applicable controls)
    for control_id in applicable_controls:
        remediation_config, templates = _get_declarative_remediation(control_id)
        if remediation_config:
            result = _apply_declarative_remediation(
                category=category,
                control_id=control_id,
                remediation_config=remediation_config,
                templates=templates,
                local_path=local_path,
                owner=owner,
                repo=repo,
                dry_run=dry_run,
                info=info,
            )
            # Add skipped controls info if any
            if skipped_controls:
                result["skipped_controls"] = skipped_controls
            return result

    # Fall back to legacy Python functions
    result = _apply_legacy_remediation(
        category=category,
        local_path=local_path,
        owner=owner,
        repo=repo,
        dry_run=dry_run,
        info=info,
    )
    # Add skipped controls info if any
    if skipped_controls:
        result["skipped_controls"] = skipped_controls
    return result


def _apply_declarative_remediation(
    category: str,
    control_id: str,
    remediation_config: Any,
    templates: Optional[Dict[str, TemplateConfig]],
    local_path: str,
    owner: Optional[str],
    repo: Optional[str],
    dry_run: bool,
    info: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply a declarative remediation from TOML config.

    Args:
        category: Remediation category name
        control_id: The control ID being remediated
        remediation_config: RemediationConfig from TOML
        templates: Template definitions from framework
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name
        dry_run: If True, only show what would be done
        info: Category info from registry

    Returns:
        Dict with category, status, and result details
    """
    try:
        # Create executor with templates
        executor = RemediationExecutor(
            local_path=local_path,
            owner=owner,
            repo=repo,
            templates=templates or {},
        )

        # Execute the remediation
        result = executor.execute(
            control_id=control_id,
            config=remediation_config,
            dry_run=dry_run,
        )

        if dry_run:
            return {
                "category": category,
                "status": "would_apply",
                "description": info["description"],
                "controls": info["controls"],
                "remediation_type": result.remediation_type,
                "details": result.details,
                "requires_api": info.get("requires_api", False),
                "declarative": True,
            }

        if result.success:
            logger.info(f"Applied declarative remediation: {category} ({result.remediation_type})")

            # Update .project/ config with reference to created file
            config_updated = False
            if result.remediation_type == "file_create":
                created_path = result.details.get("path")
                if created_path:
                    config_updated = update_config_after_file_create(
                        local_path=local_path,
                        control_id=control_id,
                        created_file_path=created_path,
                        control_reference_mapping=CONTROL_REFERENCE_MAPPING,
                    )
                    if config_updated:
                        logger.info(f"Updated .project/ with reference: {created_path}")

            return {
                "category": category,
                "status": "applied",
                "description": info["description"],
                "controls": info["controls"],
                "remediation_type": result.remediation_type,
                "result": result.message,
                "declarative": True,
                "config_updated": config_updated,
            }
        else:
            logger.error(f"Declarative remediation failed: {result.message}")
            return {
                "category": category,
                "status": "error",
                "description": info["description"],
                "message": result.message,
                "declarative": True,
            }

    except (RuntimeError, ValueError, TypeError, KeyError) as e:
        logger.error(f"Declarative remediation {category} failed: {e}")
        return {
            "category": category,
            "status": "error",
            "description": info["description"],
            "message": f"Declarative remediation error: {str(e)}",
            "declarative": True,
        }


# Mapping from category to file path and primary control ID for config updates
CATEGORY_FILE_MAPPING: Dict[str, Dict[str, str]] = {
    "security_policy": {
        "file": "SECURITY.md",
        "control_id": "OSPS-VM-01.01",  # Primary control for security.policy
    },
    "contributing": {
        "file": "CONTRIBUTING.md",
        "control_id": "OSPS-GV-03.01",  # Maps to governance.contributing
    },
    "codeowners": {
        "file": "CODEOWNERS",
        "control_id": "OSPS-GV-04.01",  # Maps to governance.codeowners
    },
    "governance": {
        "file": "GOVERNANCE.md",
        "control_id": "OSPS-GV-01.01",  # Maps to governance.maintainers
    },
    "support_doc": {
        "file": "SUPPORT.md",
        "control_id": "OSPS-DO-03.01",  # Maps to documentation.support
    },
    "bug_report_template": {
        "file": ".github/ISSUE_TEMPLATE/bug_report.md",
        "control_id": "OSPS-DO-02.01",  # Maps to security.policy (issue template)
    },
    "dependabot": {
        "file": ".github/dependabot.yml",
        "control_id": "OSPS-VM-05.01",  # Maps to security.dependency_scanning
    },
    "dco_enforcement": {
        "file": "CONTRIBUTING.md",  # DCO info added to CONTRIBUTING.md
        "control_id": "OSPS-LE-01.01",  # Maps to legal.dco
    },
}


def _apply_legacy_remediation(
    category: str,
    local_path: str,
    owner: Optional[str],
    repo: Optional[str],
    dry_run: bool,
    info: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply a legacy Python function remediation.

    Args:
        category: Remediation category name
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name
        dry_run: If True, only show what would be done
        info: Category info from registry

    Returns:
        Dict with category, status, and result details
    """
    func_name = info["function"]

    # Map function names to actual functions
    func_map = {
        "enable_branch_protection": enable_branch_protection,
        "create_security_policy": create_security_policy,
        "create_contributing_guide": create_contributing_guide,
        "create_codeowners": create_codeowners,
        "create_governance_doc": create_governance_doc,
        "create_dependabot_config": create_dependabot_config,
        "create_support_doc": create_support_doc,
        "create_bug_report_template": create_bug_report_template,
        "configure_dco_enforcement": configure_dco_enforcement,
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
            "requires_api": info["requires_api"],
            "declarative": False,
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

        logger.info(f"Applied legacy remediation: {category}")

        # Update .project/ config with reference to created file (for file-creating categories)
        config_updated = False
        file_mapping = CATEGORY_FILE_MAPPING.get(category)
        if file_mapping:
            created_path = file_mapping["file"]
            control_id = file_mapping["control_id"]
            config_updated = update_config_after_file_create(
                local_path=local_path,
                control_id=control_id,
                created_file_path=created_path,
                control_reference_mapping=CONTROL_REFERENCE_MAPPING,
            )
            if config_updated:
                logger.info(f"Updated .project/ with reference: {created_path}")

        return {
            "category": category,
            "status": "applied",
            "description": info["description"],
            "controls": info["controls"],
            "result": result[:500] if len(result) > 500 else result,
            "declarative": False,
            "config_updated": config_updated,
        }
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, IOError, OSError) as e:
        logger.error(f"Remediation {category} failed: {e}")
        return {
            "category": category,
            "status": "error",
            "description": info["description"],
            "message": str(e),
            "declarative": False,
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
    skipped = [r for r in results if r.get("status") == "skipped"]
    errors = [r for r in results if r.get("status") == "error"]

    if dry_run:
        md.append(f"## Would Apply ({len(would_apply)} remediations)")
        md.append("")
        for r in would_apply:
            controls_str = ", ".join(r.get("controls", []))
            api_note = " *(requires GitHub API)*" if r.get("requires_api") else ""
            declarative_note = " *(declarative)*" if r.get("declarative") else ""
            md.append(f"### {r['category']}{api_note}{declarative_note}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            md.append(f"- **Controls:** {controls_str}")
            if r.get("remediation_type"):
                md.append(f"- **Type:** {r.get('remediation_type')}")
            elif r.get("function"):
                md.append(f"- **Function:** `{r.get('function', 'N/A')}()`")
            # Show skipped controls if any
            if r.get("skipped_controls"):
                skipped_info = ", ".join(
                    f"{s['id']} ({s['reason']})" for s in r["skipped_controls"]
                )
                md.append(f"- **Skipped (N/A):** {skipped_info}")
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
                declarative_note = " *(declarative)*" if r.get("declarative") else ""
                md.append(f"### {r['category']}{declarative_note}")
                md.append(f"- **Description:** {r.get('description', 'N/A')}")
                md.append(f"- **Controls fixed:** {controls_str}")
                # Show skipped controls if any
                if r.get("skipped_controls"):
                    skipped_info = ", ".join(
                        f"{s['id']} ({s['reason']})" for s in r["skipped_controls"]
                    )
                    md.append(f"- **Skipped (N/A):** {skipped_info}")
                md.append("")

    # Show categories skipped due to .project.yaml overrides
    if skipped:
        md.append(f"## ⏭️ Skipped ({len(skipped)} categories)")
        md.append("")
        md.append("The following categories were skipped because all their controls")
        md.append("are marked as N/A in `.project.yaml`:")
        md.append("")
        for r in skipped:
            controls_str = ", ".join(r.get("controls", []))
            md.append(f"### {r['category']}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            md.append(f"- **Controls:** {controls_str}")
            if r.get("skipped_controls"):
                for s in r["skipped_controls"]:
                    md.append(f"  - `{s['id']}`: {s['reason']}")
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
