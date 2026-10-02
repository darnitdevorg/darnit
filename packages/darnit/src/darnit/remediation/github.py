"""GitHub API remediation actions.

This module contains functions that use the GitHub API to configure
repository settings like branch protection rules. Every write goes through
the platform engine (``darnit.remediation.platform``, feature 043).
"""

import json
import os
from typing import Any

from darnit.core.logging import get_logger
from darnit.core.utils import detect_repo_from_git

logger = get_logger("remediation.github")


def detect_workflow_checks(local_path: str) -> list[dict[str, Any]]:
    """
    Detect potential status check names from GitHub Actions workflows.

    Args:
        local_path: Path to the repository

    Returns:
        A list of dicts with job info including workflow, job_id, job_name,
        check_name, and source filename.
    """
    workflow_dir = os.path.join(local_path, ".github", "workflows")
    checks = []

    if not os.path.exists(workflow_dir):
        return checks

    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not available for workflow detection")
        return checks

    try:
        filenames = os.listdir(workflow_dir)
    except OSError as e:
        logger.debug(f"Cannot read workflow directory: {e}")
        return checks

    for filename in filenames:
        if not filename.endswith(('.yml', '.yaml')):
            continue

        filepath = os.path.join(workflow_dir, filename)
        try:
            with open(filepath, encoding='utf-8') as f:
                content = f.read()

            workflow = yaml.safe_load(content)
            if workflow and isinstance(workflow, dict):
                workflow_name = workflow.get('name', filename.replace('.yml', '').replace('.yaml', ''))
                jobs = workflow.get('jobs', {})

                for job_id, job_config in jobs.items():
                    if isinstance(job_config, dict):
                        job_name = job_config.get('name', job_id)
                        # Check for matrix builds
                        strategy = job_config.get('strategy', {})
                        matrix = strategy.get('matrix', {})

                        if matrix:
                            # Expand matrix combinations for common patterns
                            for _key, values in matrix.items():
                                if isinstance(values, list):
                                    for val in values:
                                        checks.append({
                                            'workflow': workflow_name,
                                            'job_id': job_id,
                                            'job_name': job_name,
                                            'check_name': f"{job_name} ({val})",
                                            'source': filename
                                        })
                        else:
                            checks.append({
                                'workflow': workflow_name,
                                'job_id': job_id,
                                'job_name': job_name,
                                'check_name': job_name,
                                'source': filename
                            })
        except OSError as e:
            logger.debug(f"Cannot read workflow file {filename}: {e}")
            continue
        except yaml.YAMLError as e:
            logger.debug(f"Invalid YAML in {filename}: {e}")
            continue

    return checks


TOOL_STEP = "enable_branch_protection"


def _requirements(
    *,
    required_approvals: int,
    enforce_admins: bool,
    require_pull_request: bool,
    require_status_checks: bool,
    status_checks: list[str] | None,
    prevent_deletion: bool,
    prevent_force_push: bool,
) -> dict[str, Any]:
    """The tool's parameters as ``branch_protection`` requirements; a false flag requires nothing."""
    require: dict[str, Any] = {}
    if require_pull_request:
        require["require_pull_request"] = True
        if required_approvals >= 1:
            require["require_approvals"] = required_approvals
    if prevent_deletion:
        require["prevent_deletion"] = True
    if prevent_force_push:
        require["prevent_force_push"] = True
    if enforce_admins:
        require["enforce_admins"] = True
    if require_status_checks and status_checks:
        require["require_status_checks"] = list(status_checks)
    return require


def _change_lines(change_set: Any) -> list[str]:
    from darnit.remediation.platform.policy import describe_change_set

    return describe_change_set(change_set)


def enable_branch_protection(
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
    required_approvals: int = 1,
    enforce_admins: bool = True,
    require_pull_request: bool = True,
    require_status_checks: bool = False,
    status_checks: list[str] | None = None,
    local_path: str = ".",
    dry_run: bool = True,
    approve: str | list[str] | None = None,
    prevent_deletion: bool = True,
    prevent_force_push: bool = True,
) -> str:
    """Require branch protection settings through the platform engine (feature 043, framework-design 4.5).

    The parameters become ``branch_protection`` requirements. Each only
    tightens: an existing approval count is never lowered, existing status
    checks are never removed, and a false flag requires nothing (it never
    turns an existing setting off). The engine reads the current protection
    and any active rulesets, and plans only what is missing.

    By default this previews and changes nothing. With ``dry_run=False`` the
    change is applied as the operator's remediation policy allows: under
    ``prompt`` (the default) only when ``approve`` names the digest of the
    change set the person approved, and the current settings still match the
    preview; under ``manual`` never; under ``auto`` without a digest. The
    outcome comes from reading the settings back.

    Args:
        owner: GitHub org/user (auto-detected from git if not provided)
        repo: Repository name (auto-detected from git if not provided)
        branch: Branch to protect (default: the repository's default branch)
        required_approvals: Minimum number of approving reviews (default: 1)
        enforce_admins: Require the rules to apply to administrators (default: True)
        require_pull_request: Require pull requests before merging (default: True)
        require_status_checks: Require ``status_checks`` to pass (default: False)
        status_checks: Status-check contexts to add to the required ones
        local_path: Local path to the repository (default: ".")
        dry_run: Preview only (default: True)
        approve: Digest(s) of the previewed change set the person approved
        prevent_deletion: Require that the branch cannot be deleted (default: True)
        prevent_force_push: Require that force pushes are rejected (default: True)

    Returns:
        A Markdown report followed by a fenced JSON block holding the
        ``RemediationRun`` (framework-design 15.4).
    """
    from darnit.config.operator.loader import OperatorConfigError
    from darnit.remediation import manifest
    from darnit.remediation.plan import PlanItem, RemediationOutcome, RemediationRun
    from darnit.remediation.platform import PlatformRequirement, apply, plan, platform_repository, resolve_policy

    if not owner or not repo:
        detected = detect_repo_from_git(local_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
    repository = platform_repository(local_path, owner, repo)
    if repository is None:
        return "Error: could not determine the repository (pass owner and repo)."

    require = _requirements(
        required_approvals=required_approvals,
        enforce_admins=enforce_admins,
        require_pull_request=require_pull_request,
        require_status_checks=require_status_checks,
        status_checks=status_checks,
        prevent_deletion=prevent_deletion,
        prevent_force_push=prevent_force_push,
    )
    if not require:
        return "Nothing to require: every branch protection parameter is off."
    try:
        request = PlatformRequirement(target="branch_protection", require=require, branch=branch)
        policy = resolve_policy(local_path)
    except (ValueError, OperatorConfigError) as e:
        return f"Error: {e}"

    run_id = manifest.new_run_id()
    settings = policy.settings
    lines = [
        f"# Branch protection {'preview' if dry_run else 'apply'} for {repository}",
        "",
        f"- Run: {run_id}",
        f"- Policy: platform={settings.platform}, high_impact={settings.high_impact}",
        "- Requirements: " + ", ".join(f"{k}={v}" for k, v in require.items()),
        "",
    ]

    if dry_run:
        [planned] = plan(repository, [request])
        change_sets = [planned.change_set.model_dump(mode="json")] if planned.change_set else []
        item = PlanItem(control_id=TOOL_STEP, step="platform_setting[0]", change_sets=change_sets, previewable=True)
        run = RemediationRun(
            run_id=run_id,
            repository=repository,
            mode="preview",
            policy=settings,
            operator_config_digest=policy.operator_config_digest,
            plan=[item],
        )
        if planned.error is not None:
            lines.append(f"Cannot plan: {planned.error.cause} ({planned.error.error_class}). Nothing was written.")
        elif not planned.supported:
            lines += ["Manual steps (no platform call was made):", *(f"- {step}" for step in planned.steps)]
        elif planned.change_set is not None and not planned.change_set.operations:
            lines.append(f"Already satisfied ({planned.change_set.satisfied_by}); nothing to change.")
        elif planned.change_set is not None:
            lines += ["## Planned change", "", *_change_lines(planned.change_set), ""]
            lines.append(
                "Nothing was changed. To apply, show this change to the person and, if they approve it, "
                f'call again with dry_run=False and approve="{planned.change_set.digest}".'
            )
        return "\n".join(lines) + "\n\n```json\n" + json.dumps(run.model_dump(mode="json"), indent=2) + "\n```\n"

    approvals = [approve] if isinstance(approve, str) else list(approve or [])
    [result] = apply(repository, [request], policy=policy, approvals=approvals)
    change_set = result.change_set
    wrote = change_set is not None and (result.kind == "applied" or bool(result.changed))
    if wrote:
        assert change_set is not None
        manifest.start_run(repository, checkout=local_path, run_id=run_id)
        manifest.record_change_set(repository, run_id, change_set.digest, checkout=local_path)

    shown_sets = [change_set.model_dump(mode="json")] if change_set is not None else []
    if result.kind == "applied":
        outcome = RemediationOutcome(
            control_id=TOOL_STEP,
            kind="fixed",
            change_sets=shown_sets,
            recheck={"status": "PASS", "method": "read_back"},
        )
        lines += ["Applied. The read-back satisfies every requirement and shows changed:", ""]
        lines += [f"- {c.field}: {c.before} -> {c.after}" for c in result.changed]
    elif result.kind == "error":
        assert result.error is not None
        outcome = RemediationOutcome(
            control_id=TOOL_STEP, kind="error", change_sets=shown_sets, error=result.error
        )
        lines.append(f"Error ({result.error.error_class}): {result.error.cause}")
        if result.changed:
            lines += ["Changed before the error (from the read-back):", *(f"- {c.field}" for c in result.changed)]
    else:
        reason = result.reason
        if result.kind == "manual":
            reason = f"{result.reason}: " + " | ".join(result.steps)
            lines += ["Manual steps (darnit made no change):", *(f"- {step}" for step in result.steps)]
        elif result.kind == "needs_approval":
            lines += ["Needs approval; nothing was written.", "", *(_change_lines(change_set) if change_set else [])]
        elif result.reason == "stale_preview":
            lines.append("The settings changed since the preview; nothing was written. Preview again.")
        else:
            lines.append(f"Already satisfied ({result.reason}); nothing was written.")
        outcome = RemediationOutcome(control_id=TOOL_STEP, kind=result.kind, change_sets=shown_sets, reason=reason)

    run = RemediationRun(
        run_id=run_id,
        repository=repository,
        mode="apply",
        policy=settings,
        operator_config_digest=policy.operator_config_digest,
        approvals=[result.approval] if result.approval else [],
        outcomes=[outcome],
    )
    logger.info("enable_branch_protection %s: %s", repository, result.kind)
    return "\n".join(lines) + "\n\n```json\n" + json.dumps(run.model_dump(mode="json"), indent=2) + "\n```\n"


__all__ = [
    "detect_workflow_checks",
    "enable_branch_protection",
]
