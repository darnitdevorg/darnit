"""Built-in remediate tool for any framework.

Provides a generic remediation tool that works with any TOML-defined framework.
Uses the RemediationExecutor to apply file_create, exec, and api_call remediations
defined in the framework TOML.

Usage in TOML:
    [mcp.tools.remediate]
    builtin = "remediate"
    description = "Auto-fix failing controls"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("server.tools.builtin_remediate")


async def builtin_remediate(
    local_path: str = ".",
    dry_run: bool = True,
    *,
    _framework_name: str = "",
) -> str:
    """Auto-fix failing controls using TOML-defined remediations.

    Runs the audit to find failures, then for each failing control that has
    a declarative remediation config (file_create, exec, api_call), applies
    the fix using the framework's RemediationExecutor.

    Args:
        local_path: Path to the repository to remediate.
        dry_run: If True (default), show what would be done without writing.
        _framework_name: Internal - set by the factory at registration time.

    Returns:
        Markdown-formatted remediation report.
    """
    from darnit.config import (
        load_controls_from_effective,
        load_effective_config_by_name,
    )
    from darnit.config.framework_schema import FrameworkConfig
    from darnit.core.discovery import get_implementation
    from darnit.remediation.executor import RemediationExecutor
    from darnit.sieve import CheckContext, SieveOrchestrator
    from darnit.sieve.registry import get_control_registry

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"Error: Repository path not found: {repo_path}"

    if not _framework_name:
        return "Error: No framework name configured for this remediate tool."

    # Load effective config
    try:
        config = load_effective_config_by_name(_framework_name, repo_path)
    except Exception as e:
        return f"Error loading framework config '{_framework_name}': {e}"

    # Also load the raw FrameworkConfig for templates
    fw: FrameworkConfig | None = None
    impl = get_implementation(_framework_name)
    if impl and hasattr(impl, "get_framework_config_path"):
        toml_path = impl.get_framework_config_path()
        if toml_path and toml_path.exists():
            try:
                import tomllib

                with open(toml_path, "rb") as f:
                    raw = tomllib.load(f)
                fw = FrameworkConfig(**raw)
            except Exception as e:
                logger.warning(f"Failed to parse framework TOML: {e}")

    if fw is None:
        # Fall back to building FrameworkConfig from the effective config
        try:
            fw = config.framework
        except Exception:
            return "Error: Could not load framework configuration for templates."

    # Load controls
    try:
        toml_controls = load_controls_from_effective(config)
    except Exception as e:
        return f"Error loading controls: {e}"

    # Register Python controls
    if impl and hasattr(impl, "register_controls"):
        try:
            impl.register_controls()
        except Exception as e:
            logger.warning(f"Error registering Python controls: {e}")

    registry = get_control_registry()
    toml_ids = {c.control_id for c in toml_controls}
    python_controls = [
        spec for spec in registry.get_all_specs()
        if spec.control_id not in toml_ids
    ]

    all_controls = toml_controls + python_controls
    all_controls.sort(key=lambda c: c.control_id)

    if not all_controls:
        return "No controls found."

    # Build project_context for when-clause evaluation (same as audit pipeline)
    project_context: dict[str, Any] = {}
    try:
        from darnit.context.auto_detect import collect_auto_context

        project_context = collect_auto_context(str(repo_path))
    except Exception as e:
        logger.debug("Auto-detect context failed (non-fatal): %s", e)

    try:
        from darnit.config.context_storage import (
            flatten_user_context,
            load_context,
        )

        user_context = load_context(str(repo_path))
        if user_context:
            project_context.update(flatten_user_context(user_context))
    except Exception as e:
        logger.debug("User context load failed (non-fatal): %s", e)

    # Determine which controls failed — use cached audit results if available
    from darnit.core.audit_cache import invalidate_audit_cache, read_audit_cache
    from darnit.core.utils import detect_owner_repo

    owner, repo = detect_owner_repo(str(repo_path))
    failed_ids: set[str] = set()

    cache = read_audit_cache(str(repo_path))
    if cache is not None:
        # Cache hit — extract failed IDs without re-running the audit
        logger.info("Using cached audit results (skipping redundant audit)")
        failed_ids = {
            r["id"] for r in cache["results"] if r.get("status") == "FAIL"
        }
    else:
        # Cache miss — run inline audit (existing behavior)
        logger.info("No cached audit results, running audit")
        orchestrator = SieveOrchestrator()
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
                project_context=dict(project_context),
            )
            result = orchestrator.verify(control, context)
            if result.status == "FAIL":
                failed_ids.add(control.control_id)

    if not failed_ids:
        return "All controls pass — nothing to remediate."

    # Set up executor with templates from TOML
    executor = RemediationExecutor(
        local_path=str(repo_path),
        owner=owner,
        repo=repo,
        templates=fw.templates,
    )

    # Apply remediations for each failed control
    remediation_results = []
    skipped: list[tuple[str, str]] = []

    for control_id in sorted(failed_ids):
        control_cfg = fw.controls.get(control_id)
        if not control_cfg or not control_cfg.remediation:
            skipped.append((control_id, "no remediation defined"))
            continue

        # Skip remediation if when clause doesn't match the environment
        when_clause = getattr(control_cfg, "when", None)
        if when_clause:
            from darnit.sieve.orchestrator import evaluate_when_clause

            if not evaluate_when_clause(when_clause, project_context):
                skipped.append((control_id, f"N/A (when: {when_clause})"))
                continue

        rem_cfg = control_cfg.remediation

        # Only apply declarative remediations (file_create, exec, api_call)
        has_declarative = rem_cfg.file_create or rem_cfg.exec or rem_cfg.api_call
        if not has_declarative:
            if rem_cfg.handler:
                skipped.append((control_id, f"handler-only remediation: {rem_cfg.handler}"))
            else:
                skipped.append((control_id, "no declarative remediation"))
            continue

        result = executor.execute(control_id, rem_cfg, dry_run=dry_run)
        remediation_results.append(result)

        # Apply project_update if the remediation succeeded and has one
        if result.success and not dry_run and rem_cfg.project_update:
            _apply_project_update(
                str(repo_path), rem_cfg.project_update, control_id
            )

    # Invalidate cache after applying changes (not dry-run)
    if not dry_run and remediation_results:
        try:
            invalidate_audit_cache(str(repo_path))
        except Exception as exc:
            logger.warning("Failed to invalidate audit cache: %s", exc)

    return _format_remediation_report(
        framework_name=_framework_name,
        repo_path=str(repo_path),
        dry_run=dry_run,
        results=remediation_results,
        skipped=skipped,
    )



def _apply_project_update(
    local_path: str,
    project_update: Any,
    control_id: str,
) -> None:
    """Apply project_update after successful remediation.

    Updates .project/project.yaml with the values specified in
    the project_update config.
    """
    from darnit.remediation.executor import apply_project_update

    try:
        apply_project_update(local_path, project_update, control_id)
    except Exception as e:
        logger.warning(
            f"Failed to apply project_update for {control_id}: {e}"
        )


def _format_remediation_report(
    framework_name: str,
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
    lines.append(f"# {framework_name} Remediation Report ({mode})")
    lines.append("")
    lines.append(f"**Path:** {repo_path}")
    lines.append("")

    if succeeded:
        verb = "Would create/fix" if dry_run else "Created/fixed"
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
        lines.append("Run the audit tool to verify the fixes.")
        lines.append("")

    if dry_run and succeeded:
        lines.append("Run with `dry_run=false` to apply these changes.")
        lines.append("")

    return "\n".join(lines)


__all__ = ["builtin_remediate"]
