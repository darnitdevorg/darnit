"""Remediation orchestrator for OpenSSF Baseline compliance.

This module coordinates the application of remediations based on audit
findings using declarative TOML-based remediation definitions.
"""

from datetime import datetime
from typing import Any

from darnit.config.framework_schema import FrameworkConfig, TemplateConfig
from darnit.config.loader import load_project_config
from darnit.config.resolver import update_config_after_file_create
from darnit.core.logging import get_logger
from darnit.core.models import AuditResult
from darnit.core.utils import (
    get_git_commit,
    get_git_ref,
    validate_local_path,
)
from darnit.remediation.context_validator import (
    check_context_requirements,
    get_context_requirements_for_category,
)
from darnit.remediation.executor import RemediationExecutor
from darnit.sieve.project_context import is_control_applicable
from darnit.tools import (
    calculate_compliance,
    prepare_audit,
    run_checks,
    summarize_results,
)

from ..config.mappings import CONTROL_REFERENCE_MAPPING

logger = get_logger("remediation.orchestrator")


# =============================================================================
# Remediation Category Registry
# =============================================================================
# Maps category names to their associated controls and metadata.
# This is the category structure used for batch remediation dispatch.
# All actual remediation logic is defined in TOML (file_create, api_call, manual).
#
# TODO: Extract common remediation templates (SECURITY.md, CONTRIBUTING.md,
# CODEOWNERS, GOVERNANCE.md, etc.) into a shared `darnit-templates` core
# library that multiple darnit implementations can reuse, since there is
# significant overlap across compliance control catalogs.

REMEDIATION_CATEGORIES: dict[str, dict[str, Any]] = {
    "branch_protection": {
        "description": "Enable branch protection rules",
        "controls": ["OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-QA-07.01"],
        "safe": True,
        "requires_api": True,
    },
    "security_policy": {
        "description": "Create SECURITY.md with vulnerability reporting and VEX policy",
        "controls": ["OSPS-VM-01.01", "OSPS-VM-02.01", "OSPS-VM-03.01", "OSPS-VM-04.02"],
        "safe": True,
        "requires_api": False,
    },
    "codeowners": {
        "description": "Create CODEOWNERS file",
        "controls": ["OSPS-GV-04.01"],
        "safe": True,
        "requires_api": False,
    },
    "governance": {
        "description": "Create GOVERNANCE.md and MAINTAINERS.md",
        "controls": ["OSPS-GV-01.01", "OSPS-GV-01.02"],
        "safe": True,
        "requires_api": False,
    },
    "contributing": {
        "description": "Create CONTRIBUTING.md guide",
        "controls": ["OSPS-GV-03.01", "OSPS-GV-03.02"],
        "safe": True,
        "requires_api": False,
    },
    "dco_enforcement": {
        "description": "Configure DCO enforcement",
        "controls": ["OSPS-LE-01.01"],
        "safe": True,
        "requires_api": False,
    },
    "bug_report_template": {
        "description": "Create bug report issue template",
        "controls": ["OSPS-DO-02.01"],
        "safe": True,
        "requires_api": False,
    },
    "dependabot": {
        "description": "Configure Dependabot for dependency scanning",
        "controls": ["OSPS-VM-05.01", "OSPS-VM-05.02", "OSPS-VM-05.03"],
        "safe": True,
        "requires_api": False,
    },
    "support_doc": {
        "description": "Create SUPPORT.md",
        "controls": ["OSPS-DO-03.01"],
        "safe": True,
        "requires_api": False,
    },
}


# =============================================================================
# Framework Loading
# =============================================================================

_cached_framework: FrameworkConfig | None = None


def _get_framework_config() -> FrameworkConfig | None:
    """Load the OpenSSF Baseline framework config from TOML.

    Returns:
        FrameworkConfig if loaded successfully, None otherwise
    """
    global _cached_framework
    if _cached_framework is not None:
        return _cached_framework

    try:
        import tomllib

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

    except OSError as e:
        logger.debug(f"Failed to load framework TOML: {e}")
        return None
    except (ValueError, TypeError, KeyError) as e:
        logger.debug(f"Failed to parse framework TOML: {e}")
        return None


def _get_declarative_remediation(
    control_id: str,
) -> tuple[Any | None, dict[str, TemplateConfig] | None]:
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

    # Check if this has executable declarative remediation handlers
    # (manual-only handlers are guidance — handled separately by _get_manual_remediation)
    remediation = control.remediation
    if remediation.handlers:
        has_executable = any(
            h.handler != "manual" for h in remediation.handlers
        )
        if has_executable:
            return remediation, framework.templates

    return None, None


def _get_manual_remediation(
    control_ids: list[str],
    owner: str | None = None,
    repo: str | None = None,
) -> str | None:
    """Get manual remediation steps from TOML for the given controls.

    Returns formatted markdown with manual steps, or None if no manual
    remediation is defined. Substitutes ${owner} and ${repo} variables
    in steps and docs_url.
    """
    framework = _get_framework_config()
    if not framework:
        return None

    steps_by_control: list[tuple[str, list[str], str | None]] = []
    for control_id in control_ids:
        control = framework.controls.get(control_id)
        if not control or not control.remediation or not control.remediation.handlers:
            continue
        # Find manual handler invocations in the handlers list
        for handler in control.remediation.handlers:
            if handler.handler == "manual":
                extra = handler.model_extra or {}
                steps = extra.get("steps", [])
                docs_url = extra.get("docs_url")
                if steps:
                    steps_by_control.append((control_id, steps, docs_url))
                    break  # Only use first manual handler per control

    if not steps_by_control:
        return None

    # Build substitution map for template variables
    subs = {
        "${owner}": owner or "OWNER",
        "${repo}": repo or "REPO",
        "$OWNER": owner or "OWNER",
        "$REPO": repo or "REPO",
    }

    def _sub(text: str) -> str:
        for var, val in subs.items():
            text = text.replace(var, val)
        return text

    lines: list[str] = []
    lines.append("**Manual remediation required** — follow these steps:")
    lines.append("")
    for control_id, steps, docs_url in steps_by_control:
        lines.append(f"**{control_id}:**")
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {_sub(step)}")
        if docs_url:
            lines.append(f"\nSee: {_sub(docs_url)}")
        lines.append("")

    return "\n".join(lines)


def _run_baseline_checks(
    owner: str | None,
    repo: str | None,
    local_path: str,
    level: int = 3,
) -> tuple[AuditResult | None, str | None]:
    """Run baseline checks and return audit result or error.

    Args:
        owner: GitHub owner/organization
        repo: Repository name
        local_path: Path to local repository
        level: Maximum OSPS level to check (1, 2, or 3)

    Returns:
        Tuple of (AuditResult, None) on success or (None, error_message) on failure
    """
    # Prepare audit
    owner, repo, resolved_path, default_branch, error = prepare_audit(owner, repo, local_path)
    if error:
        return None, error

    # Run checks - returns (results_list, skipped_controls_dict)
    all_results, skipped_controls = run_checks(owner, repo, resolved_path, default_branch, level)

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
    except OSError:
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
        skipped_controls=skipped_controls,
        commit=commit,
        ref=ref,
    )

    return result, None


def _apply_remediation(
    category: str,
    local_path: str,
    owner: str | None = None,
    repo: str | None = None,
    dry_run: bool = True,
    non_passing_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Apply a single remediation category.

    This function first checks if controls are applicable (via .project.yaml),
    filters to only non-passing controls, then attempts to use declarative
    remediation from TOML.

    Args:
        category: Remediation category name
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name
        dry_run: If True, only show what would be done
        non_passing_ids: Set of control IDs that did not pass the audit.
            Only these controls will be considered for remediation.
            If None, all applicable controls are considered (legacy behavior).

    Returns:
        Dict with category, status, and result details
    """
    if category not in REMEDIATION_CATEGORIES:
        return {
            "category": category,
            "status": "error",
            "message": f"Unknown remediation category: {category}. Valid: {list(REMEDIATION_CATEGORIES.keys())}"
        }

    info = REMEDIATION_CATEGORIES[category]
    controls = info["controls"]

    # Get framework config for TOML-based requirements
    framework = _get_framework_config()

    # Pre-check: Validate context requirements before running remediation
    # Priority: TOML (via framework) > Python registry
    context_requirements = get_context_requirements_for_category(
        category=category,
        control_id=controls[0] if controls else None,  # Use first control for TOML lookup
        framework=framework,
        registry=REMEDIATION_CATEGORIES,
    )

    # Context validation must happen regardless of dry_run mode
    # Users need to see the prompt even in preview mode, otherwise they get
    # misleading output showing files would be created with guessed maintainers
    if context_requirements:
        check_result = check_context_requirements(
            requirements=context_requirements,
            local_path=local_path,
            framework=framework,
            owner=owner,  # Pass for sieve auto-detection
            repo=repo,    # Pass for sieve auto-detection
        )

        if not check_result.ready:
            # Context needs confirmation - return prompts
            logger.info(f"Remediation {category} needs context confirmation: {check_result.missing_context}")

            # Build the prompt output
            prompt_output = "\n\n".join(check_result.prompts)

            return {
                "category": category,
                "status": "needs_confirmation",
                "description": info["description"],
                "controls": controls,
                "missing_context": check_result.missing_context,
                "auto_detected": check_result.auto_detected,
                "result": prompt_output,
                "declarative": False,
            }

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
            "message": "All controls marked as N/A in .project.yaml",
        }

    # Filter to only non-passing controls (skip controls that already pass the audit)
    if non_passing_ids is not None:
        applicable_controls = [c for c in applicable_controls if c in non_passing_ids]
        if not applicable_controls:
            return {
                "category": category,
                "status": "already_passing",
                "description": info["description"],
                "controls": controls,
                "message": "All controls in this category already pass the audit",
            }

    # Try executable declarative remediation first (only for applicable controls)
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

    # Try manual-only declarative remediation before legacy fallthrough
    manual_result = _get_manual_remediation(applicable_controls, owner=owner, repo=repo)
    if manual_result:
        result = {
            "category": category,
            "status": "manual",
            "description": info["description"],
            "controls": info["controls"],
            "result": manual_result,
            "declarative": True,
        }
        if skipped_controls:
            result["skipped_controls"] = skipped_controls
        return result

    # No remediation available for this category
    result = {
        "category": category,
        "status": "no_remediation",
        "description": info["description"],
        "controls": info["controls"],
        "message": f"No TOML remediation defined for category '{category}'",
    }
    if skipped_controls:
        result["skipped_controls"] = skipped_controls
    return result


def _apply_declarative_remediation(
    category: str,
    control_id: str,
    remediation_config: Any,
    templates: dict[str, TemplateConfig] | None,
    local_path: str,
    owner: str | None,
    repo: str | None,
    dry_run: bool,
    info: dict[str, Any],
) -> dict[str, Any]:
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
        # Load confirmed context values for ${context.*} substitution
        context_values: dict[str, Any] = {}
        try:
            from darnit.config.context_storage import load_context
            all_context = load_context(local_path)
            for _category, values in all_context.items():
                for key, ctx_val in values.items():
                    context_values[key] = ctx_val.value
        except Exception:
            pass  # Context loading is best-effort

        # Create executor with templates and context
        executor = RemediationExecutor(
            local_path=local_path,
            owner=owner,
            repo=repo,
            templates=templates or {},
            context_values=context_values,
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
            # Find file_create handlers and get the created path
            for handler_inv in remediation_config.handlers:
                if handler_inv.handler == "file_create":
                    extra = handler_inv.model_extra or {}
                    created_path = extra.get("path")
                    if created_path:
                        config_updated = update_config_after_file_create(
                            local_path=local_path,
                            control_id=control_id,
                            created_file_path=created_path,
                            control_reference_mapping=CONTROL_REFERENCE_MAPPING,
                        )
                        if config_updated:
                            logger.info(f"Updated .project/ with reference: {created_path}")
                        break

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






def _preflight_context_check(
    categories: list[str],
    local_path: str,
    owner: str | None,
    repo: str | None,
) -> tuple[bool, dict[str, Any]]:
    """Pre-flight check for all context requirements across categories.

    Aggregates all missing context requirements before starting any remediation.
    This allows us to prompt the user once for all needed context, rather than
    discovering missing context one category at a time.

    Args:
        categories: List of remediation categories to check
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name

    Returns:
        Tuple of (ready, context_info) where:
        - ready: True if all context is available, False if prompts needed
        - context_info: Dict with missing_context, auto_detected, and prompts
    """
    framework = _get_framework_config()

    # Aggregate context requirements across all categories (deduplicate by key)
    all_requirements: dict[str, tuple[str, Any]] = {}  # key -> (category, requirement)

    for category in categories:
        if category not in REMEDIATION_CATEGORIES:
            continue

        info = REMEDIATION_CATEGORIES[category]
        controls = info["controls"]

        # Get context requirements for this category
        context_requirements = get_context_requirements_for_category(
            category=category,
            control_id=controls[0] if controls else None,
            framework=framework,
            registry=REMEDIATION_CATEGORIES,
        )

        for req in context_requirements:
            if req.key not in all_requirements:
                all_requirements[req.key] = (category, req)

    if not all_requirements:
        return True, {"missing_context": [], "auto_detected": {}, "prompts": []}

    # Check all requirements at once
    from darnit.remediation.context_validator import check_context_requirements

    requirements_list = [req for _, req in all_requirements.values()]
    check_result = check_context_requirements(
        requirements=requirements_list,
        local_path=local_path,
        framework=framework,
        owner=owner,
        repo=repo,
    )

    # Build category mapping for context keys
    key_to_categories: dict[str, list[str]] = {}
    for key, (category, _) in all_requirements.items():
        if key not in key_to_categories:
            key_to_categories[key] = []
        key_to_categories[key].append(category)

    return check_result.ready, {
        "missing_context": check_result.missing_context,
        "auto_detected": check_result.auto_detected,
        "prompts": check_result.prompts,
        "key_to_categories": key_to_categories,
    }


def _format_preflight_prompt(
    context_info: dict[str, Any],
    local_path: str,
) -> str:
    """Format the pre-flight context check results as a user-friendly prompt.

    Args:
        context_info: Dict with missing_context, auto_detected, prompts, key_to_categories
        local_path: Path to repository

    Returns:
        Markdown-formatted prompt for user
    """
    md = []
    md.append("# BLOCKED: Remediation Cannot Proceed")
    md.append("")
    md.append(
        "Remediation has **NOT** been applied and **WILL NOT** proceed "
        "until the following context is confirmed."
    )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## DO NOT directly edit `.project/` files!")
    md.append("")
    md.append("You **MUST** use the `confirm_project_context()` tool to set context values.")
    md.append("Direct file edits will be rejected and may cause inconsistent state.")
    md.append("")
    md.append("---")
    md.append("")

    # Show each prompt
    for prompt in context_info.get("prompts", []):
        md.append(prompt)
        md.append("")

    # Show which categories are affected
    key_to_cats = context_info.get("key_to_categories", {})
    if key_to_cats:
        md.append("---")
        md.append("")
        md.append("**Affected remediation categories:**")
        for key, cats in key_to_cats.items():
            if key in context_info.get("missing_context", []):
                md.append(f"- `{key}`: {', '.join(cats)}")
        md.append("")

    # Build a ready-to-use confirm_project_context() call from auto-detected values
    auto_detected = context_info.get("auto_detected", {})
    missing = context_info.get("missing_context", [])
    tool_args = []
    for key in missing:
        if key in auto_detected:
            value = auto_detected[key]
            if isinstance(value, str):
                tool_args.append(f'{key}="{value}"')
            elif isinstance(value, bool):
                tool_args.append(f"{key}={value}")
            elif isinstance(value, list):
                formatted = [f'"{v}"' for v in value]
                tool_args.append(f"{key}=[{', '.join(formatted)}]")
            else:
                tool_args.append(f"{key}={value!r}")

    md.append("---")
    md.append("")
    md.append("🛑 **AI Agents:** You MUST ask the user for the missing values above.")
    md.append("Do NOT guess or infer from repository owner, git history, or other sources.")
    md.append("")
    if tool_args:
        md.append("**After the user provides values, run this to confirm, then re-run remediation:**")
        md.append("```python")
        args_str = ",\n    ".join(tool_args)
        md.append(f'confirm_project_context(\n    local_path="{local_path}",\n    {args_str}\n)')
        md.append("```")
    else:
        md.append("**After the user provides values, confirm them, then re-run remediation:**")
        md.append("```python")
        md.append(f'confirm_project_context(local_path="{local_path}", ...)')
        md.append("```")

    return "\n".join(md)


def remediate_audit_findings(
    local_path: str = ".",
    owner: str | None = None,
    repo: str | None = None,
    categories: list[str] | None = None,
    dry_run: bool = True
) -> str:
    """
    Apply automated remediations for failed audit controls.

    This function can fix common compliance gaps automatically. By default it runs in
    dry_run mode to show what would be changed without making modifications.

    Available remediation categories:
    - branch_protection: Enable branch protection (OSPS-AC-03.01, AC-03.02, QA-07.01)
    - security_policy: Create SECURITY.md (OSPS-VM-01.01, VM-02.01, VM-03.01, VM-04.02)
    - codeowners: Create CODEOWNERS (OSPS-GV-04.01)
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

    # Auto-detect owner/repo (upstream-first by default)
    from darnit.core.utils import detect_owner_repo

    if not owner or not repo:
        detected_owner, detected_repo = detect_owner_repo(local_path)
        owner = owner or detected_owner
        repo = repo or detected_repo

    # Determine which controls failed the audit.
    # Only FAIL controls are remediated — WARN means "can't verify automatically"
    # and the existing content may be correct.  PASS is obviously skipped.
    # First, try the audit cache — avoids re-running the full audit when results
    # are fresh (e.g. the user just ran audit → remediate in sequence).
    failed_ids: set[str] | None = None
    error: str | None = None

    try:
        from darnit.core.audit_cache import read_audit_cache

        cache = read_audit_cache(local_path)
    except Exception:
        cache = None

    if cache is not None:
        # Cache hit — extract failed IDs without re-running the audit
        logger.info("Using cached audit results (skipping redundant audit)")
        failed_ids = {
            r.get("id", "") for r in cache["results"] if r.get("status") == "FAIL"
        }
    else:
        # Cache miss — fall back to running the audit
        logger.info("No cached audit results, running audit")
        audit_result, error = _run_baseline_checks(
            owner=owner, repo=repo, local_path=local_path
        )

        if not error and audit_result:
            failed_ids = {
                r.get("id", "") for r in audit_result.all_results if r.get("status") == "FAIL"
            }

    # Determine categories to apply
    if not categories or categories == ["all"]:
        if error:
            return f"❌ Error running audit: {error}"

        if not failed_ids:
            return "✅ No remediations needed - all controls with available auto-fixes are passing."

        categories = sorted(REMEDIATION_CATEGORIES.keys())
    elif error:
        # Audit failed but user specified explicit categories — proceed without
        # control-level filtering (failed_ids stays None = legacy behavior)
        logger.warning(f"Audit failed ({error}), proceeding without control-level filtering")

    # Pre-flight check: Verify all context requirements BEFORE starting remediation
    # This ensures we prompt for all missing context upfront, not one-by-one
    context_ready, context_info = _preflight_context_check(
        categories=categories,
        local_path=local_path,
        owner=owner,
        repo=repo,
    )

    if not context_ready:
        # Return consolidated prompt for all missing context
        return _format_preflight_prompt(context_info, local_path)

    # All context is ready - apply remediations
    results = []
    for category in categories:
        result = _apply_remediation(
            category=category,
            local_path=local_path,
            owner=owner,
            repo=repo,
            dry_run=dry_run,
            non_passing_ids=failed_ids,
        )
        results.append(result)

    # Invalidate cache after applying changes (not dry-run)
    if not dry_run:
        applied_any = any(r.get("status") == "applied" for r in results)
        if applied_any:
            try:
                from darnit.core.audit_cache import invalidate_audit_cache

                invalidate_audit_cache(local_path)
            except Exception as exc:
                logger.warning(f"Failed to invalidate audit cache: {exc}")

    # Build output
    md = []
    mode = "Preview (dry run)" if dry_run else "Applied"
    md.append(f"# Remediation {mode}")
    md.append(f"**Repository:** {owner}/{repo}" if owner and repo else f"**Path:** {local_path}")
    md.append("")

    applied = [r for r in results if r.get("status") == "applied"]
    would_apply = [r for r in results if r.get("status") == "would_apply"]
    needs_confirmation = [r for r in results if r.get("status") == "needs_confirmation"]
    manual = [r for r in results if r.get("status") == "manual"]
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

    # Show categories that need user confirmation before proceeding
    if needs_confirmation:
        md.append(f"## ⚠️ Needs Confirmation ({len(needs_confirmation)} remediations)")
        md.append("")
        md.append("The following remediations need your confirmation before they can be applied:")
        md.append("")
        for r in needs_confirmation:
            controls_str = ", ".join(r.get("controls", []))
            md.append(f"### {r['category']}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            md.append(f"- **Controls:** {controls_str}")
            md.append("")
            # Show the full confirmation prompt
            if r.get("result"):
                md.append(r["result"])
            md.append("")
        md.append("---")
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

    if manual:
        md.append(f"## 📋 Manual Steps Required ({len(manual)})")
        md.append("")
        for r in manual:
            controls_str = ", ".join(r.get("controls", []))
            md.append(f"### {r['category']}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            md.append(f"- **Controls:** {controls_str}")
            md.append("")
            if r.get("result"):
                md.append(r["result"])
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
    "_run_baseline_checks",
]
