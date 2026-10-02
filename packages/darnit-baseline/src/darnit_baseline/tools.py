"""MCP tool handlers for OpenSSF Baseline.

This module provides standalone tool functions that can be registered
with the darnit MCP server via TOML configuration.

Each function is designed to be used as an MCP tool handler.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

# OSPS control-ID-to-tool mapping for audit report remediation suggestions.
# This keeps all OSPS-specific knowledge in the implementation package.
OSPS_REMEDIATION_MAP: dict = {
    "groups": [
        {
            "name": "Branch Protection",
            "tool": "enable_branch_protection",
            "description": "Configure branch protection rules",
            "control_ids": {"OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-QA-07.01", "OSPS-QA-03.01"},
        },
        {
            "name": "Security Policy",
            "tool": "create_security_policy",
            "description": "Generate SECURITY.md with vulnerability reporting",
            "control_ids": {"OSPS-VM-01.01", "OSPS-VM-02.01", "OSPS-VM-03.01"},
        },
    ],
    "bulk_tool": "remediate_audit_findings",
    "bulk_description": "Auto-fix multiple compliance issues at once",
    "branch_name": "fix/openssf-baseline",
    "framework_name": "OpenSSF Baseline",
}


def _compact_result(r: dict[str, Any]) -> dict[str, Any]:
    """Reduce one check result to the `summary` output shape.

    Drops evidence and pass_history (~5-8K vs ~164K for 62 controls) but
    keeps ``error_class`` when present. Feature 036: a summary that hides
    "we could not verify" is worse than no summary -- a consumer would
    read an unreachable network as a real compliance failure.
    """
    compact: dict[str, Any] = {
        "id": r.get("id"),
        "status": r.get("status"),
        "level": r.get("level"),
        "details": r.get("details", ""),
    }
    if r.get("error_class") is not None:
        compact["error_class"] = r["error_class"]
    if r.get("assertion") is not None:
        compact["assertion"] = r["assertion"]
    return compact


def _build_audit_result(
    owner: str,
    repo: str,
    repo_path: Path,
    level: int,
    default_branch: str,
    results: list[dict],
    summary: dict[str, int],
    level_compliance: dict[int, bool],
):
    """Assemble an AuditResult from sieve audit output for SARIF/attestation."""
    from darnit.core.models import AuditResult
    from darnit_baseline.attestation import get_git_commit, get_git_ref

    return AuditResult(
        owner=owner,
        repo=repo,
        local_path=str(repo_path),
        level=level,
        default_branch=default_branch,
        all_results=results,
        summary=summary,
        level_compliance=level_compliance,
        commit=get_git_commit(str(repo_path)),
        ref=get_git_ref(str(repo_path)),
    )


def audit_openssf_baseline(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    level: int = 3,
    tags: str | list[str] | None = None,
    output_format: str = "markdown",
    auto_init_config: bool = True,
    attest: bool = False,
    sign_attestation: bool = True,
    staging: bool = False,
    prefer_upstream: bool = False,
    profile: str | None = None,
    project_url: str | None = None,
    host: str | None = None,
) -> str:
    """
    Run a comprehensive OpenSSF Baseline audit on a repository.

    This checks compliance with OSPS v2025.10.10 across 62 controls at 3 maturity levels.

    Args:
        owner: GitHub Org/User (auto-detected from git if not provided)
        repo: Repository Name (auto-detected from git if not provided)
        local_path: ABSOLUTE path to repo (e.g., "/Users/you/projects/repo")
        level: Maximum OSPS level to check (1, 2, or 3). Default: 3
        tags: Filter controls by tags. Can be a string or list of strings.
              Examples: "domain=AC", ["domain=AC", "level=1"], "priority=low,priority=high"
              - Different fields use AND logic: domain=AC AND level=1
              - Same field repeated uses OR logic: priority=low OR priority=high
              - Bare values match against control tags dict keys
        output_format: Output format - "markdown", "json", "summary", "sarif", or "badge".
              Default: "markdown".
              Use "summary" for compact JSON (id/status/level/details only, no evidence).
              Use "badge" to generate an OpenSSF Best Practices Badge automation-proposal URL.
        auto_init_config: Create .project.yaml if missing. Default: True
        attest: Generate in-toto attestation after audit. Default: False
        sign_attestation: Sign attestation with Sigstore. Default: True
        staging: Use Sigstore staging environment. Default: False
        prefer_upstream: If True, prefer 'upstream' git remote when auto-detecting owner/repo.
                         Default: False. Auto-detected owner/repo never make a repository trusted.
        profile: Optional audit profile name to filter controls. Short name (e.g., "level1_quick")
                 or qualified name (e.g., "openssf-baseline:level1_quick"). Default: None (all controls)
        project_url: Canonical repository URL for the Best Practices Badge submission
                     (e.g. "https://github.com/curl/curl"). Auto-detected from git when omitted.
                     Only used when output_format="badge".
        host: Git host of owner/repo (default github.com). owner, repo, and host
              name the repository whose trust is decided from operator configuration.

    Returns:
        Formatted audit report with compliance status and remediation instructions
    """
    from darnit.config import (
        load_controls_from_effective,
        load_effective_config_by_name,
    )
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.server.factory import registration_scope_warning
    from darnit.tools.audit import (
        audit_report_metadata,
        calculate_compliance,
        format_results_markdown,
        run_sieve_audit,
    )

    # Resolve path
    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    try:
        operator_config = resolve_operator_config(repo_path)
    except OperatorConfigError as e:
        return f"Error: {e}"

    from darnit.trust.decision import target_from_owner_repo

    target = target_from_owner_repo(owner, repo, host)

    # Auto-detect owner/repo from git (origin first)
    from darnit.core.utils import detect_owner_repo

    detected_owner, detected_repo = detect_owner_repo(
        str(repo_path), prefer_upstream=prefer_upstream
    )
    owner = owner or detected_owner
    repo = repo or detected_repo

    # Load framework config
    try:
        config = load_effective_config_by_name("openssf-baseline", repo_path, operator=operator_config.config)
    except Exception as e:
        return f"❌ Error loading framework: {e}"

    # Load controls filtered by level
    controls = load_controls_from_effective(config)
    controls = [c for c in controls if c.level <= level]

    # Apply profile filtering if specified
    if profile:
        from darnit.config.profile_resolver import (
            ProfileAmbiguousError,
            ProfileNotFoundError,
            resolve_profile,
            resolve_profile_control_ids,
        )

        try:
            # Build implementations dict from loaded config
            profile_impls: dict = {}
            if config._framework_config and config._framework_config.audit_profiles:
                profile_impls[config.framework_name] = config._framework_config.audit_profiles
            _, profile_config = resolve_profile(profile, profile_impls)
            profile_ids = resolve_profile_control_ids(profile_config, controls)
            controls = [c for c in controls if c.control_id in profile_ids]
        except (ProfileNotFoundError, ProfileAmbiguousError) as e:
            return f"❌ {e}"

    if not controls:
        return "❌ No controls loaded"

    # Normalize tags
    tags_list: list[str] | None = None
    if tags:
        if isinstance(tags, str):
            tags_list = [tags]
        else:
            tags_list = list(tags)

    default_branch = _detect_default_branch(repo_path)

    # Delegate to canonical audit pipeline
    results, summary = run_sieve_audit(
        owner=owner,
        repo=repo,
        local_path=str(repo_path),
        default_branch=default_branch,
        level=level,
        controls=controls,
        tags=tags_list,
        apply_user_config=True,
        stop_on_llm=True,
        framework_name="openssf-baseline",
        operator_config=operator_config,
        target=target,
    )

    metadata = audit_report_metadata(operator_config, str(repo_path), target, "openssf-baseline")
    warning = registration_scope_warning(repo_path)
    if warning:
        metadata.setdefault("warnings", []).append(warning)

    # Format output
    if output_format == "badge":
        from .formatters.badge import generate_badge_url

        # Resolve project URL: explicit arg > auto-detected from git remote
        resolved_project_url = project_url or ""
        if not resolved_project_url and owner and repo:
            resolved_project_url = f"https://github.com/{owner}/{repo}"

        return generate_badge_url(results, resolved_project_url)
    elif output_format == "summary":
        # Compact JSON: only id/status/level/details — no evidence or pass_history.
        # ~5-8K vs ~164K for full JSON with 62 controls.
        from darnit.tools.audit import framework_metadata

        compact_results = [_compact_result(r) for r in results]
        output = json.dumps({
            "metadata": framework_metadata("openssf-baseline"),
            **metadata,
            "owner": owner,
            "repo": repo,
            "level": level,
            "summary": summary,
            "results": compact_results,
        }, indent=2)
    elif output_format == "json":
        from darnit.tools.audit import framework_metadata

        output = json.dumps({
            "metadata": framework_metadata("openssf-baseline"),
            **metadata,
            "owner": owner,
            "repo": repo,
            "level": level,
            "summary": summary,
            "results": results,
        }, indent=2)
    elif output_format == "sarif":
        from darnit_baseline.formatters.sarif import generate_sarif_audit

        compliance = calculate_compliance(results, level)
        audit_result = _build_audit_result(
            owner or "", repo or "", repo_path, level,
            default_branch, results, summary, compliance,
        )
        output = json.dumps(generate_sarif_audit(audit_result), indent=2)
    else:
        compliance = calculate_compliance(results, level)
        output = format_results_markdown(
            owner=owner,
            repo=repo,
            results=results,
            summary=summary,
            compliance=compliance,
            level=level,
            local_path=str(repo_path),
            report_title="OpenSSF Baseline Audit Report",
            remediation_map=OSPS_REMEDIATION_MAP,
            framework_name="openssf-baseline",
            audit_metadata=metadata,
        )

    if attest:
        attest_note = _attest_audit(
            owner, repo, repo_path, level, default_branch,
            results, summary, sign=sign_attestation, staging=staging,
            trust=metadata["trust"],
        )
        # Only markdown output can carry the note without breaking the
        # format; for JSON/SARIF the attestation file is still written.
        if output_format not in ("summary", "json", "sarif"):
            output += f"\n\n## Attestation\n\n{attest_note}\n"

    return output


def _attest_audit(
    owner: str | None,
    repo: str | None,
    repo_path: Path,
    level: int,
    default_branch: str,
    results: list[dict],
    summary: dict[str, int],
    *,
    sign: bool,
    staging: bool,
    trust: dict | None = None,
) -> str:
    """Generate an attestation from completed audit results.

    Returns a one-line status message suitable for embedding in a report.
    """
    if not owner or not repo:
        return "❌ Attestation skipped: owner/repo could not be determined."

    try:
        from darnit.tools.audit import calculate_compliance
        from darnit_baseline.attestation import generate_attestation_from_results

        compliance = calculate_compliance(results, level)
        audit_result = _build_audit_result(
            owner, repo, repo_path, level, default_branch,
            results, summary, compliance,
        )
        audit_result.trust = trust
        message = generate_attestation_from_results(
            audit_result, sign=sign, staging=staging,
        )
        first_line = message.splitlines()[0] if message else ""
        return first_line if first_line.startswith("✅") else message
    except Exception as e:
        return f"❌ Attestation failed: {e}"


def list_available_checks(profile: str | None = None) -> str:
    """
    List all available OpenSSF Baseline checks organized by level.

    Args:
        profile: Optional audit profile name to filter controls.

    Returns:
        Formatted list of OSPS controls across 3 levels
    """
    from darnit.config.merger import load_framework_by_name

    config = load_framework_by_name("openssf-baseline")

    # Resolve profile filter if specified
    profile_ids: set[str] | None = None
    if profile and config.audit_profiles:
        from darnit.config.control_loader import load_controls_from_framework
        from darnit.config.profile_resolver import (
            resolve_profile,
            resolve_profile_control_ids,
        )

        try:
            _, profile_config = resolve_profile(
                profile, {"openssf-baseline": config.audit_profiles}
            )
            controls = load_controls_from_framework(config)
            profile_ids = set(resolve_profile_control_ids(profile_config, controls))
        except Exception:
            profile_ids = None

    checks: dict[str, list] = {"level1": [], "level2": [], "level3": []}

    for control_id, control in config.controls.items():
        if profile_ids is not None and control_id not in profile_ids:
            continue
        level = control.tags.get("level", 1) if control.tags else 1
        level_key = f"level{level}"
        if level_key in checks:
            checks[level_key].append({
                "id": control_id,
                "name": control.name,
                "description": control.description[:100] if control.description else "",
            })

    return json.dumps(checks, indent=2)


def get_project_config(local_path: str = ".") -> str:
    """
    Get the current project configuration for OpenSSF Baseline.

    Returns the .project.yaml configuration which contains ONLY:
    - Project metadata (name, type)
    - File location pointers
    - Control overrides with reasoning
    - CI/CD configuration references

    Args:
        local_path: Path to repository

    Returns:
        Current configuration or instructions to create one
    """
    from darnit.config import config_exists
    from darnit.config import get_project_config as _get_config

    repo_path = Path(local_path).resolve()

    if not config_exists(repo_path):
        return (
            "No .project.yaml found.\n\n"
            "To create one, use: init_project_config()\n"
            "Or run: darnit init"
        )

    try:
        config = _get_config(repo_path)
        # Convert to dict for JSON output
        config_dict = config.model_dump(exclude_none=True, exclude_unset=True)
        return json.dumps(config_dict, indent=2, default=str)
    except Exception as e:
        return f"❌ Error reading config: {e}"


def create_security_policy(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    template: str = "standard",
) -> str:
    """
    Create a SECURITY.md file for vulnerability reporting.

    Satisfies: OSPS-VM-01.01, OSPS-VM-02.01, OSPS-VM-03.01

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository
        template: Template to use (standard, minimal, enterprise)

    Returns:
        Success message with created file path
    """
    from darnit.config import load_effective_config_by_name
    from darnit.config.framework_schema import FrameworkConfig
    from darnit.remediation.executor import RemediationExecutor

    repo_path = Path(local_path).resolve()

    # Auto-detect owner/repo
    from darnit.core.utils import detect_owner_repo

    detected_owner, detected_repo = detect_owner_repo(str(repo_path))
    owner = owner or detected_owner
    repo = repo or detected_repo

    try:
        # Load framework config to get SECURITY.md remediation definition
        config = load_effective_config_by_name("openssf-baseline", repo_path)
        framework = FrameworkConfig(**config)

        # Use the TOML-defined remediation for OSPS-VM-02.01 (security policy)
        control = framework.controls.get("OSPS-VM-02.01")
        if not control or not control.remediation:
            return "❌ No remediation config found for OSPS-VM-02.01"

        fw_path = None
        try:
            from darnit_baseline import get_framework_path
            p = get_framework_path()
            if p:
                fw_path = str(p)
        except Exception:
            pass

        from darnit.config.context_resolve import resolve_context
        from darnit.config.context_storage import framework_definitions

        resolved = resolve_context(str(repo_path), framework_definitions(framework), detect=False)
        executor = RemediationExecutor(
            local_path=str(repo_path),
            owner=owner,
            repo=repo,
            templates=framework.templates or {},
            context_values=resolved.usable(),
            framework_path=fw_path,
            unconfirmed_keys=resolved.unusable_keys(),
        )

        result = executor.execute(
            control_id="OSPS-VM-02.01",
            config=control.remediation,
            dry_run=False,
        )

        if result.confirmation_required:
            return (
                f"Error: SECURITY.md was not created: {result.message}. Ask the person for "
                f"`{result.confirmation_required}` and record their answer with confirm_project_data."
            )
        if result.success:
            return f"✅ Created SECURITY.md at {repo_path}/SECURITY.md"
        else:
            return f"❌ Error creating SECURITY.md: {result.message}"
    except Exception as e:
        return f"❌ Error creating SECURITY.md: {e}"


def enable_branch_protection(
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
    required_approvals: int = 1,
    enforce_admins: bool = True,
    require_pull_request: bool = True,
    require_status_checks: bool = False,
    status_checks: list | None = None,
    local_path: str = ".",
    dry_run: bool = True,
    approve: str | None = None,
    prevent_deletion: bool = True,
    prevent_force_push: bool = True,
) -> str:
    """
    Require branch protection settings; previews unless asked to apply.

    Satisfies: OSPS-AC-03.01, OSPS-AC-03.02, OSPS-QA-07.01

    Reads the current protection and active rulesets and plans only the
    missing settings. It never lowers an existing approval count, never
    removes a status check, and never turns an existing setting off. The
    default call changes nothing and returns the planned change with its
    digest. Show that change to the person; only if they approve it, call
    again with ``dry_run=False`` and ``approve`` set to that digest. Passing
    ``dry_run=False`` alone is not an approval.

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        branch: Branch to protect (default: the repository's default branch)
        required_approvals: Minimum number of required PR approvals (default: 1)
        enforce_admins: Require the rules to apply to admins too (default: True)
        require_pull_request: Require PRs for changes (default: True)
        require_status_checks: Require ``status_checks`` to pass (default: False)
        status_checks: Status check contexts to add to the required ones
        local_path: Path to repository for auto-detection
        dry_run: Preview only (default: True)
        approve: Digest of the previewed change set the person approved
        prevent_deletion: Require that the branch cannot be deleted (default: True)
        prevent_force_push: Require that force pushes are rejected (default: True)

    Returns:
        Markdown report followed by a fenced JSON block with the run record
    """
    from darnit.core.utils import detect_owner_repo
    from darnit.remediation.github import enable_branch_protection as _enable

    repo_path = Path(local_path).resolve()
    detected_owner, detected_repo = detect_owner_repo(str(repo_path), owner=owner, repo=repo)
    try:
        return _enable(
            owner=owner or detected_owner or None,
            repo=repo or detected_repo or None,
            branch=branch,
            required_approvals=required_approvals,
            enforce_admins=enforce_admins,
            require_pull_request=require_pull_request,
            require_status_checks=require_status_checks,
            status_checks=status_checks or [],
            local_path=str(repo_path),
            dry_run=dry_run,
            approve=approve,
            prevent_deletion=prevent_deletion,
            prevent_force_push=prevent_force_push,
        )
    except Exception as e:
        return f"Error configuring branch protection: {e}"


# =============================================================================
# Configuration Tools
# =============================================================================


def init_project_config(local_path: str = ".") -> str:
    """
    Create an empty .project/darnit.yaml when the repository has no .project/ directory.

    Nothing is detected or pre-filled: project values are recorded only when a
    person confirms them with confirm_project_data(). An existing .project/
    directory is reported, never overwritten.

    Args:
        local_path: Path to repository

    Returns:
        What was created, or why nothing was
    """
    from darnit.config.context_writes import create_extension_file

    repo_path = Path(local_path).resolve()
    project_dir = repo_path / ".project"
    if project_dir.exists():
        present = sorted(p.name for p in project_dir.iterdir()) if project_dir.is_dir() else []
        return (
            f"{project_dir} already exists ({', '.join(present) or 'empty'}); nothing was changed. "
            "Use get_project_config() to view it."
        )

    try:
        result = create_extension_file(str(repo_path))
    except OSError as e:
        return f"Error creating {project_dir / 'darnit.yaml'}: {e}"
    return f"Created an empty {repo_path / result.file}"


def confirm_project_data(
    local_path: str = ".",
    *,
    accept_candidates: dict[str, str] | None = None,
    confirm_stored: list[str] | None = None,
    reject_stored: list[str] | None = None,
    expires_at: dict[str, str] | None = None,
    confirm_not_applicable: list[str] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    host: str | None = None,
    confirm_pass_candidate: list[str] | None = None,
    **values: Any,
) -> str:
    """
    Record a person's confirmation of project data values.

    Only on the person's explicit instruction. Values are recorded in
    .project/darnit.yaml when the operator trusts the repository named by
    `owner`/`repo` (and `host`), otherwise operator-side; without them,
    values are refused.

    **Parameters:**
    - `local_path`: Path to repository (default: ".")
    - `owner`, `repo`, `host`: The repository the values or claims are for (required)
    - One parameter per context key OpenSSF Baseline defines (for example
      `maintainers`, `governance_model`, `platform`): the person's answer.
      Enum keys accept only their allowed values.
    - `accept_candidates`: `{key: candidate digest}` for candidates
      get_pending_data showed the person and the person accepted. A candidate
      is confirmed only if its digest still matches, and its value and origin
      are recorded as the basis.
    - `confirm_stored` / `reject_stored`: keys from get_pending_data's
      `stored_unconfirmed` list whose stored value the person confirms or
      rejects. A rejected .project/darnit.yaml value is deleted (trusted
      repository only); a .project/project.yaml value is reported with the
      field to edit and left unchanged.
    - `expires_at`: `{key: date}` optional expiry recorded with a key's confirmation.
    - `confirm_not_applicable`: Control IDs whose pending not-applicable claim the
      operator confirms. Only on the operator's explicit instruction.
    - `confirm_pass_candidate`: Control IDs whose PASS candidate (a positive model
      judgment awaiting confirmation) the operator confirms for the current
      evidence. Only on the operator's explicit instruction.

    Returns:
        What was recorded or refused, per key
    """
    from darnit.server.tools.project_data import confirm_project_data_impl

    return confirm_project_data_impl(
        local_path=local_path,
        accept_candidates=accept_candidates,
        confirm_stored=confirm_stored,
        reject_stored=reject_stored,
        expires_at=expires_at,
        confirm_not_applicable=confirm_not_applicable,
        owner=owner,
        repo=repo,
        host=host,
        framework_name=_FRAMEWORK_NAME,
        confirm_pass_candidate=confirm_pass_candidate,
        **values,
    )


def confirm_project_data_tool():
    """``confirm_project_data`` with a parameter for every context key OpenSSF Baseline defines."""
    from darnit.server.tools.project_data import confirmable_definitions, with_context_parameters

    return with_context_parameters(confirm_project_data, confirmable_definitions(_FRAMEWORK_NAME))


_FRAMEWORK_NAME = "openssf-baseline"
_SELECTOR_OPTION_LIMIT = 4


@functools.cache
def _context_key_order() -> list[str]:
    """This framework's context keys in TOML definition order, for a stable question order."""
    from darnit.config.merger import load_framework_by_name

    try:
        return list(load_framework_by_name(_FRAMEWORK_NAME).context.definitions)
    except (ValueError, OSError):
        return []


_LLM_DIRECTIVE_PREFIX = """MANDATORY: Your next action MUST be calling the AskUserQuestion tool.

For every question in "questions" that has a "candidate", first show the person its
candidate.value and candidate.origin, labelled UNCONFIRMED. Then pass "ask_user_batch"
below verbatim as the "questions" parameter to AskUserQuestion. Do NOT paraphrase, do NOT
pre-select answers, and do NOT add options. A question in "questions" with no entry in
"ask_user_batch" (free text, or more allowed values than the selector holds) is asked
after that, listing every value in its "allowed_values"; never offer its "format_hint"
as an answer.

After the person answers, call confirm_project_data() once for the batch, with owner and
repo (and host when not github.com) naming the repository. Use "answer_mapping":
- "Yes" / "No" on a yes/no question -> pass true / false (not strings)
- A selected option label -> pass the label as a string
- "Yes" on a candidate question -> accept_candidates, mapping the key to that question's
  candidate.digest; fill in the digest only now, after the person answered Yes
- "No" on a candidate question, or "Other" -> pass the value the person typed
Never type a detected value as an answer. Then call get_pending_data() again for the
next batch (if any remain).

---
"""


def get_pending_data(
    local_path: str = ".",
    control_ids: list[str] | None = None,
    level: int = 3,
    owner: str | None = None,
    repo: str | None = None,
    limit: int = 4,
    _tool_config: dict | None = None,
    profile: str | None = None,
) -> str:
    """Get data values that would improve audit accuracy. Writes nothing.

    Returns up to `limit` questions per call as a batch. Each question carries
    its candidate, if any, as unconfirmed data (value, origin, digest); command
    templates and answer mappings hold placeholders only.

    Workflow:
    1. Call this tool. It returns "questions" and "ask_user_batch".
    2. Show each question's candidate to the person, labelled unconfirmed, then
       call AskUserQuestion(questions=<ask_user_batch>).
    3. After the person answers, use "answer_mapping" to call confirm_project_data().
    4. Call get_pending_data() again for the next batch. Repeat until status is "complete".

    Parameters:
    - `local_path`: Path to repository (default: ".")
    - `control_ids`: Optional list of control IDs to check
    - `level`: Maximum maturity level (1, 2, or 3)
    - `owner`: GitHub owner (auto-detected if not provided)
    - `repo`: GitHub repo name (auto-detected if not provided)
    - `limit`: Max questions to return per batch (default: 4). Use 0 for all.

    Returns:
        JSON with the questions, ask_user_batch (for AskUserQuestion),
        answer_mapping for confirm_project_data, a progress indicator, and
        stored_unconfirmed: values stored in .project/ without a confirmation,
        with their locations, for review with confirm_stored / reject_stored.
    """
    from darnit.config.context_storage import get_pending_context as _get_pending
    from darnit.server.tools.project_data import stored_unconfirmed
    from darnit.trust.decision import target_from_owner_repo

    repo_path = Path(local_path).resolve()
    target = target_from_owner_repo(owner, repo)

    # Auto-detect owner/repo from git
    if owner is None or repo is None:
        from darnit.core.utils import detect_owner_repo

        detected_owner, detected_repo = detect_owner_repo(str(repo_path))
        owner = owner or detected_owner
        repo = repo or detected_repo

    try:
        pending = _get_pending(
            str(repo_path),
            control_ids=control_ids,
            owner=owner,
            repo=repo,
            target=target,
        )

        stored = stored_unconfirmed(str(repo_path), target=target)

        if not pending:
            complete: dict = {
                "status": "complete",
                "message": "All context has been confirmed. No additional input needed.",
                "questions": [],
            }
            if stored:
                complete["stored_unconfirmed"] = stored
            return json.dumps(complete, indent=2)

        total = len(pending)

        # Read config from TOML if available
        effective_limit = limit
        append_directive = True
        if _tool_config:
            effective_limit = _tool_config.get("limit", limit)
            append_directive = _tool_config.get("append_directive", True)

        questions = [_build_context_question(req) for req in pending]

        order = _context_key_order()
        questions.sort(key=lambda q: order.index(q["key"]) if q["key"] in order else len(order))

        # Apply pagination (limit=0 means return all)
        if effective_limit > 0:
            questions = questions[:effective_limit]

        batch_questions = []
        answer_mapping = []
        for q in questions:
            ask_user = q.get("ask_user")
            if ask_user is None:
                continue
            batch_questions.append(ask_user)
            mapping: dict = {
                "question_index": len(batch_questions) - 1,
                "context_key": q["key"],
            }
            if q["candidate"] is not None:
                mapping["value_map"] = {
                    "Yes": {"accept_candidates": {q["key"]: "<candidate.digest>"}},
                    "No": "ASK_USER_FOR_VALUE",
                }
            elif q["input_type"] == "select" and q.get("options") == ["true", "false"]:
                mapping["value_map"] = {"Yes": True, "No": False}
            answer_mapping.append(mapping)

        # Determine answered count from total minus pending
        answered = total - len(pending)

        response: dict = {
            "status": "pending",
            "progress": {
                "answered": answered,
                "total": total,
            },
            "questions": questions,
            "stored_unconfirmed": stored,
        }

        if batch_questions:
            response["ask_user_batch"] = batch_questions
            response["answer_mapping"] = answer_mapping

        result_json = json.dumps(response, indent=2)

        if append_directive and batch_questions:
            result = _LLM_DIRECTIVE_PREFIX + result_json
        else:
            result = result_json

        return result

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Error getting pending context: {e}",
        }, indent=2)


def _origin_text(origin: dict | None) -> str:
    if not origin:
        return "unknown origin"
    return f"{origin['kind']} ({origin['method']})" if origin.get("method") else origin["kind"]


def _build_context_question(req) -> dict:
    """A structured question for one pending context key (contract: context-confirmation-tools.md).

    A candidate is carried as data in ``candidate`` only. ``command_template``
    holds placeholders, never a candidate value or a configuration example;
    an enum lists its whole vocabulary in ``allowed_values``; examples are
    only a ``format_hint``.
    """
    from darnit.config.context_keys import vocabulary
    from darnit.config.context_resolve import candidate_payload, confirmation_template

    definition = req.definition
    candidate = candidate_payload(req.candidate)
    allowed = vocabulary(definition)

    effective_hint = definition.hint
    if definition.auto_detect and candidate is None and definition.no_detect_hint:
        effective_hint = definition.no_detect_hint

    prompt = definition.prompt
    if allowed and len(allowed) > _SELECTOR_OPTION_LIMIT:
        prompt = f"{prompt} (one of: {', '.join(allowed)})"

    question: dict = {
        "key": req.key,
        "priority": req.priority,
        "affects_controls": req.control_ids,
        "prompt": prompt,
        "candidate": candidate,
        "command_template": confirmation_template(req.key, candidate=candidate is not None),
        "allowed_values": allowed,
        "format_hint": (
            " or ".join(definition.examples)
            if definition.examples and definition.type not in ("enum", "boolean")
            else None
        ),
    }

    hint = definition.computed_presentation_hint
    if hint is not None:
        question["presentation_hint"] = hint
    if effective_hint:
        question["hint"] = effective_hint

    if candidate is not None:
        question["input_type"] = "confirm"
        question["instruction"] = (
            "Show the person the candidate's value and origin, labelled unconfirmed, and ask whether "
            "to accept it. Accept it by its digest only after the person answers yes."
        )
    elif allowed:
        question["input_type"] = "select"
        question["options"] = allowed
        question["instruction"] = "Offer every allowed value and nothing else."
    elif definition.type == "boolean":
        question["input_type"] = "select"
        question["options"] = ["true", "false"]
        question["instruction"] = "Ask yes or no. Do NOT add other options."
    else:
        question["input_type"] = "free_text"
        question["instruction"] = (
            "Ask the person to type their answer. Do NOT suggest values. Do NOT pre-fill based on "
            "repository owner, git config, or any other source. The format hint is not an answer."
        )

    ask_user = _build_ask_user_params(req.key, question, definition)
    if ask_user is not None:
        question["ask_user"] = ask_user

    return question


def _build_ask_user_params(key: str, question_dict: dict, definition) -> dict | None:
    """AskUserQuestion parameters (question/header/options/multiSelect), or None.

    None for free text and for an enum with more values than the selector
    holds, so no allowed value is dropped (FR-015). A candidate's value is
    not repeated here; the person sees it from the question's ``candidate``.
    """
    input_type = question_dict.get("input_type")
    question_text = question_dict["prompt"]

    header = key.removeprefix("has_").removeprefix("is_").replace("_", " ").title()[:12]

    if input_type == "confirm":
        return {
            "question": f"{question_text} Accept the unconfirmed candidate shown above?",
            "header": header,
            "options": [
                {
                    "label": "Yes",
                    "description": f"Accept the candidate from {_origin_text(question_dict['candidate']['origin'])}",
                },
                {"label": "No", "description": "Specify a different value"},
            ],
            "multiSelect": False,
        }

    if input_type != "select":
        return None

    if definition.type == "boolean":
        options = [
            {"label": "Yes", "description": definition.hint or "Yes, this applies"},
            {"label": "No", "description": "No, this does not apply"},
        ]
    else:
        values = question_dict["options"]
        if len(values) > _SELECTOR_OPTION_LIMIT:
            return None
        options = [{"label": str(v), "description": f"Select '{v}'"} for v in values]

    return {
        "question": question_text,
        "header": header,
        "options": options,
        "multiSelect": False,
    }


# =============================================================================
# Threat Model & Attestation Tools
# =============================================================================


def generate_threat_model(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    output_format: str = "markdown",
    output_path: str | None = None,
    detail_level: str = "detailed",
) -> str:
    """
    Generate a STRIDE-based threat model for a repository.

    Uses the tree-sitter structural discovery pipeline with optional
    Opengrep taint enrichment.

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: ABSOLUTE path to repo
        output_format: Output format - "markdown", "sarif", or "json"
        output_path: Optional file path (relative to local_path) to write
            the threat model to disk. If not provided, returns content as string.
        detail_level: Detail level for Markdown output - "summary" or "detailed"
            (default). Only affects Markdown; SARIF/JSON always include full detail.

    Returns:
        Threat model report with identified threats and recommendations,
        or a confirmation message if output_path is provided.
    """
    from darnit_baseline.threat_model.grouping import group_by_cli_family
    from darnit_baseline.threat_model.ranking import (
        apply_cap,
        assign_stride_for_cli_families,
        rank_findings,
    )
    from darnit_baseline.threat_model.ts_discovery import discover_all
    from darnit_baseline.threat_model.ts_generators import (
        GeneratorOptions,
        generate_json_summary,
        generate_markdown_threat_model,
        generate_sarif_threat_model,
    )

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    try:
        result = discover_all(repo_path)
        ranked = rank_findings(result.findings)
        emitted, overflow = apply_cap(ranked, max_findings=50)

        # Feature 014-cobra-threat-model: build CLI command families once
        # and pass to all three generators (Markdown / SARIF / JSON) so the
        # single-file output path emits the same cobra section as the
        # multi-file pipeline (threat_model/remediation.py).
        cli_families = group_by_cli_family(result.entry_points)
        if cli_families:
            assign_stride_for_cli_families(
                cli_families, result.cobra_file_imports
            )

        if output_format == "sarif":
            content = generate_sarif_threat_model(
                result, emitted, cli_families=cli_families
            )
        elif output_format == "json":
            content = generate_json_summary(
                result, emitted, overflow, cli_families=cli_families
            )
        else:
            options = GeneratorOptions(detail_level=detail_level)
            content = generate_markdown_threat_model(
                repo_path=str(repo_path),
                result=result,
                capped_findings=emitted,
                overflow=overflow,
                options=options,
                cli_families=cli_families,
            )

        if output_path:
            # Use multi-file pipeline for the new canonical location.
            if output_path.endswith("SUMMARY.md") or "threatmodel" in output_path:
                from darnit.sieve.handler_registry import HandlerContext
                from darnit_baseline.threat_model.remediation import (
                    generate_threat_model_handler,
                )

                context = HandlerContext(
                    local_path=str(repo_path),
                    owner=owner or "",
                    repo=repo or "",
                    control_id="OSPS-SA-03.02",
                )
                handler_result = generate_threat_model_handler(
                    {"path": output_path, "overwrite": True},
                    context,
                )
                files = handler_result.evidence.get("files_written", [output_path])
                return (
                    f"Multi-file threat model written to {output_path} "
                    f"({len(ranked)} findings, {len(files)} files)"
                )

            target = repo_path / output_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return (
                f"Threat model written to {output_path} ({len(content)} bytes, "
                f"{len(emitted)} findings, {overflow.total} trimmed)"
            )

        return content
    except Exception as e:
        return f"❌ Error generating threat model: {e}"


def generate_attestation(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    level: int = 3,
    sign: bool = True,
    staging: bool = False,
    output_path: str | None = None,
    output_dir: str | None = None,
    host: str | None = None,
) -> str:
    """
    Generate an in-toto attestation for OpenSSF Baseline compliance.

    Creates a cryptographically signed attestation proving compliance status.

    Args:
        owner: GitHub org/user (auto-detected if not provided)
        repo: Repository name (auto-detected if not provided)
        local_path: ABSOLUTE path to repo
        level: Maximum OSPS level to check (1, 2, or 3)
        sign: Whether to sign with Sigstore. Default: True
        staging: Use Sigstore staging environment. Default: False
        output_path: Explicit path for attestation file
        output_dir: Directory to save attestation
        host: Git host of owner/repo (default github.com); owner, repo, and host
              name the repository whose trust is recorded in the attestation

    Returns:
        JSON attestation and path to saved file
    """
    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    from darnit.core.utils import detect_owner_repo
    from darnit.trust.decision import target_from_owner_repo

    target = target_from_owner_repo(owner, repo, host)

    detected_owner, detected_repo = detect_owner_repo(str(repo_path))
    owner = owner or detected_owner
    repo = repo or detected_repo

    if not owner or not repo:
        return "❌ Error: owner/repo could not be determined. Pass them explicitly."

    try:
        from darnit.config.operator.loader import resolve_operator_config
        from darnit.tools.audit import calculate_compliance, run_sieve_audit
        from darnit.trust.decision import decide_trust
        from darnit_baseline.attestation import generate_attestation_from_results

        default_branch = _detect_default_branch(repo_path)
        operator_config = resolve_operator_config(repo_path)
        results, summary = run_sieve_audit(
            owner=owner,
            repo=repo,
            local_path=str(repo_path),
            default_branch=default_branch,
            level=level,
            framework_name="openssf-baseline",
            operator_config=operator_config,
            target=target,
        )
        compliance = calculate_compliance(results, level)
        audit_result = _build_audit_result(
            owner, repo, repo_path, level, default_branch,
            results, summary, compliance,
        )
        audit_result.trust = decide_trust(target, operator_config.config, repo_path).report()
        return generate_attestation_from_results(
            audit_result,
            sign=sign,
            staging=staging,
            output_path=output_path,
            output_dir=output_dir,
        )
    except Exception as e:
        return f"❌ Error generating attestation: {e}"


# =============================================================================
# Remediation Tools
# =============================================================================


def remediate_audit_findings(
    local_path: str = ".",
    owner: str | None = None,
    repo: str | None = None,
    categories: list | None = None,
    dry_run: bool = True,
    profile: str | None = None,
    branch_name: str | None = None,
    auto_commit: bool = False,
    create_pr: bool = False,
    enhance_with_llm: bool = False,
    approve: list | None = None,
) -> str:
    """
    Apply automated remediations for failed audit controls.

    By default remediates ALL failed controls that have TOML-defined
    remediation.  Use ``categories`` to filter to a subset by domain.

    Domain-based category filters:
    - access_control, build_release, documentation, governance, legal,
      quality, security_architecture, vulnerability_management

    Supports optional git workflow (ignored when dry_run=True):
    - branch_name: Create/switch to this branch before applying (e.g., "fix/compliance")
    - auto_commit: Commit changes after applying (requires dry_run=false)
    - create_pr: Create a pull request after committing (requires auto_commit=true)

    Args:
        local_path: ABSOLUTE path to repo
        owner: GitHub org/user (auto-detected if not provided)
        repo: Repository name (auto-detected if not provided)
        categories: Optional filter — list of category names, or ["all"]
        dry_run: If True (default), show what would be changed without applying
        profile: Optional audit profile name to filter remediation to profile controls only
        branch_name: Create/checkout this branch before applying remediations
        auto_commit: Automatically commit after applying remediations
        create_pr: Create a pull request after committing
        enhance_with_llm: If True, enrich complex documents (ARCHITECTURE.md,
            threat model) with LLM-generated descriptions after deterministic
            generation.  Default False (opt-in).
        approve: Digests from the preview that the person approved. Platform
            changes are written only for approved change-set digests under the
            default remediation policy; ``dry_run=False`` alone approves
            nothing. Pass only digests the person approved.

    Returns:
        Summary of applied or planned remediations (with git workflow status if applicable)
    """
    from darnit_baseline.remediation import orchestrator

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"Error: Repository path not found: {repo_path}"

    # Validate git workflow param combinations
    if create_pr and not auto_commit:
        return "Error: create_pr requires auto_commit=True"

    from darnit.core.utils import detect_owner_repo

    detected_owner, detected_repo = detect_owner_repo(str(repo_path))
    owner = owner or detected_owner
    repo = repo or detected_repo

    # Guard: unresolved context stops remediation, and so does a guard that
    # cannot tell (feature 043, FR-020).
    try:
        from darnit.config.context_storage import get_pending_context as _get_pending

        pending = _get_pending(
            local_path=str(repo_path), owner=owner, repo=repo,
        )
    except Exception as e:
        return (
            f"Error: cannot check for unconfirmed project context: {e}. "
            "Remediation did not run; nothing was changed."
        )
    if pending:
        keys = [p.key for p in pending]
        return (
            "Cannot remediate yet: there are unresolved context questions.\n\n"
            f"**Pending context keys**: {', '.join(keys)}\n\n"
            "Please call `get_pending_data()` first to collect the missing "
            "project context, then confirm each answer with `confirm_project_data()`. "
            "Once all context is resolved, call `remediate_audit_findings()` again."
        )

    from darnit.remediation import git_state, manifest
    from darnit.server.tools import git_operations

    run_id = manifest.new_run_id()

    # Feature 043 (FR-013): a requested git step is checked before any
    # remediation is applied; an unsafe repository state changes nothing.
    if not dry_run and (branch_name or auto_commit or create_pr):
        refusal = git_state.check_repository_state(repo_path, branch_name)
        if refusal:
            return f"Error: cannot run the requested git steps: {refusal}. Nothing was changed."

    # Step 1: Create branch before applying (so changes land on the right branch)
    git_report: list[str] = []
    if branch_name and not dry_run:
        branch_result = git_operations.create_remediation_branch_impl(
            branch_name=branch_name, local_path=str(repo_path), run_id=run_id, owner=owner, repo=repo,
        )
        if git_state.current_branch(repo_path) != branch_name:
            return f"Error: the remediation branch was not checked out; remediation did not run.\n\n{branch_result}"
        git_report.append(branch_result)

    # Step 2: Apply remediations
    try:
        report = orchestrator.run_remediation(
            local_path=str(repo_path),
            owner=owner,
            repo=repo,
            categories=categories or ["all"],
            dry_run=dry_run,
            profile=profile,
            enhance_with_llm=enhance_with_llm,
            approve=approve,
            run_id=run_id,
        )
    except Exception as e:
        return f"Error applying remediations: {e}"
    result = report.markdown

    # Step 3: Commit and optionally open a PR, only when an outcome changed
    # files (FR-019). The PR step itself refuses a run with no commit.
    run = report.run
    changed_files = (
        run is not None
        and run.mode == "apply"
        and any(change.changes for outcome in run.outcomes for change in outcome.file_changes)
    )
    if not dry_run and auto_commit:
        if changed_files:
            git_report.append(
                git_operations.commit_remediation_changes_impl(
                    local_path=str(repo_path), run_id=run_id, owner=owner, repo=repo,
                )
            )
            if create_pr:
                git_report.append(
                    git_operations.create_remediation_pr_impl(
                        local_path=str(repo_path), run_id=run_id, owner=owner, repo=repo,
                    )
                )
        else:
            git_report.append("No outcome changed a file, so nothing was committed and no pull request was opened.")

    # Append git workflow summary if any git steps ran
    if git_report:
        result += "\n\n---\n## Git Workflow\n\n" + "\n\n".join(git_report)

    return result


# =============================================================================
# Git Workflow Tools
# =============================================================================


def create_remediation_branch(
    branch_name: str = "fix/openssf-baseline-compliance",
    local_path: str = ".",
    base_branch: str | None = None,
    run_id: str | None = None,
) -> str:
    """
    Create a new branch for remediation work, or switch to an existing remediation branch.

    Never stashes. A new branch is created from HEAD and uncommitted changes
    stay in the working tree. An existing branch is used only when the
    working tree is clean and every commit on it beyond its base was made by
    remediation. A detached HEAD or a merge or rebase in progress is refused.

    Args:
        branch_name: Name for the branch
        local_path: Path to the repository
        base_branch: Branch to base off of (default: current branch)
        run_id: Remediation run to record the branch in (default: the latest run)

    Returns:
        Success message with branch name or error
    """
    from darnit.server.tools.git_operations import create_remediation_branch_impl

    return create_remediation_branch_impl(
        branch_name=branch_name,
        local_path=local_path,
        base_branch=base_branch,
        run_id=run_id,
    )


def commit_remediation_changes(
    local_path: str = ".",
    message: str | None = None,
    run_id: str | None = None,
) -> str:
    """
    Commit the files a remediation run wrote, and nothing else.

    Stages only the run's files whose content is unchanged since remediation
    wrote them, never ignored files, and adds a ``Darnit-Remediation-Run``
    trailer. Other changes in the working tree are left as they are.

    Args:
        local_path: Path to the repository
        message: Commit message (auto-generated if not provided)
        run_id: Remediation run to commit (default: the latest run)

    Returns:
        Success message listing every committed file, or error
    """
    from darnit.server.tools.git_operations import commit_remediation_changes_impl

    return commit_remediation_changes_impl(
        local_path=local_path,
        message=message,
        run_id=run_id,
    )


def create_remediation_pr(
    local_path: str = ".",
    title: str | None = None,
    body: str | None = None,
    base_branch: str | None = None,
    draft: bool = False,
    run_id: str | None = None,
) -> str:
    """
    Create a pull request for a remediation run's branch, pushing only that branch.

    Use this after committing remediation changes to open a PR for review.

    Args:
        local_path: Path to the repository
        title: PR title (auto-generated if not provided)
        body: PR body/description (auto-generated if not provided)
        base_branch: Target branch for PR (default: repo default branch)
        draft: Create as draft PR (default: False)
        run_id: Remediation run whose branch to push (default: the latest run)

    Returns:
        Success message with PR URL or error
    """
    from darnit.server.tools.git_operations import create_remediation_pr_impl

    return create_remediation_pr_impl(
        local_path=local_path,
        title=title,
        body=body,
        base_branch=base_branch,
        draft=draft,
        run_id=run_id,
    )


def get_remediation_status(local_path: str = ".") -> str:
    """
    Get the current git status for remediation work.

    Use this to check the state of the repository before/after remediation.

    Args:
        local_path: Path to the repository

    Returns:
        Current branch, uncommitted changes, and next steps
    """
    from darnit.server.tools.git_operations import get_remediation_status_impl

    return get_remediation_status_impl(local_path=local_path)


# =============================================================================
# Test Repository Tool
# =============================================================================


def create_test_repository(
    repo_name: str = "baseline-test-repo",
    parent_dir: str = ".",
    github_org: str | None = None,
    create_github: bool = True,
    make_template: bool = False,
) -> str:
    """
    Create a minimal test repository that intentionally fails all OpenSSF Baseline controls.

    Useful for testing the baseline-mcp audit tools and learning what each control requires.

    Args:
        repo_name: Name of the repository (default: baseline-test-repo)
        parent_dir: Directory to create the repo in (default: current directory)
        github_org: GitHub org/username (auto-detected if not provided)
        create_github: Whether to create a GitHub repo (requires gh CLI)
        make_template: Whether to make it a GitHub template repository

    Returns:
        Success message with next steps
    """
    from darnit.server.tools.test_repository import create_test_repository_impl

    return create_test_repository_impl(
        repo_name=repo_name,
        parent_dir=parent_dir,
        github_org=github_org,
        create_github=create_github,
        make_template=make_template,
    )


# =============================================================================
# Helper Functions
# =============================================================================



def _detect_default_branch(repo_path: Path) -> str:
    """Detect the default branch name."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().split("/")[-1]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return "main"


def list_org_repos(
    owner: str,
    include_archived: bool = False,
) -> str:
    """
    List all repositories in a GitHub org or user account.

    Returns a JSON list of repository names. Use this to discover repos
    before auditing them individually with ``audit_org``.

    Requires the ``gh`` CLI to be installed and authenticated.

    Args:
        owner: GitHub org or user (e.g., "kusari-oss")
        include_archived: Include archived repositories. Default: False

    Returns:
        JSON object with repo list and count
    """
    from darnit.tools.audit_org import enumerate_org_repos

    repo_names, error = enumerate_org_repos(
        owner, include_archived=include_archived
    )
    if error:
        return json.dumps({"error": error, "repos": [], "count": 0})

    return json.dumps({
        "owner": owner,
        "repos": repo_names,
        "count": len(repo_names),
    })


def audit_org(
    owner: str,
    repo: str,
    level: int = 3,
    tags: str | list[str] | None = None,
    output_format: str = "markdown",
) -> str:
    """
    Audit a single repository from a GitHub org by cloning it to a temp
    directory and running the OpenSSF Baseline audit pipeline.

    Use ``list_org_repos`` first to discover available repos, then call
    this tool for each repo individually.

    Requires the ``gh`` CLI to be installed and authenticated.

    Args:
        owner: GitHub org or user (e.g., "kusari-oss")
        repo: Repository name to audit (e.g., "my-repo")
        level: Maximum OSPS level to check (1, 2, or 3). Default: 3
        tags: Filter controls by tags (same format as audit_openssf_baseline)
        output_format: "markdown" or "json". Default: "markdown"

    Returns:
        Audit report for the single repository
    """
    from darnit.tools.audit_org import _audit_single_repo

    # Normalize tags
    tags_list: list[str] | None = None
    if tags:
        if isinstance(tags, str):
            tags_list = [tags]
        else:
            tags_list = list(tags)

    result = _audit_single_repo(owner, repo, level, tags_list, framework_name="openssf-baseline")

    if output_format == "json":
        return json.dumps(result, indent=2)

    # Markdown format
    if result["status"] == "ERROR":
        return f"# Audit: {owner}/{repo}\n\n**Error:** {result['error']}"

    from darnit.tools.audit import calculate_compliance, format_results_markdown

    results = result["results"]
    summary = result["summary"]

    if not results:
        return f"# Audit: {owner}/{repo}\n\nNo results available."

    compliance = calculate_compliance(results, level)
    return format_results_markdown(
        owner=owner,
        repo=repo,
        results=results,
        summary=summary,
        compliance=compliance,
        level=level,
        framework_name="openssf-baseline",
        audit_metadata={
            k: result[k]
            for k in ("operator_config", "trust", "ignored_repository_settings", "unknown_assertions", "warnings")
            if k in result
        },
    )


__all__ = [
    # Audit
    "audit_openssf_baseline",
    "list_org_repos",
    "audit_org",
    "list_available_checks",
    # Configuration
    "get_project_config",
    "init_project_config",
    "confirm_project_data",
    "get_pending_data",
    # Threat Model & Attestation
    "generate_threat_model",
    "generate_attestation",
    # Remediation
    "create_security_policy",
    "enable_branch_protection",
    "remediate_audit_findings",
    # Git Workflow
    "create_remediation_branch",
    "commit_remediation_changes",
    "create_remediation_pr",
    "get_remediation_status",
    # Test Repository
    "create_test_repository",
]
