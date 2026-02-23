"""Remediation orchestrator for OpenSSF Baseline compliance.

This module coordinates the application of remediations based on audit
findings using declarative TOML-based remediation definitions.

All remediation metadata (safe, requires_api, description, context
requirements) comes from the TOML FrameworkConfig.  The orchestrator
iterates *controls*, not hardcoded categories.
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
# Category ↔ Control Mapping (domain-based)
# =============================================================================
# Domain-based categories derived from control ID prefix.
DOMAIN_PREFIXES: dict[str, str] = {
    "access_control": "OSPS-AC",
    "build_release": "OSPS-BR",
    "documentation": "OSPS-DO",
    "governance": "OSPS-GV",
    "legal": "OSPS-LE",
    "quality": "OSPS-QA",
    "security_architecture": "OSPS-SA",
    "vulnerability_management": "OSPS-VM",
}

# Human-readable domain labels for grouped output.
_DOMAIN_LABELS: dict[str, str] = {
    "AC": "Access Control",
    "BR": "Build & Release",
    "DO": "Documentation",
    "GV": "Governance",
    "LE": "Legal",
    "QA": "Quality Assurance",
    "SA": "Security Architecture",
    "VM": "Vulnerability Management",
}


def _get_domain(control_id: str) -> str:
    """Extract the 2-letter domain code from a control ID.

    Example: "OSPS-VM-01.01" → "VM"
    """
    parts = control_id.split("-")
    return parts[1] if len(parts) >= 2 else "??"


def _resolve_categories_to_control_ids(
    categories: list[str],
    framework: FrameworkConfig | None,
) -> set[str]:
    """Resolve domain-based category names to a set of control IDs.

    Categories must be domain names (e.g., "vulnerability_management",
    "governance").  See DOMAIN_PREFIXES for valid names.
    """
    ids: set[str] = set()
    all_control_ids = set(framework.controls.keys()) if framework else set()

    for cat in categories:
        if cat in DOMAIN_PREFIXES:
            prefix = DOMAIN_PREFIXES[cat]
            ids.update(cid for cid in all_control_ids if cid.startswith(prefix))
        else:
            logger.warning(
                f"Unknown category '{cat}' — ignored. "
                f"Valid: {sorted(DOMAIN_PREFIXES.keys())}"
            )

    return ids


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


# =============================================================================
# Per-Control Remediation
# =============================================================================


def _apply_control_remediation(
    control_id: str,
    local_path: str,
    owner: str | None = None,
    repo: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply remediation for a single control, driven entirely by TOML.

    Args:
        control_id: The control ID (e.g., "OSPS-GV-01.01")
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name
        dry_run: If True, only show what would be done

    Returns:
        Dict with control_id, status, and result details
    """
    framework = _get_framework_config()
    if not framework:
        return {
            "control_id": control_id,
            "status": "error",
            "message": "Could not load framework config from TOML",
        }

    control = framework.controls.get(control_id)
    if not control:
        return {
            "control_id": control_id,
            "status": "error",
            "message": f"Control {control_id} not found in TOML",
        }

    description = control.description or control_id
    remediation = control.remediation

    if not remediation or not remediation.handlers:
        return {
            "control_id": control_id,
            "status": "no_remediation",
            "description": description,
            "message": f"No remediation handlers defined for {control_id}",
        }

    # --- Context validation (regardless of dry_run) ---
    if remediation.requires_context:
        check_result = check_context_requirements(
            requirements=remediation.requires_context,
            local_path=local_path,
            framework=framework,
            owner=owner,
            repo=repo,
        )

        if not check_result.ready:
            logger.info(f"Remediation {control_id} needs context: {check_result.missing_context}")
            prompt_output = "\n\n".join(check_result.prompts)

            return {
                "control_id": control_id,
                "status": "needs_confirmation",
                "description": description,
                "controls": [control_id],
                "missing_context": check_result.missing_context,
                "auto_detected": check_result.auto_detected,
                "result": prompt_output,
                "declarative": False,
            }

    # --- Applicability check (.project.yaml overrides) ---
    applicable, reason = is_control_applicable(local_path, control_id)
    if not applicable:
        return {
            "control_id": control_id,
            "status": "skipped",
            "description": description,
            "message": reason,
        }

    # --- Try executable declarative remediation ---
    remediation_config, templates = _get_declarative_remediation(control_id)
    if remediation_config:
        result = _apply_declarative_remediation(
            control_id=control_id,
            remediation_config=remediation_config,
            templates=templates,
            local_path=local_path,
            owner=owner,
            repo=repo,
            dry_run=dry_run,
            description=description,
            requires_api=remediation_config.requires_api,
        )
        # Tag unsafe remediations for review
        if not remediation_config.safe:
            result["needs_review"] = True
        return result

    # --- Try manual-only remediation ---
    manual_result = _get_manual_remediation([control_id], owner=owner, repo=repo)
    if manual_result:
        return {
            "control_id": control_id,
            "status": "manual",
            "description": description,
            "controls": [control_id],
            "result": manual_result,
            "declarative": True,
        }

    return {
        "control_id": control_id,
        "status": "no_remediation",
        "description": description,
        "message": f"No executable remediation for {control_id}",
    }


def _apply_declarative_remediation(
    control_id: str,
    remediation_config: Any,
    templates: dict[str, TemplateConfig] | None,
    local_path: str,
    owner: str | None,
    repo: str | None,
    dry_run: bool,
    description: str = "",
    requires_api: bool = False,
) -> dict[str, Any]:
    """Apply a declarative remediation from TOML config.

    Args:
        control_id: The control ID being remediated
        remediation_config: RemediationConfig from TOML
        templates: Template definitions from framework
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name
        dry_run: If True, only show what would be done
        description: Human-readable control description
        requires_api: Whether this remediation needs API access

    Returns:
        Dict with control_id, status, and result details
    """
    try:
        # Start with auto-detected context (platform, ci_provider,
        # detected_ecosystem, license_type) so that ``when`` clauses on
        # remediation handlers can match without explicit user confirmation.
        context_values: dict[str, Any] = {}
        try:
            from darnit.context.auto_detect import collect_auto_context
            context_values = collect_auto_context(local_path)
        except Exception:
            pass  # Auto-detection is best-effort

        # Confirmed context overrides auto-detected values
        try:
            from darnit.config.context_storage import load_context
            all_context = load_context(local_path)
            for _category, values in all_context.items():
                for key, ctx_val in values.items():
                    context_values[key] = ctx_val.value
        except Exception:
            pass  # Context loading is best-effort

        # Resolve framework TOML path for template file resolution
        fw_path: str | None = None
        try:
            from darnit_baseline import get_framework_path
            p = get_framework_path()
            if p:
                fw_path = str(p)
        except Exception:
            pass

        # Create executor with templates and context
        executor = RemediationExecutor(
            local_path=local_path,
            owner=owner,
            repo=repo,
            templates=templates or {},
            context_values=context_values,
            framework_path=fw_path,
        )

        # Execute the remediation
        result = executor.execute(
            control_id=control_id,
            config=remediation_config,
            dry_run=dry_run,
        )

        if dry_run:
            return {
                "control_id": control_id,
                "status": "would_apply",
                "description": description,
                "controls": [control_id],
                "remediation_type": result.remediation_type,
                "details": result.details,
                "requires_api": requires_api,
                "declarative": True,
            }

        if result.success:
            logger.info(f"Applied declarative remediation: {control_id} ({result.remediation_type})")

            # Update .project/ config with reference to created file
            config_updated = False
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

            # Apply project_update if defined
            if remediation_config.project_update:
                _apply_project_update(local_path, remediation_config.project_update, control_id)

            return {
                "control_id": control_id,
                "status": "applied",
                "description": description,
                "controls": [control_id],
                "remediation_type": result.remediation_type,
                "result": result.message,
                "declarative": True,
                "config_updated": config_updated,
            }
        else:
            logger.error(f"Declarative remediation failed: {result.message}")
            return {
                "control_id": control_id,
                "status": "error",
                "description": description,
                "message": result.message,
                "declarative": True,
            }

    except (RuntimeError, ValueError, TypeError, KeyError) as e:
        logger.error(f"Declarative remediation {control_id} failed: {e}")
        return {
            "control_id": control_id,
            "status": "error",
            "description": description,
            "message": f"Declarative remediation error: {str(e)}",
            "declarative": True,
        }


def _apply_project_update(
    local_path: str,
    project_update: Any,
    control_id: str,
) -> None:
    """Apply project_update after successful remediation."""
    from darnit.remediation.executor import apply_project_update

    try:
        apply_project_update(local_path, project_update, control_id)
    except Exception as e:
        logger.warning(f"Failed to apply project_update for {control_id}: {e}")


# =============================================================================
# Pre-flight Context Check
# =============================================================================


def _preflight_context_check(
    control_ids: list[str],
    local_path: str,
    owner: str | None,
    repo: str | None,
) -> tuple[bool, dict[str, Any]]:
    """Pre-flight check for all context requirements across controls.

    Aggregates all missing context requirements before starting any remediation.
    This allows us to prompt the user once for all needed context, rather than
    discovering missing context one control at a time.

    Args:
        control_ids: List of control IDs to check
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name

    Returns:
        Tuple of (ready, context_info) where:
        - ready: True if all context is available, False if prompts needed
        - context_info: Dict with missing_context, auto_detected, and prompts
    """
    framework = _get_framework_config()

    # Aggregate context requirements across all controls (deduplicate by key)
    all_requirements: dict[str, tuple[str, Any]] = {}  # key -> (control_id, requirement)

    for control_id in control_ids:
        if not framework:
            continue

        control = framework.controls.get(control_id)
        if not control or not control.remediation or not control.remediation.requires_context:
            continue

        for req in control.remediation.requires_context:
            if req.key not in all_requirements:
                all_requirements[req.key] = (control_id, req)

    if not all_requirements:
        return True, {"missing_context": [], "auto_detected": {}, "prompts": []}

    # Check all requirements at once
    requirements_list = [req for _, req in all_requirements.values()]
    check_result = check_context_requirements(
        requirements=requirements_list,
        local_path=local_path,
        framework=framework,
        owner=owner,
        repo=repo,
    )

    # Build control mapping for context keys
    key_to_controls: dict[str, list[str]] = {}
    for key, (control_id, _) in all_requirements.items():
        if key not in key_to_controls:
            key_to_controls[key] = []
        key_to_controls[key].append(control_id)

    return check_result.ready, {
        "missing_context": check_result.missing_context,
        "auto_detected": check_result.auto_detected,
        "prompts": check_result.prompts,
        "key_to_controls": key_to_controls,
    }


def _format_preflight_prompt(
    context_info: dict[str, Any],
    local_path: str,
) -> str:
    """Format the pre-flight context check results as a user-friendly prompt.

    Args:
        context_info: Dict with missing_context, auto_detected, prompts, key_to_controls
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

    # Show which controls are affected
    key_to_controls = context_info.get("key_to_controls", {})
    if key_to_controls:
        md.append("---")
        md.append("")
        md.append("**Affected controls:**")
        for key, controls in key_to_controls.items():
            if key in context_info.get("missing_context", []):
                md.append(f"- `{key}`: {', '.join(controls)}")
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


# =============================================================================
# Main Entry Point
# =============================================================================


def remediate_audit_findings(
    local_path: str = ".",
    owner: str | None = None,
    repo: str | None = None,
    categories: list[str] | None = None,
    dry_run: bool = True
) -> str:
    """Apply automated remediations for failed audit controls.

    Iterates all failed controls that have TOML-defined remediation and
    applies them.  The optional ``categories`` parameter filters to a
    subset (supports both domain-based and legacy category names).

    Args:
        local_path: Absolute path to repository
        owner: GitHub org/user (auto-detected if not provided)
        repo: Repository name (auto-detected if not provided)
        categories: Optional filter — list of category names, or ["all"]
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

    # Load framework config (needed for control discovery)
    framework = _get_framework_config()
    if not framework:
        return "❌ Error: Could not load framework TOML config"

    # ------------------------------------------------------------------
    # Determine which controls failed the audit.
    # Only FAIL controls are remediated — WARN means "can't verify
    # automatically" and existing content may be correct.
    # ------------------------------------------------------------------
    failed_ids: set[str] | None = None
    error: str | None = None

    try:
        from darnit.core.audit_cache import read_audit_cache
        cache = read_audit_cache(local_path)
    except Exception:
        cache = None

    if cache is not None:
        logger.info("Using cached audit results (skipping redundant audit)")
        failed_ids = {
            r.get("id", "") for r in cache["results"] if r.get("status") == "FAIL"
        }
    else:
        logger.info("No cached audit results, running audit")
        audit_result, error = _run_baseline_checks(
            owner=owner, repo=repo, local_path=local_path
        )
        if not error and audit_result:
            failed_ids = {
                r.get("id", "") for r in audit_result.all_results if r.get("status") == "FAIL"
            }

    # ------------------------------------------------------------------
    # Build the list of controls to remediate
    # ------------------------------------------------------------------
    if not categories or categories == ["all"]:
        if error:
            return f"❌ Error running audit: {error}"
        if not failed_ids:
            return "✅ No remediations needed - all controls with available auto-fixes are passing."

        # All failed controls that have ANY remediation in TOML
        remediable_ids = []
        for cid in sorted(failed_ids):
            control = framework.controls.get(cid)
            if control and control.remediation and control.remediation.handlers:
                remediable_ids.append(cid)
    else:
        # Category filter — resolve to control IDs, intersect with failures
        allowed_ids = _resolve_categories_to_control_ids(categories, framework)

        if error:
            # Audit failed but user specified explicit categories — proceed
            # without control-level filtering
            logger.warning(f"Audit failed ({error}), proceeding without control-level filtering")
            remediable_ids = sorted(
                cid for cid in allowed_ids
                if framework.controls.get(cid)
                and framework.controls[cid].remediation
                and framework.controls[cid].remediation.handlers
            )
        elif failed_ids is not None:
            remediable_ids = sorted(
                cid for cid in allowed_ids
                if cid in failed_ids
                and framework.controls.get(cid)
                and framework.controls[cid].remediation
                and framework.controls[cid].remediation.handlers
            )
        else:
            remediable_ids = sorted(
                cid for cid in allowed_ids
                if framework.controls.get(cid)
                and framework.controls[cid].remediation
                and framework.controls[cid].remediation.handlers
            )

    if not remediable_ids:
        return "✅ No remediations needed - all controls with available auto-fixes are passing."

    # ------------------------------------------------------------------
    # Pre-flight context check (prompt for ALL missing context upfront)
    # ------------------------------------------------------------------
    context_ready, context_info = _preflight_context_check(
        control_ids=remediable_ids,
        local_path=local_path,
        owner=owner,
        repo=repo,
    )

    if not context_ready:
        return _format_preflight_prompt(context_info, local_path)

    # ------------------------------------------------------------------
    # Apply remediations
    # ------------------------------------------------------------------
    results = []
    for control_id in remediable_ids:
        result = _apply_control_remediation(
            control_id=control_id,
            local_path=local_path,
            owner=owner,
            repo=repo,
            dry_run=dry_run,
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

    # ------------------------------------------------------------------
    # Format output
    # ------------------------------------------------------------------
    return _format_remediation_output(
        results=results,
        local_path=local_path,
        owner=owner,
        repo=repo,
        dry_run=dry_run,
        categories=categories,
    )


def _format_remediation_output(
    results: list[dict[str, Any]],
    local_path: str,
    owner: str | None,
    repo: str | None,
    dry_run: bool,
    categories: list[str] | None = None,
) -> str:
    """Build the markdown output for the remediation report."""
    md: list[str] = []
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
            cid = r.get("control_id", r.get("category", "?"))
            api_note = " *(requires GitHub API)*" if r.get("requires_api") else ""
            review_note = " **⚠️ REVIEW REQUIRED**" if r.get("needs_review") else ""
            declarative_note = " *(declarative)*" if r.get("declarative") else ""
            md.append(f"### {cid}{api_note}{declarative_note}{review_note}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            if r.get("remediation_type"):
                md.append(f"- **Type:** {r.get('remediation_type')}")
            md.append("")

        md.append("---")
        md.append("")
        md.append("**To apply these remediations:**")
        md.append("```python")
        md.append("remediate_audit_findings(")
        md.append(f'    local_path="{local_path}",')
        if categories and categories != ["all"]:
            cats_str = ", ".join(f'"{c}"' for c in categories)
            md.append(f"    categories=[{cats_str}],")
        md.append("    dry_run=False")
        md.append(")")
        md.append("```")
    else:
        if applied:
            md.append(f"## ✅ Applied ({len(applied)} remediations)")
            md.append("")
            for r in applied:
                cid = r.get("control_id", r.get("category", "?"))
                review_note = " **⚠️ REVIEW REQUIRED**" if r.get("needs_review") else ""
                declarative_note = " *(declarative)*" if r.get("declarative") else ""
                md.append(f"### {cid}{declarative_note}{review_note}")
                md.append(f"- **Description:** {r.get('description', 'N/A')}")
                md.append("")

    # Context confirmation needed
    if needs_confirmation:
        md.append(f"## ⚠️ Needs Confirmation ({len(needs_confirmation)} remediations)")
        md.append("")
        md.append("The following remediations need your confirmation before they can be applied:")
        md.append("")
        for r in needs_confirmation:
            cid = r.get("control_id", r.get("category", "?"))
            md.append(f"### {cid}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            md.append("")
            if r.get("result"):
                md.append(r["result"])
            md.append("")
        md.append("---")
        md.append("")

    # Skipped (.project.yaml overrides)
    if skipped:
        md.append(f"## ⏭️ Skipped ({len(skipped)} controls)")
        md.append("")
        for r in skipped:
            cid = r.get("control_id", r.get("category", "?"))
            md.append(f"- **{cid}**: {r.get('message', 'N/A in .project.yaml')}")
        md.append("")

    # Manual steps
    if manual:
        md.append(f"## 📋 Manual Steps Required ({len(manual)})")
        md.append("")
        for r in manual:
            cid = r.get("control_id", r.get("category", "?"))
            md.append(f"### {cid}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            md.append("")
            if r.get("result"):
                md.append(r["result"])
            md.append("")

    # Errors
    if errors:
        md.append(f"## ❌ Errors ({len(errors)})")
        md.append("")
        for r in errors:
            cid = r.get("control_id", r.get("category", "?"))
            md.append(f"- **{cid}**: {r.get('message', 'Unknown error')}")
        md.append("")

    # Review warnings section (aggregated)
    review_results = [r for r in results if r.get("needs_review") and r.get("status") in ("applied", "would_apply")]
    if review_results:
        md.append("## ⚠️ Changes Requiring Review")
        md.append("")
        md.append(
            "The following remediations may modify application behavior "
            "(e.g., rewriting workflow expressions, changing CI/CD configuration). "
            "**Review the changes before committing.**"
        )
        md.append("")
        for r in review_results:
            cid = r.get("control_id", r.get("category", "?"))
            md.append(f"- **{cid}**: {r.get('description', r.get('result', 'N/A'))}")
        md.append("")
        if not dry_run:
            md.append("Use `git diff` to inspect all modifications.")
            md.append("")

    if not dry_run and applied:
        md.append("Run the audit tool to verify the fixes.")
        md.append("")

    return "\n".join(md)


__all__ = [
    "remediate_audit_findings",
    "_apply_control_remediation",
    "_run_baseline_checks",
]
