"""Remediation orchestrator for OpenSSF Baseline compliance.

This module coordinates the application of remediations based on audit
findings using declarative TOML-based remediation definitions.

All remediation metadata (safe, requires_api, description, context
requirements) comes from the TOML FrameworkConfig.  The orchestrator
iterates *controls*, not hardcoded categories.
"""

import json
import os
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from darnit.config.framework_schema import FrameworkConfig, TemplateConfig
from darnit.config.loader import load_project_config
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
from darnit.remediation.plan import Approval, ErrorInfo, FileChange, PlanItem, RemediationOutcome, RemediationRun
from darnit.tools import (
    calculate_compliance,
    prepare_audit,
    run_checks,
    summarize_results,
)

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
    target: str | None = None,
) -> tuple[AuditResult | None, str | None]:
    """Run baseline checks and return audit result or error.

    Args:
        owner: GitHub owner/organization
        repo: Repository name
        local_path: Path to local repository
        level: Maximum OSPS level to check (1, 2, or 3)
        target: Repository identity the operator named, for the trust decision

    Returns:
        Tuple of (AuditResult, None) on success or (None, error_message) on failure
    """
    # Prepare audit
    owner, repo, resolved_path, default_branch, error = prepare_audit(owner, repo, local_path)
    if error:
        return None, error

    # Run checks - returns (results_list, skipped_controls_dict)
    all_results, skipped_controls = run_checks(
        owner, repo, resolved_path, default_branch, level,
        framework_name="openssf-baseline",
        target=target,
    )

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
    enhance_with_llm: bool = False,
    target: str | None = None,
    platform: Any | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Apply remediation for a single control, driven entirely by TOML.

    Args:
        control_id: The control ID (e.g., "OSPS-GV-01.01")
        local_path: Path to repository
        owner: GitHub owner/organization
        repo: Repository name
        dry_run: If True, only show what would be done
        enhance_with_llm: If True, enrich complex docs with LLM after generation
        target: Repository identity the operator named, for operator-side
            context confirmations
        platform: The run's platform session (policy, approvals, and every
            platform requirement of the run; feature 043)
        run_id: Remediation run whose manifest records this control's writes

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
            target=target,
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
            enhance_with_llm=enhance_with_llm,
            target=target,
            platform=platform,
            run_id=run_id,
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
    enhance_with_llm: bool = False,
    target: str | None = None,
    platform: Any | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Apply a declarative remediation from TOML config.

    Templates and ``when`` clauses read only usable context values: this
    run's detections of keys that may be concluded, overlaid with confirmed
    values. Reading a defined context key without a usable value stops the
    remediation with "confirmation required" (feature 042, FR-006, FR-007).

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
        target: Repository identity the operator named, for operator-side
            context confirmations

    Returns:
        Dict with control_id, status, and result details
    """
    try:
        from darnit.config.context_resolve import resolve_context
        from darnit.config.context_storage import framework_definitions
        from darnit.context.auto_detect import collect_auto_context

        framework = _get_framework_config()
        resolved = resolve_context(
            local_path, framework_definitions(framework) if framework else None, target=target, detect=False
        )
        context_values: dict[str, Any] = collect_auto_context(
            local_path, include_stored=False, definitions=resolved.definitions
        )
        context_values.update(resolved.usable())

        # Resolve framework TOML path for template file resolution
        fw_path: str | None = None
        try:
            from darnit_baseline import get_framework_path
            p = get_framework_path()
            if p:
                fw_path = str(p)
        except Exception as exc:
            logger.warning(f"Framework path resolution failed: {exc}")

        # Scan repository for context-aware template rendering
        scan_values: dict[str, Any] = {}
        try:
            from darnit_baseline.remediation.scanner import (
                flatten_scan_context,
                scan_repository,
            )
            scan_ctx = scan_repository(local_path)
            scan_values = flatten_scan_context(scan_ctx)
        except Exception as exc:
            logger.warning(f"Repository scanning failed: {exc}")

        # Load .project/project.yaml for ${project.*} substitution
        project_values: dict[str, Any] = {}
        try:
            import yaml
            project_yaml = os.path.join(local_path, ".project", "project.yaml")
            if os.path.isfile(project_yaml):
                with open(project_yaml, encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                # Flatten nested keys: {security: {contact: "x"}} -> {"security.contact": "x"}
                def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
                    out: dict[str, str] = {}
                    for k, v in d.items():
                        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
                        if isinstance(v, dict):
                            out.update(_flatten(v, key))
                        elif v is not None:
                            out[key] = str(v) if not isinstance(v, list) else " ".join(str(i) for i in v)
                    return out
                project_values = _flatten(raw)
        except Exception as exc:
            logger.warning(f"Project YAML loading failed: {exc}")

        # Create executor with templates and context
        executor = RemediationExecutor(
            local_path=local_path,
            owner=owner,
            repo=repo,
            templates=templates or {},
            context_values=context_values,
            scan_values=scan_values,
            project_values=project_values,
            framework_path=fw_path,
            unconfirmed_keys=resolved.unusable_keys(),
            run_id=run_id,
            platform=platform,
        )

        # Execute the remediation
        result = executor.execute(
            control_id=control_id,
            config=remediation_config,
            dry_run=dry_run,
        )

        if result.confirmation_required:
            return {
                "control_id": control_id,
                "status": "needs_confirmation",
                "description": description,
                "controls": [control_id],
                "missing_context": [result.confirmation_required],
                "result": (
                    f"{result.message}. Ask the person for `{result.confirmation_required}`; "
                    "record their answer with confirm_project_data, then re-run remediation."
                ),
                "declarative": True,
            }

        plan_items = [item.model_dump(mode="json") for item in result.plan]
        if enhance_with_llm and (dry_run or result.needs_approval):
            planned_changes = [c for item in result.plan for c in item.file_changes]
            for _index, item, _etype in _enhancement_items(control_id, planned_changes, remediation_config):
                if platform is not None:
                    platform.note_known(item.digest)
                plan_items.append(item.model_dump(mode="json"))
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
                "plan": plan_items,
                "references": _unrecorded_references(result.details),
            }

        if result.needs_approval:
            return {
                "control_id": control_id,
                "status": "needs_approval",
                "description": description,
                "controls": [control_id],
                "result": result.message,
                "declarative": True,
                "plan": plan_items,
                "needs_approval": list(result.needs_approval),
            }

        platform_results = _platform_results(result.details)
        applied_record: dict[str, Any] = {
            "plan": plan_items,
            "platform": platform_results,
            "file_changes": [change.model_dump(mode="json") for change in result.file_changes],
            "handlers": _handler_statuses(result.details),
            "references": _unrecorded_references(result.details),
            "approvals": [approval.model_dump(mode="json") for approval in result.approvals],
        }
        platform_status = _platform_status(platform_results, result.changed) if result.success else None
        if platform_status is not None:
            return {
                "control_id": control_id,
                "status": platform_status,
                "description": description,
                "controls": [control_id],
                "result": _platform_summary(platform_results),
                "declarative": True,
                **applied_record,
            }

        if result.success:
            logger.info(f"Applied declarative remediation: {control_id} ({result.remediation_type})")

            enhanced = False
            if enhance_with_llm:
                enhanced, items, approvals, pending = _enhance_created_files(
                    executor, result, remediation_config, local_path, control_id
                )
                applied_record["file_changes"] = [change.model_dump(mode="json") for change in result.file_changes]
                applied_record["plan"] += [item.model_dump(mode="json") for item in items]
                applied_record["approvals"] += [approval.model_dump(mode="json") for approval in approvals]
                applied_record["enhancement_needs_approval"] = pending

            result_dict: dict[str, Any] = {
                "control_id": control_id,
                "status": "applied",
                "description": description,
                "controls": [control_id],
                "remediation_type": result.remediation_type,
                "result": result.message,
                "declarative": True,
                "enhanced": enhanced,
                **applied_record,
            }
            # Propagate handler evidence containing LLM consultation
            # payloads so the MCP tool can surface them to the agent.
            for handler_info in (result.details or {}).get("handlers", []):
                evidence = handler_info.get("evidence", {})
                if evidence.get("llm_verification_required"):
                    result_dict["needs_review"] = True
                    result_dict["llm_consultation"] = evidence.get(
                        "llm_consultation"
                    )
                    break
            return result_dict
        else:
            logger.error(f"Declarative remediation failed: {result.message}")
            failures = [h for h in (result.details or {}).get("handlers", []) if h.get("status") == "error"]
            return {
                "control_id": control_id,
                "status": "error",
                "description": description,
                "message": "; ".join(h.get("message", "") for h in failures) or result.message,
                "declarative": True,
                **applied_record,
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


def _enhancement_items(
    control_id: str, changes: list[FileChange], remediation_config: Any
) -> list[tuple[int, PlanItem, str]]:
    """``(index in changes, plan item, enhancement type)`` for each created file a model would customize (FR-023).

    The model's output cannot be computed in advance, so each customization
    is its own plan item that cannot be previewed exactly and needs
    individual approval. Its digest covers the path and the digest of the
    content the file is created with, so an approval covers enhancing that
    content only.
    """
    from darnit.remediation.plan import normalize_repo_path
    from darnit_baseline.remediation.enhancer import get_enhancement_type, is_enhanceable

    created = {c.path: index for index, c in enumerate(changes) if c.action == "create"}
    items: list[tuple[int, PlanItem, str]] = []
    for handler_inv in remediation_config.handlers:
        if handler_inv.handler != "file_create":
            continue
        try:
            path = normalize_repo_path((handler_inv.model_extra or {}).get("path") or "")
        except ValueError:
            continue
        index = created.get(path)
        if index is None or not is_enhanceable(path):
            continue
        etype = get_enhancement_type(path)
        if not etype:
            continue
        item = PlanItem(
            control_id=control_id,
            step=f"llm_enhance[{path}] of {changes[index].after_digest}",
            previewable=False,
            requires_individual_approval=True,
        )
        items.append((index, item, etype))
    return items


def _enhance_created_files(
    executor: RemediationExecutor,
    result: Any,
    remediation_config: Any,
    local_path: str,
    control_id: str,
) -> tuple[bool, list[PlanItem], list[Approval], list[str]]:
    """Enrich complex documents this apply created, through the executor's writer (framework-design 4.3).

    Only a file whose ``FileChange`` in ``result`` is a create is enhanced; a
    file that existed before the run is never touched. Each enhancement is a
    plan item (:func:`_enhancement_items`) and runs only when the executor
    approves it; otherwise the file keeps the content it was created with
    and the item's digest is returned as needing approval. Enhanced content
    is recorded in the run manifest, so it stays committable.

    Returns ``(enhanced, items, approvals, digests needing approval)``.
    """
    from darnit.remediation.executor import WriteRefused
    from darnit_baseline.remediation.enhancer import enhance_generated_file

    enhanced = False
    items: list[PlanItem] = []
    approvals: list[Approval] = []
    pending: list[str] = []
    for index, item, etype in _enhancement_items(control_id, result.file_changes, remediation_config):
        items.append(item)
        approval = executor.approve_item(item)
        if approval is None:
            pending.append(item.digest)
            continue
        approvals.append(approval)
        path = result.file_changes[index].path
        try:
            enriched = enhance_generated_file(os.path.join(local_path, path), local_path, etype)
        except Exception as e:
            logger.debug("LLM enhancement skipped for %s: %s", path, e)
            continue
        if not enriched:
            continue
        try:
            result.file_changes[index] = executor.amend_created(result.file_changes[index], enriched)
        except (WriteRefused, OSError, ValueError, LookupError) as e:
            logger.warning("LLM enhancement of %s for %s not written: %s", path, control_id, e)
            continue
        enhanced = True
        logger.info("LLM-enhanced %s for %s", path, control_id)
    return enhanced, items, approvals, pending


def _platform_results(details: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The platform engine's results reported by this control's ``platform_setting`` steps."""
    return [
        platform_result
        for handler in (details or {}).get("handlers", [])
        for platform_result in (handler.get("evidence") or {}).get("platform_results", [])
    ]


def _unrecorded_references(details: dict[str, Any] | None) -> list[str]:
    """Why each declared ``project_reference`` was not recorded (framework-design 4.3)."""
    return [
        f"{note['path']} is not recorded as {note['reference']}: {note['reason']}"
        for h in (details or {}).get("handlers", [])
        if (note := h.get("project_reference")) and not note["recorded"]
    ]


def _handler_statuses(details: dict[str, Any] | None) -> list[dict[str, str]]:
    return [
        {"handler": h.get("handler", "?"), "status": h.get("status", "?"), "message": h.get("message", "")}
        for h in (details or {}).get("handlers", [])
    ]


def _platform_status(platform_results: list[dict[str, Any]], changed: bool) -> str | None:
    """The control status when a platform step changed nothing, else None."""
    kinds = [p["kind"] for p in platform_results]
    if "needs_approval" in kinds:
        return "needs_approval"
    if "manual" in kinds:
        return "manual"
    if any(p["kind"] == "unchanged" and p.get("reason") == "stale_preview" for p in platform_results):
        return "unchanged"
    if kinds and set(kinds) == {"unchanged"} and not changed:
        return "unchanged"
    return None


def _platform_summary(platform_results: list[dict[str, Any]]) -> str:
    from darnit.remediation.platform import ChangeSet
    from darnit.remediation.platform.policy import describe_change_set

    lines: list[str] = []
    for platform_result in platform_results:
        kind = platform_result["kind"]
        change_set = platform_result.get("change_set")
        if kind == "needs_approval" and change_set:
            lines.append("Needs approval of this change set's digest; nothing was written:")
            lines += describe_change_set(ChangeSet.model_validate(change_set))
        elif kind == "manual":
            lines.append(f"darnit made no platform change ({platform_result.get('reason')}). Steps:")
            lines += [f"{i}. {step}" for i, step in enumerate(platform_result.get("steps", []), 1)]
        elif kind == "unchanged" and platform_result.get("reason") == "stale_preview":
            lines.append("The settings changed since the preview; nothing was written. Preview again.")
        elif kind == "unchanged":
            lines.append(f"Platform setting already satisfied ({platform_result.get('reason')}); nothing was written.")
    return "\n".join(lines)


# =============================================================================
# Pre-flight Context Check
# =============================================================================


def _preflight_context_check(
    control_ids: list[str],
    local_path: str,
    owner: str | None,
    repo: str | None,
    target: str | None = None,
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
        return True, {"missing_context": [], "auto_detected": {}, "candidates": {}, "prompts": []}

    # Check all requirements at once
    requirements_list = [req for _, req in all_requirements.values()]
    check_result = check_context_requirements(
        requirements=requirements_list,
        local_path=local_path,
        framework=framework,
        owner=owner,
        repo=repo,
        target=target,
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
        "candidates": check_result.candidates,
        "prompts": check_result.prompts,
        "key_to_controls": key_to_controls,
    }


def _format_preflight_prompt(
    context_info: dict[str, Any],
    local_path: str,
) -> str:
    """Format the pre-flight context check results as a user-friendly prompt.

    Each key's prompt shows its candidate, if any, as unconfirmed data with
    origin and digest (feature 042, FR-013); the command below holds
    placeholders only.

    Args:
        context_info: Dict with missing_context, candidates, prompts, key_to_controls
        local_path: Path to repository

    Returns:
        Markdown-formatted prompt for user
    """
    from darnit.config.context_resolve import ANSWER_PLACEHOLDER, DIGEST_PLACEHOLDER

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
    md.append("You **MUST** use the `confirm_project_data()` tool to set context values.")
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

    missing = context_info.get("missing_context", [])
    candidates = context_info.get("candidates", {})
    accepted = [key for key in missing if key in candidates]
    answered = [key for key in missing if key not in candidates]

    md.append("---")
    md.append("")
    md.append("**AI Agents:** You MUST ask the user for the missing values above, showing each candidate")
    md.append("as unconfirmed data. Do NOT guess or infer from repository owner, git history, or other sources.")
    md.append("")
    md.append("**After the user answers, confirm the answers, then re-run remediation.** For a key with a")
    md.append("candidate, either accept it by its digest (only if the user accepted it) or pass the user's answer:")
    md.append("```python")
    args = [f'local_path="{local_path}"']
    if accepted:
        pairs = ", ".join(f'"{key}": "{DIGEST_PLACEHOLDER}"' for key in accepted)
        args.append(f"accept_candidates={{{pairs}}}")
    args += [f"{key}={ANSWER_PLACEHOLDER}" for key in answered]
    args += ["owner=...", "repo=..."]
    md.append("confirm_project_data(\n    " + ",\n    ".join(args) + "\n)")
    md.append("```")

    return "\n".join(md)


# =============================================================================
# Main Entry Point
# =============================================================================


@dataclass(frozen=True)
class RemediationReport:
    """A remediation call's Markdown report and, when remediation ran, its run record."""

    markdown: str
    run: RemediationRun | None = None


def remediate_audit_findings(
    local_path: str = ".",
    owner: str | None = None,
    repo: str | None = None,
    categories: list[str] | None = None,
    dry_run: bool = True,
    profile: str | None = None,
    enhance_with_llm: bool = False,
    approve: list[str] | None = None,
    run_id: str | None = None,
) -> str:
    """Apply automated remediations for failed audit controls.

    Iterates all failed controls that have TOML-defined remediation and
    applies them.  The optional ``categories`` parameter filters to a
    subset (supports both domain-based and legacy category names).

    Platform changes follow the operator's remediation policy (feature 043):
    under ``prompt`` a change set is written only when its digest is in
    ``approve``. After an apply, every control whose remediation changed
    something is re-checked without writing the audit cache, and its outcome
    says whether it now passes. The report ends with a fenced JSON block
    holding the ``RemediationRun`` (run id, policy, plan items and change
    sets with their digests, and in an apply the per-control outcomes).

    Args:
        local_path: Absolute path to repository
        owner: GitHub org/user (auto-detected if not provided)
        repo: Repository name (auto-detected if not provided)
        categories: Optional filter — list of category names, or ["all"]
        dry_run: If True (default), show what would be changed without applying
        profile: Optional audit profile name to filter to profile controls only
        enhance_with_llm: If True, enrich complex documents with LLM-generated
            descriptions after deterministic generation.  Default False.
        approve: Digests of the previewed change sets (and plan items) the
            person approved
        run_id: Remediation run whose manifest records an apply's writes
            (default: a new run); the git steps use the same run

    Returns:
        Markdown-formatted summary of applied or planned remediations
    """
    return run_remediation(
        local_path=local_path,
        owner=owner,
        repo=repo,
        categories=categories,
        dry_run=dry_run,
        profile=profile,
        enhance_with_llm=enhance_with_llm,
        approve=approve,
        run_id=run_id,
    ).markdown


def run_remediation(
    local_path: str = ".",
    owner: str | None = None,
    repo: str | None = None,
    categories: list[str] | None = None,
    dry_run: bool = True,
    profile: str | None = None,
    enhance_with_llm: bool = False,
    approve: list[str] | None = None,
    run_id: str | None = None,
) -> RemediationReport:
    """:func:`remediate_audit_findings`, returning the run record with the report.

    ``run`` is None when remediation did not run (an error, nothing to
    remediate, or context that needs confirmation).
    """
    # Validate path
    resolved_path, path_error = validate_local_path(local_path)
    if path_error:
        return RemediationReport(f"Error: {path_error}")
    local_path = resolved_path

    from darnit.core.utils import detect_owner_repo
    from darnit.trust.decision import target_from_owner_repo

    target = target_from_owner_repo(owner, repo)

    # Auto-detect owner/repo (origin first)
    if not owner or not repo:
        detected_owner, detected_repo = detect_owner_repo(local_path)
        owner = owner or detected_owner
        repo = repo or detected_repo

    # Load framework config (needed for control discovery)
    framework = _get_framework_config()
    if not framework:
        return RemediationReport("Error: Could not load framework TOML config")

    # Apply profile filtering if specified
    profile_ids: set[str] | None = None
    if profile:
        try:
            from darnit.config.control_loader import load_controls_from_framework
            from darnit.config.profile_resolver import (
                resolve_profile,
                resolve_profile_control_ids,
            )

            all_controls = load_controls_from_framework(framework)
            profile_impls: dict = {}
            if framework.audit_profiles:
                profile_impls["openssf-baseline"] = dict(framework.audit_profiles)
            _, profile_config = resolve_profile(profile, profile_impls)
            profile_ids = set(resolve_profile_control_ids(profile_config, all_controls))
        except Exception as e:
            return RemediationReport(f"Error resolving profile '{profile}': {e}")

    # ------------------------------------------------------------------
    # Determine which controls failed the audit.
    # Only FAIL controls are remediated — WARN means "can't verify
    # automatically" and existing content may be correct.
    # ------------------------------------------------------------------
    failed_ids: set[str] | None = None
    audit_results: list[dict[str, Any]] = []
    error: str | None = None

    try:
        # Issue #542: remediation acts on a full level-3 audit of this
        # framework, which is what it runs on a miss. A level-1, filtered or
        # other-framework cache is a subset, so it must miss. The read goes
        # through the store and key the audit writes to.
        from darnit.tools.audit import read_full_audit_cache

        cache = read_full_audit_cache(local_path, "openssf-baseline", level=3)
    except Exception as exc:
        logger.warning(f"Audit cache read failed: {exc}")
        cache = None

    if cache is not None:
        logger.info("Using cached audit results (skipping redundant audit)")
        audit_results = cache["results"]
        failed_ids = {
            r.get("id", "") for r in audit_results if r.get("status") == "FAIL"
        }
    else:
        logger.info("No cached audit results, running audit")
        audit_result, error = _run_baseline_checks(
            owner=owner, repo=repo, local_path=local_path, target=target
        )
        if not error and audit_result:
            audit_results = audit_result.all_results
            failed_ids = {
                r.get("id", "") for r in audit_results if r.get("status") == "FAIL"
            }

    # Feature 040: only an honored not-applicable claim exempts a control
    # from remediation; pending and contradicted claims never do.
    honored_claims = {
        r.get("id", ""): r["assertion"].get("reason") or "asserted not applicable"
        for r in audit_results
        if (r.get("assertion") or {}).get("outcome") == "honored"
    }

    # Apply profile filter to failed_ids
    if profile_ids is not None and failed_ids is not None:
        failed_ids = failed_ids & profile_ids

    # ------------------------------------------------------------------
    # Build the list of controls to remediate
    # ------------------------------------------------------------------
    if not categories or categories == ["all"]:
        if error:
            return RemediationReport(f"Error running audit: {error}")
        if not failed_ids:
            if failed_ids is None:
                return RemediationReport("Error: Audit did not produce results. Try running an audit first.")
            return RemediationReport("No remediations needed - all controls are passing.")

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
        if failed_ids:
            no_handler_ids = sorted(failed_ids)
            return RemediationReport(
                f"{len(failed_ids)} control(s) failed but none have auto-fix handlers.\n\n"
                f"**Controls without auto-fix:** {', '.join(no_handler_ids)}\n\n"
                "These require manual remediation."
            )
        return RemediationReport("No remediations needed - all controls are passing.")

    # ------------------------------------------------------------------
    # Pre-flight context check (prompt for ALL missing context upfront)
    # ------------------------------------------------------------------
    context_ready, context_info = _preflight_context_check(
        control_ids=remediable_ids,
        local_path=local_path,
        owner=owner,
        repo=repo,
        target=target,
    )

    if not context_ready:
        return RemediationReport(_format_preflight_prompt(context_info, local_path))

    # ------------------------------------------------------------------
    # Platform session: one policy, one set of approvals, and every
    # platform requirement of the run planned together (feature 043)
    # ------------------------------------------------------------------
    from darnit.config.operator.loader import OperatorConfigError
    from darnit.remediation import manifest
    from darnit.remediation.platform import PlatformSession, platform_repository, platform_requests, resolve_policy

    try:
        policy = resolve_policy(local_path)
    except OperatorConfigError as e:
        return RemediationReport(f"Error: remediation policy unavailable: {e}")
    run_id = run_id or manifest.new_run_id()
    repository = platform_repository(local_path, owner, repo) or manifest.repository_identity(local_path, owner, repo)
    session = PlatformSession(
        repository,
        platform_requests(framework, [c for c in remediable_ids if c not in honored_claims]),
        policy=policy,
        approvals=approve or [],
    )

    # ------------------------------------------------------------------
    # Apply remediations
    # ------------------------------------------------------------------
    results = []
    for control_id in remediable_ids:
        if control_id in honored_claims:
            results.append({
                "control_id": control_id,
                "status": "skipped",
                "description": framework.controls[control_id].description or control_id,
                "message": f"Not applicable (asserted, honored): {honored_claims[control_id]}",
            })
            continue
        result = _apply_control_remediation(
            control_id=control_id,
            local_path=local_path,
            owner=owner,
            repo=repo,
            dry_run=dry_run,
            enhance_with_llm=enhance_with_llm,
            target=target,
            platform=session,
            run_id=None if dry_run else run_id,
        )
        results.append(result)

    # ------------------------------------------------------------------
    # Outcomes: re-check what changed, then invalidate the stale cache
    # ------------------------------------------------------------------
    outcomes: list[RemediationOutcome] = []
    if not dry_run:
        _reclassify_stale_previews(results, session.approvals)
        outcomes = _outcomes(results, lambda ids: _recheck(ids, local_path, owner, repo, target))
        if any(_written(r) or _applied_change_sets(r) for r in results):
            try:
                from darnit.core import audit_cache

                audit_cache.invalidate_audit_cache(local_path)
            except Exception as exc:
                logger.warning(f"Failed to invalidate audit cache: {exc}")

    run = RemediationRun(
        run_id=run_id,
        repository=repository,
        mode="preview" if dry_run else "apply",
        policy=policy.settings,
        operator_config_digest=policy.operator_config_digest,
        approvals=_run_approvals(session.used_approvals, results),
        plan=[PlanItem.model_validate(item) for r in results for item in r.get("plan", [])],
        outcomes=outcomes,
    )
    markdown = _format_remediation_output(
        results=results,
        local_path=local_path,
        owner=owner,
        repo=repo,
        dry_run=dry_run,
        categories=categories,
        run=run,
    )
    return RemediationReport(markdown, run)


_RECHECK_FIELDS = ("status", "details", "authority", "error", "error_class", "pending")


def _run_digests(results: list[dict[str, Any]]) -> set[str]:
    """Every plan-item and change-set digest the controls of this run planned or applied."""
    seen: set[str] = set()
    for r in results:
        for item in r.get("plan", []):
            seen.add(item["digest"])
            seen.update(cs["digest"] for cs in item.get("change_sets", []))
        seen.update(p["change_set"]["digest"] for p in r.get("platform") or [] if p.get("change_set"))
    return seen


def _reclassify_stale_previews(results: list[dict[str, Any]], approvals: Collection[str]) -> None:
    """Turn ``stale_preview`` into ``needs_approval`` when every approval matches an item of this run (15.2).

    A change set applied before a later control was planned saw that
    control's approved items as unmatched. Once every control has run, an
    approval that matches a digest of the run is not stale. Nothing was
    written for such a change set either way.
    """
    if not approvals or not set(approvals) <= _run_digests(results):
        return
    for r in results:
        platform_results = r.get("platform") or []
        stale = [p for p in platform_results if p["kind"] == "unchanged" and p.get("reason") == "stale_preview"]
        if not stale:
            continue
        for p in stale:
            p["kind"], p["reason"] = "needs_approval", None
        if r.get("status") == "unchanged":
            r["status"] = _platform_status(platform_results, bool(_written(r))) or r["status"]
            r["result"] = _platform_summary(platform_results)


def _run_approvals(platform_approvals: list[Approval], results: list[dict[str, Any]]) -> list[Approval]:
    """The run's approvals: change sets the platform engine applied, and plan items approved individually (15.3)."""
    approvals = {a.digest: a for a in platform_approvals}
    for r in results:
        for raw in r.get("approvals", []):
            approvals.setdefault(raw["digest"], Approval.model_validate(raw))
    return list(approvals.values())


def _written(r: dict[str, Any]) -> list[FileChange]:
    """The files this control's apply wrote."""
    return [FileChange.model_validate(c) for c in r.get("file_changes", []) if c.get("action") != "none"]


def _applied_change_sets(r: dict[str, Any]) -> list[dict[str, Any]]:
    """The change sets this control's apply wrote, each with the settings its read-back shows changed."""
    return [
        {**p["change_set"], "read_back": p.get("changed", [])}
        for p in r.get("platform") or []
        if p.get("change_set") and (p["kind"] == "applied" or p.get("changed"))
    ]


def _enhancement_notes(r: dict[str, Any]) -> list[str]:
    """One note per created file whose model customization was not approved; it keeps its created content."""
    steps = {item["digest"]: item["step"] for item in r.get("plan", [])}
    return [
        f"{steps.get(d, 'llm_enhance')} needs individual approval of plan item digest {d}; "
        "the file keeps the content it was created with"
        for d in r.get("enhancement_needs_approval", [])
    ]


def _settled_outcome(r: dict[str, Any]) -> RemediationOutcome | None:
    """The outcome of a control whose apply needs no re-check, or None when it changed something (15.4)."""
    control_id = r.get("control_id", "?")
    status = r.get("status")
    platform_results = r.get("platform") or []
    written = _written(r)
    applied = _applied_change_sets(r)
    if status == "needs_confirmation":
        return RemediationOutcome(
            control_id=control_id,
            kind="needs_confirmation",
            reason="confirmation required: " + ", ".join(r.get("missing_context") or []),
        )
    if status == "needs_approval" and r.get("needs_approval"):
        unapproved = set(r["needs_approval"])
        return RemediationOutcome(
            control_id=control_id,
            kind="needs_approval",
            change_sets=[cs for item in r.get("plan", []) if item["digest"] in unapproved for cs in item["change_sets"]],
            reason=(
                "individual approval required for plan item digest(s) "
                + ", ".join(sorted(unapproved))
                + "; no step of this remediation was run"
            ),
        )
    if status == "needs_approval":
        pending = [p["change_set"] for p in platform_results if p["kind"] == "needs_approval" and p.get("change_set")]
        return RemediationOutcome(
            control_id=control_id,
            kind="needs_approval",
            file_changes=written,
            change_sets=pending,
            reason="approval required; nothing was written for this change",
        )
    if status == "manual":
        return RemediationOutcome(
            control_id=control_id, kind="manual", file_changes=written, reason=r.get("result") or "manual steps"
        )
    if status == "error":
        platform_errors = [p["error"] for p in platform_results if p.get("error")]
        error = (
            ErrorInfo.model_validate(platform_errors[0])
            if platform_errors
            else ErrorInfo(error_class="crashed", cause=r.get("message") or "remediation failed")
        )
        return RemediationOutcome(
            control_id=control_id, kind="error", file_changes=written, change_sets=applied, error=error
        )
    if written or applied:
        return None
    unchanged = [FileChange.model_validate(c) for c in r.get("file_changes", []) if c.get("action") == "none"]
    reasons = [c.reason for c in unchanged if c.reason]
    reasons += [p["reason"] for p in platform_results if p.get("reason")]
    reasons += [
        f"{h['handler']} returned {h['status']}: {h['message']}"
        for h in r.get("handlers", [])
        if h.get("status") != "pass"
    ]
    return RemediationOutcome(
        control_id=control_id,
        kind="unchanged",
        file_changes=unchanged,
        reason=", ".join(dict.fromkeys(reasons)) or r.get("message") or "nothing changed",
    )


def _rechecked_outcome(r: dict[str, Any], result: dict[str, Any] | None, failure: str | None) -> RemediationOutcome:
    """The outcome of a control whose apply changed something, from its re-check (15.5)."""
    common: dict[str, Any] = {
        "control_id": r.get("control_id", "?"),
        "file_changes": _written(r),
        "change_sets": _applied_change_sets(r),
        "reason": "; ".join(r.get("references", []) + _enhancement_notes(r)) or None,
    }
    if result is None:
        cause = failure or "the re-check returned no result for this control"
        return RemediationOutcome(
            kind="changed_not_verified", error=ErrorInfo(error_class="crashed", cause=cause), **common
        )
    recheck = {k: result[k] for k in _RECHECK_FIELDS if k in result}
    status = recheck.get("status")
    if status == "PASS":
        return RemediationOutcome(kind="fixed", recheck=recheck, **common)
    if status == "ERROR":
        block = recheck.get("error") or {}
        error = ErrorInfo(
            error_class=block.get("class") or recheck.get("error_class") or "evaluation",
            cause=block.get("cause") or recheck.get("details") or "the re-check ended ERROR",
        )
        return RemediationOutcome(kind="changed_not_verified", recheck=recheck, error=error, **common)
    return RemediationOutcome(kind="changed_not_passing", recheck=recheck, **common)


def _outcomes(
    results: list[dict[str, Any]], recheck: Callable[[list[str]], dict[str, dict[str, Any]]]
) -> list[RemediationOutcome]:
    """One outcome per control; controls whose apply changed something are re-checked together."""
    settled = [_settled_outcome(r) for r in results]
    changed = [r.get("control_id", "?") for r, outcome in zip(results, settled, strict=True) if outcome is None]
    rechecked: dict[str, dict[str, Any]] = {}
    failure: str | None = None
    if changed:
        try:
            rechecked = recheck(changed)
        except Exception as e:
            logger.warning(f"Re-check of remediated controls could not run: {e}")
            failure = f"the re-check could not run: {e}"
    return [
        outcome or _rechecked_outcome(r, rechecked.get(r.get("control_id", "?")), failure)
        for r, outcome in zip(results, settled, strict=True)
    ]


def _recheck(
    control_ids: list[str], local_path: str, owner: str | None, repo: str | None, target: str | None
) -> dict[str, dict[str, Any]]:
    """Re-check ``control_ids`` through the canonical audit pipeline, without writing the audit cache (15.5)."""
    from darnit.config.control_loader import load_controls_from_effective
    from darnit.config.merger import merge_configs
    from darnit.config.operator.loader import resolve_operator_config
    from darnit.tools import audit as audit_tools

    framework = _get_framework_config()
    if framework is None:
        raise RuntimeError("the framework configuration could not be loaded")
    owner, repo, resolved_path, default_branch, error = prepare_audit(owner, repo, local_path)
    if error:
        raise RuntimeError(error)
    operator_config = resolve_operator_config(resolved_path)
    wanted = set(control_ids)
    specs = [
        spec
        for spec in load_controls_from_effective(merge_configs(framework, operator_config.config))
        if spec.control_id in wanted
    ]
    results, _ = audit_tools.run_sieve_audit(
        owner or "",
        repo or "",
        resolved_path,
        default_branch,
        3,
        controls=specs,
        framework_name="openssf-baseline",
        operator_config=operator_config,
        target=target,
        write_cache=False,
    )
    return {r["id"]: r for r in results}


def _file_lines(changes: list[FileChange], *, preview: bool) -> list[str]:
    lines: list[str] = []
    for change in changes:
        if change.action == "none":
            lines.append(f"- `{change.path}`: not written ({change.reason})")
            continue
        verb = {"create": "created", "modify": "modified"}[change.action]
        lines.append(f"- `{change.path}`: {'would be ' + verb if preview else verb}")
        if change.ignored:
            lines.append("  - ignored by the repository's ignore rules; it is never committed")
    return lines


def _change_set_lines(change_sets: list[dict[str, Any]]) -> list[str]:
    from darnit.remediation.platform import ChangeSet
    from darnit.remediation.platform.policy import describe_change_set

    lines: list[str] = []
    for change_set in change_sets:
        if not change_set["operations"]:
            lines.append(f"- Platform setting already satisfied ({change_set['satisfied_by']}); nothing to change")
            continue
        lines += ["- **Platform change** (approve by its digest):", "```text"]
        lines += describe_change_set(ChangeSet.model_validate({k: v for k, v in change_set.items() if k != "read_back"}))
        lines.append("```")
    return lines


def _applied_platform_lines(change_sets: list[dict[str, Any]]) -> list[str]:
    from darnit.remediation.platform.targets import show_value

    lines: list[str] = []
    for change_set in change_sets:
        target = change_set["target"]
        where = f"{target['owner']}/{target['repo']}" + (f" branch {target['branch']}" if target.get("branch") else "")
        changes = change_set.get("read_back") or [c for op in change_set["operations"] for c in op["changes"]]
        lines.append(f"- **Platform:** {target['kind']} on {where} (`{change_set['digest']}`)")
        lines += [f"  - {c['field']}: {show_value(c['before'])} -> {show_value(c['after'])}" for c in changes]
        lines += [f"  - Impact: {note}" for note in change_set.get("impact_notes", [])]
    return lines


def _plan_item_lines(item: PlanItem) -> list[str]:
    lines = _file_lines(item.file_changes, preview=True)
    lines += _change_set_lines(item.change_sets)
    lines += [f"- Command: `{' '.join(command)}`" for command in item.commands]
    if not item.previewable:
        lines.append(f"- `{item.step}` cannot be previewed exactly; it may change files or settings not listed here")
    if item.requires_individual_approval:
        lines.append(f"- Requires individual approval: plan item digest `{item.digest}`")
    return lines


def _run_lines(run: RemediationRun) -> list[str]:
    lines = [
        f"**Run:** `{run.run_id}`",
        f"**Policy:** platform={run.policy.platform}, high_impact={run.policy.high_impact}",
        (
            f"**Operator configuration:** `{run.operator_config_digest}`"
            if run.operator_config_digest
            else "**Operator configuration:** built-in defaults (no operator configuration file)"
        ),
    ]
    if run.approvals:
        lines.append("**Approvals:**")
        lines += [f"- `{a.digest}` by {a.approved_by} at {a.approved_at.isoformat()}" for a in run.approvals]
    else:
        lines.append("**Approvals:** none")
    return lines + [""]


def _preview_lines(
    results: list[dict[str, Any]], run: RemediationRun, local_path: str, categories: list[str] | None
) -> list[str]:
    plan: dict[str, list[PlanItem]] = {}
    for item in run.plan:
        plan.setdefault(item.control_id, []).append(item)

    would_apply = [r for r in results if r.get("status") == "would_apply"]
    md = [f"## Would Apply ({len(would_apply)} remediations)", ""]
    for r in would_apply:
        cid = r.get("control_id", "?")
        api_note = " *(requires GitHub API)*" if r.get("requires_api") else ""
        declarative_note = " *(declarative)*" if r.get("declarative") else ""
        review_note = " **REVIEW REQUIRED**" if r.get("needs_review") else ""
        md.append(f"### {cid}{api_note}{declarative_note}{review_note}")
        md.append(f"- **Description:** {r.get('description', 'N/A')}")
        if r.get("remediation_type"):
            md.append(f"- **Type:** {r.get('remediation_type')}")
        for item in plan.get(cid, []):
            md.extend(_plan_item_lines(item))
        md += [f"- {note}" for note in r.get("references", [])]
        md.append("")

    md += _status_sections(results)
    md += ["---", "", "**To apply these remediations:**", "```python", "remediate_audit_findings("]
    md.append(f'    local_path="{local_path}",')
    if categories and categories != ["all"]:
        md.append(f"    categories=[{', '.join(repr(c) for c in categories)}],")
    md += ["    dry_run=False,", "    approve=[<only the digests the person approved>],", ")", "```", ""]
    md.append(
        "Platform changes are written only for approved digests under the default policy; "
        "`dry_run=False` alone approves nothing."
    )
    md.append("")
    return md


def _status_sections(results: list[dict[str, Any]]) -> list[str]:
    """Preview sections for controls that have no plan to apply."""
    md: list[str] = []
    sections = (
        ("needs_confirmation", "Needs Confirmation"),
        ("manual", "Manual Steps Required"),
        ("skipped", "Skipped"),
        ("no_remediation", "No Remediation"),
        ("error", "Errors"),
    )
    for status, title in sections:
        matching = [r for r in results if r.get("status") == status]
        if not matching:
            continue
        md += [f"## {title} ({len(matching)})", ""]
        for r in matching:
            md.append(f"### {r.get('control_id', '?')}")
            md.append(f"- **Description:** {r.get('description', 'N/A')}")
            if r.get("message"):
                md.append(f"- {r['message']}")
            if r.get("result"):
                md += ["", r["result"]]
            md.append("")
    return md


def _outcome_lines(run: RemediationRun, results: list[dict[str, Any]]) -> list[str]:
    by_id = {r.get("control_id", "?"): r for r in results}
    md = ["## Summary", "", "| Outcome | Count |", "|---|---|"]
    md += [f"| {kind} | {count} |" for kind, count in run.summary.items()]
    md.append("")
    if run.outcomes:
        md += ["## Outcomes", ""]
    for outcome in run.outcomes:
        r = by_id.get(outcome.control_id, {})
        md.append(f"### {outcome.control_id}: {outcome.kind}")
        if r.get("description"):
            md.append(f"- **Description:** {r['description']}")
        md += _file_lines(outcome.file_changes, preview=False)
        if outcome.kind == "needs_approval" and r.get("needs_approval"):
            for item in r.get("plan", []):
                if item["digest"] in r["needs_approval"]:
                    md += _plan_item_lines(PlanItem.model_validate(item))
        elif outcome.kind == "needs_approval":
            md += _change_set_lines(outcome.change_sets)
        else:
            md += _applied_platform_lines(outcome.change_sets)
        if outcome.recheck is not None:
            details = f" ({outcome.recheck['details']})" if outcome.recheck.get("details") else ""
            md.append(f"- **Re-check:** {outcome.recheck.get('status')}{details}")
        if outcome.reason and outcome.kind != "manual":
            md.append(f"- **Reason:** {outcome.reason}")
        for item in r.get("plan", []):
            if item["digest"] in r.get("enhancement_needs_approval", []):
                md += _plan_item_lines(PlanItem.model_validate(item))
        if outcome.error is not None:
            md.append(f"- **Error:** {outcome.error.error_class}: {outcome.error.cause}")
        if outcome.kind in ("needs_confirmation", "manual") and r.get("result"):
            md += ["", r["result"]]
        md.append("")
    return md


def _review_lines(results: list[dict[str, Any]], dry_run: bool) -> list[str]:
    review = [r for r in results if r.get("needs_review") and r.get("status") in ("applied", "would_apply")]
    if not review:
        return []
    md = [
        "## Changes Requiring Review",
        "",
        "The following remediations may modify application behavior "
        "(e.g., rewriting workflow expressions, changing CI/CD configuration). "
        "**Review the changes before committing.**",
        "",
    ]
    md += [f"- **{r.get('control_id', '?')}**: {r.get('description', r.get('result', 'N/A'))}" for r in review]
    md.append("")
    if not dry_run:
        md += ["Use `git diff` to inspect all modifications.", ""]
    return md


def _consultation_lines(results: list[dict[str, Any]]) -> list[str]:
    """Structured review requests from handlers that set ``llm_verification_required`` (e.g., threat model)."""
    md: list[str] = []
    consultations = [r for r in results if r.get("llm_consultation") and r.get("status") == "applied"]
    if consultations:
        md += ["## LLM Verification Required", ""]
    for r in consultations:
        consultation = r["llm_consultation"]
        md.append(f"### {r.get('control_id', '?')}: Review generated threat model")
        md.append("")
        md.append(f"**File:** `{consultation.get('file_path', '?')}`")
        md.append(f"**Findings to review:** {consultation.get('total_findings', 0)}")
        md.append("")
        by_sev = consultation.get("summary", {}).get("by_severity", {})
        if by_sev:
            md += ["| Severity | Count |", "|----------|-------|"]
            md += [f"| {sev} | {by_sev[sev]} |" for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW") if by_sev.get(sev, 0) > 0]
            md.append("")
        md += [consultation.get("instructions", ""), ""]
        findings = consultation.get("findings_to_review", [])
        high_medium = [f for f in findings if f.get("severity_band") in ("CRITICAL", "HIGH", "MEDIUM")]
        if high_medium:
            md += [f"### Findings requiring review ({len(high_medium)})", ""]
            for f in high_medium:
                md.append(f"- **{f['severity_band']}** | `{f['location']}` | {f['title']}")
                if f.get("review_hint"):
                    md.append(f"  - *{f['review_hint']}*")
            md.append("")
        low = [f for f in findings if f.get("severity_band") == "LOW"]
        if low:
            md.append(
                f"*Plus {len(low)} LOW-risk findings rendered as a summary table in the file. "
                "Spot-check a few but these are likely acceptable as-is.*"
            )
            md.append("")
    return md


def _format_remediation_output(
    results: list[dict[str, Any]],
    local_path: str,
    owner: str | None,
    repo: str | None,
    dry_run: bool,
    run: RemediationRun,
    categories: list[str] | None = None,
) -> str:
    """The Markdown report rendered from ``run`` (contract section 5), followed by ``run`` as fenced JSON."""
    md = [
        f"# Remediation {'Preview (dry run)' if dry_run else 'Applied'}",
        f"**Repository:** {owner}/{repo}" if owner and repo else f"**Path:** {local_path}",
        "",
    ]
    md += _run_lines(run)
    md += _preview_lines(results, run, local_path, categories) if dry_run else _outcome_lines(run, results)
    md += _review_lines(results, dry_run)
    if not dry_run:
        md += _consultation_lines(results)
    md += ["```json", json.dumps(run.model_dump(mode="json"), indent=2), "```", ""]
    return "\n".join(md)


__all__ = [
    "RemediationReport",
    "remediate_audit_findings",
    "run_remediation",
    "_apply_control_remediation",
    "_run_baseline_checks",
]
