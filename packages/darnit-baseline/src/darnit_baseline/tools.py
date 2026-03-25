"""MCP tool handlers for OpenSSF Baseline.

This module provides standalone tool functions that can be registered
with the darnit MCP server via TOML configuration.

Each function is designed to be used as an MCP tool handler.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    prefer_upstream: bool = True,
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
        output_format: Output format - "markdown", "json", or "sarif". Default: "markdown"
        auto_init_config: Create .project.yaml if missing. Default: True
        attest: Generate in-toto attestation after audit. Default: False
        sign_attestation: Sign attestation with Sigstore. Default: True
        staging: Use Sigstore staging environment. Default: False
        prefer_upstream: If True, prefer 'upstream' git remote when auto-detecting owner/repo.
                         Useful for auditing forks against their upstream repository. Default: True

    Returns:
        Formatted audit report with compliance status and remediation instructions
    """
    from darnit.config import (
        load_controls_from_effective,
        load_effective_config_by_name,
    )
    from darnit.tools.audit import (
        calculate_compliance,
        format_results_markdown,
        run_sieve_audit,
    )

    # Resolve path
    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    # Auto-detect owner/repo from git (upstream-first by default)
    from darnit.core.utils import detect_owner_repo

    detected_owner, detected_repo = detect_owner_repo(
        str(repo_path), prefer_upstream=prefer_upstream
    )
    owner = owner or detected_owner
    repo = repo or detected_repo

    # Load framework config
    try:
        config = load_effective_config_by_name("openssf-baseline", repo_path)
    except Exception as e:
        return f"❌ Error loading framework: {e}"

    # Load controls filtered by level
    controls = load_controls_from_effective(config)
    controls = [c for c in controls if c.level <= level]

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
    )

    # Format output
    if output_format == "json":
        return json.dumps({
            "owner": owner,
            "repo": repo,
            "level": level,
            "summary": summary,
            "results": results,
        }, indent=2)
    else:
        compliance = calculate_compliance(results, level)
        return format_results_markdown(
            owner=owner,
            repo=repo,
            results=results,
            summary=summary,
            compliance=compliance,
            level=level,
            local_path=str(repo_path),
            report_title="OpenSSF Baseline Audit Report",
            remediation_map=OSPS_REMEDIATION_MAP,
        )


def list_available_checks() -> str:
    """
    List all available OpenSSF Baseline checks organized by level.

    Returns:
        Formatted list of all 62 OSPS controls across 3 levels
    """
    from darnit.config.merger import load_framework_by_name

    config = load_framework_by_name("openssf-baseline")
    checks: dict[str, list] = {"level1": [], "level2": [], "level3": []}

    for control_id, control in config.controls.items():
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

        executor = RemediationExecutor(
            local_path=str(repo_path),
            owner=owner,
            repo=repo,
            templates=framework.templates or {},
            framework_path=fw_path,
        )

        result = executor.execute(
            control_id="OSPS-VM-02.01",
            config=control.remediation,
            dry_run=False,
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
    branch: str = "main",
    required_approvals: int = 1,
    enforce_admins: bool = True,
    require_pull_request: bool = True,
    require_status_checks: bool = False,
    status_checks: list | None = None,
    local_path: str = ".",
    dry_run: bool = False,
) -> str:
    """
    Enable branch protection rules.

    Satisfies: OSPS-AC-03.01, OSPS-AC-03.02, OSPS-QA-07.01

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        branch: Branch to protect (default: main)
        required_approvals: Number of required PR approvals (default: 1)
        enforce_admins: Apply rules to admins too (default: True)
        require_pull_request: Require PRs for changes (default: True)
        require_status_checks: Require status checks (default: False)
        status_checks: List of required status check contexts
        local_path: Path to repository for auto-detection
        dry_run: Show what would be done without making changes

    Returns:
        Success message with configuration details
    """
    from darnit.remediation.github import enable_branch_protection as _enable

    repo_path = Path(local_path).resolve()

    # Auto-detect owner/repo
    from darnit.core.utils import detect_owner_repo

    detected_owner, detected_repo = detect_owner_repo(str(repo_path))
    owner = owner or detected_owner
    repo = repo or detected_repo

    try:
        result = _enable(
            owner=owner,
            repo=repo,
            branch=branch,
            required_approvals=required_approvals,
            enforce_admins=enforce_admins,
            require_pull_request=require_pull_request,
            require_status_checks=require_status_checks,
            status_checks=status_checks or [],
            dry_run=dry_run,
        )
        return result
    except Exception as e:
        return f"❌ Error configuring branch protection: {e}"


# =============================================================================
# Configuration Tools
# =============================================================================


def init_project_config(
    local_path: str = ".",
    project_name: str | None = None,
    project_type: str = "software",
) -> str:
    """
    Initialize a new OpenSSF Baseline configuration file (.project.yaml).

    Creates a .project.yaml with discovered file locations.

    Args:
        local_path: Path to repository
        project_name: Project name (auto-detected if not provided)
        project_type: Type of project (software, library, framework, specification)

    Returns:
        Success message with created configuration
    """
    from darnit.config import config_exists
    from darnit.config import init_project_config as _init

    repo_path = Path(local_path).resolve()

    if config_exists(repo_path):
        return "⚠️ .project.yaml already exists. Use get_project_config() to view it."

    try:
        _init(repo_path, project_name=project_name)
        return f"✅ Created .project.yaml at {repo_path}"
    except Exception as e:
        return f"❌ Error creating config: {e}"


def confirm_project_context(
    local_path: str = ".",
    has_subprojects: bool | None = None,
    has_releases: bool | None = None,
    is_library: bool | None = None,
    has_compiled_assets: bool | None = None,
    ci_provider: str | None = None,
    # New governance and security context
    maintainers: list[str] | str | None = None,
    security_contact: str | None = None,
    governance_model: str | None = None,
) -> str:
    """
    Record user-confirmed project context in .project.yaml.

    **IMPORTANT**: This is the ONLY way to set project context. DO NOT directly edit
    .project/ files - always use this tool instead.

    **Parameters:**
    - `local_path`: Path to repository (default: ".")
    - `maintainers`: Project maintainers - list ["@user1", "@user2"] OR file reference "CODEOWNERS"
    - `security_contact`: Security contact email or file reference
    - `governance_model`: One of: bdfl, meritocracy, democracy, corporate, foundation, committee, other
    - `ci_provider`: One of: github, gitlab, jenkins, circleci, azure, travis, none, other
    - `has_subprojects`: Boolean - does project have subprojects?
    - `has_releases`: Boolean - does project make official releases?
    - `is_library`: Boolean - is this a library consumed by other projects?
    - `has_compiled_assets`: Boolean - does project release compiled binaries?

    **Examples:**
    ```
    # Reference existing CODEOWNERS file (RECOMMENDED)
    confirm_project_context(maintainers="CODEOWNERS")

    # Explicit maintainer list
    confirm_project_context(maintainers=["@alice", "@bob"])

    # Multiple context values
    confirm_project_context(
        maintainers="CODEOWNERS",
        security_contact="security@example.com",
        ci_provider="github"
    )
    ```

    Returns:
        Confirmation of what was recorded
    """
    from darnit.server.tools.project_context import confirm_project_context_impl

    return confirm_project_context_impl(
        local_path=local_path,
        has_subprojects=has_subprojects,
        has_releases=has_releases,
        is_library=is_library,
        has_compiled_assets=has_compiled_assets,
        ci_provider=ci_provider,
        maintainers=maintainers,
        security_contact=security_contact,
        governance_model=governance_model,
    )


# Fixed ordering matching TOML [context.*] definition order for stable UX.
# This must match the order of sections in openssf-baseline.toml.
_CONTEXT_KEY_ORDER = [
    "maintainers",
    "security_contact",
    "governance_model",
    "has_subprojects",
    "has_releases",
    "is_library",
    "has_compiled_assets",
    "ci_provider",
]

_LLM_DIRECTIVE_PREFIX = """⚠️ MANDATORY: Your next action MUST be calling the AskUserQuestion tool.

Copy "ask_user_batch" below verbatim as the "questions" parameter to AskUserQuestion.
Do NOT render these questions as text. Do NOT paraphrase. Do NOT summarize.
You MUST call the AskUserQuestion tool now.

After the user answers, use "answer_mapping" to call confirm_project_context() for EACH answer:
- "Yes" / "No" for booleans → pass true / false (not strings)
- Selected option label for enums → pass the label as a string
- "Other" selections → pass the user's typed value
Then call get_pending_context() again for the next batch (if any remain).

---
"""


def get_pending_context(
    local_path: str = ".",
    control_ids: list[str] | None = None,
    level: int = 3,
    owner: str | None = None,
    repo: str | None = None,
    limit: int = 4,
    _tool_config: dict | None = None,
) -> str:
    """Get context values that would improve audit accuracy.

    Returns up to `limit` questions per call as a batch.

    MANDATORY WORKFLOW — your next action MUST be calling AskUserQuestion:
    1. Call this tool. It returns "ask_user_batch" — an array ready for AskUserQuestion.
    2. Call AskUserQuestion(questions=<ask_user_batch>). Pass VERBATIM. Do NOT render as text.
    3. After the user answers, use "answer_mapping" to call confirm_project_context() per answer.
    4. Call get_pending_context() again for the next batch. Repeat until status is "complete".

    Parameters:
    - `local_path`: Path to repository (default: ".")
    - `control_ids`: Optional list of control IDs to check
    - `level`: Maximum maturity level (1, 2, or 3)
    - `owner`: GitHub owner (auto-detected if not provided)
    - `repo`: GitHub repo name (auto-detected if not provided)
    - `limit`: Max questions to return per batch (default: 4). Use 0 for all.

    Returns:
        JSON with ask_user_batch (pass directly to AskUserQuestion),
        answer_mapping for confirm_project_context, and a progress indicator.
    """
    from darnit.config.context_storage import get_pending_context as _get_pending

    repo_path = Path(local_path).resolve()

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
            level=level,
            owner=owner,
            repo=repo,
        )

        if not pending:
            return json.dumps({
                "status": "complete",
                "message": "All context has been confirmed. No additional input needed.",
                "questions": [],
            }, indent=2)

        total = len(pending)

        # Read config from TOML if available
        effective_limit = limit
        append_directive = True
        if _tool_config:
            effective_limit = _tool_config.get("limit", limit)
            append_directive = _tool_config.get("append_directive", True)

        # Build structured JSON output — each question specifies exactly
        # how to present it so the calling LLM doesn't improvise
        questions = []
        for req in pending:
            questions.append(_build_context_question(req))

        # Sort by TOML definition order for stable UX across runs.
        # Keys not in the fixed order list sort to the end.
        def _toml_order(q: dict) -> int:
            try:
                return _CONTEXT_KEY_ORDER.index(q["key"])
            except ValueError:
                return len(_CONTEXT_KEY_ORDER)

        questions.sort(key=_toml_order)

        # Apply pagination (limit=0 means return all)
        if effective_limit > 0:
            questions = questions[:effective_limit]

        # Build ask_user_batch: collect per-question ask_user params into
        # a single array that maps directly to AskUserQuestion's questions param.
        batch_questions = []
        answer_mapping = []
        for q in questions:
            ask_user = q.get("ask_user")
            if ask_user is not None:
                batch_questions.append(ask_user)
                mapping: dict = {
                    "question_index": len(batch_questions) - 1,
                    "context_key": q["key"],
                }
                # Build value_map for the LLM to translate selections
                input_type = q.get("input_type")
                if input_type == "select" and q.get("options") == ["true", "false"]:
                    mapping["value_map"] = {"Yes": True, "No": False}
                elif input_type == "confirm":
                    mapping["value_map"] = {
                        "Yes": q.get("detected_value"),
                        "No": "ASK_USER_FOR_VALUE",
                    }
                answer_mapping.append(mapping)

        # Determine answered count from total minus pending
        answered = total - len(pending)

        response: dict = {
            "status": "pending",
            "progress": {
                "answered": answered,
                "total": total,
            },
        }

        if batch_questions:
            response["ask_user_batch"] = batch_questions
            response["answer_mapping"] = answer_mapping

        # Include raw question details only when no ask_user_batch
        # (i.e., free_text questions that can't use AskUserQuestion)
        if not batch_questions:
            response["questions"] = questions

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


def _build_context_question(req) -> dict:
    """Build a structured question dict for a pending context request.

    Returns a JSON-serializable dict with explicit input_type so the calling
    LLM knows exactly how to present it — no room for improvisation.
    """
    auto_detect_enabled = getattr(req.definition, "auto_detect", False)

    question: dict = {
        "key": req.key,
        "priority": req.priority,
        "affects_controls": req.control_ids,
    }

    # Include presentation hint if available
    hint = req.definition.computed_presentation_hint
    if hint is not None:
        question["presentation_hint"] = hint

    # Determine input type and build question accordingly
    if req.current_value is not None and auto_detect_enabled:
        # Auto-detected value available — ask user to confirm or correct
        value = req.current_value.value
        method = req.current_value.detection_method or "auto"
        confidence = req.current_value.confidence

        question["input_type"] = "confirm"
        question["question"] = req.definition.prompt
        question["detected_value"] = value
        question["detection_method"] = method
        question["confidence"] = int(confidence * 100)
        question["auto_accepted"] = getattr(req.current_value, "auto_accepted", False)
        question["instruction"] = (
            "Show the detected value and ask the user to confirm or correct it."
        )
        if isinstance(value, list):
            question["confirm_command"] = (
                f"confirm_project_context({req.key}={repr(value)})"
            )
        else:
            question["confirm_command"] = (
                f'confirm_project_context({req.key}="{value}")'
            )

    elif req.definition.type == "enum" and req.definition.values:
        # Enum type — provide the exact options
        question["input_type"] = "select"
        question["question"] = req.definition.prompt
        question["options"] = req.definition.values
        question["instruction"] = (
            "Present ONLY these options. Do NOT add other options."
        )
        if req.definition.hint:
            question["hint"] = req.definition.hint
        question["command_template"] = (
            f'confirm_project_context({req.key}="<selected_value>")'
        )

    elif req.definition.type == "boolean":
        # Boolean — yes/no only
        question["input_type"] = "select"
        question["question"] = req.definition.prompt
        question["options"] = ["true", "false"]
        question["instruction"] = "Ask yes or no. Do NOT add other options."
        if req.definition.hint:
            question["hint"] = req.definition.hint
        question["command_template"] = (
            f"confirm_project_context({req.key}=<true_or_false>)"
        )

    else:
        # Free text — the user must type their answer
        question["input_type"] = "free_text"
        question["question"] = req.definition.prompt
        question["instruction"] = (
            "Ask the user to type their answer. "
            "Do NOT suggest values. Do NOT pre-fill based on repository "
            "owner, git config, or any other source. "
            "Present a blank text input only."
        )
        if req.definition.hint:
            question["hint"] = req.definition.hint
        if req.definition.examples:
            question["example_format"] = req.definition.examples
        question["command_template"] = (
            f"confirm_project_context({req.key}=<user_answer>)"
        )

    # Add ask_user params for interactive presentation (AskUserQuestion)
    ask_user = _build_ask_user_params(req.key, question, req.definition)
    if ask_user is not None:
        question["ask_user"] = ask_user

    return question


def _build_ask_user_params(key: str, question_dict: dict, definition) -> dict | None:
    """Build AskUserQuestion-compatible parameters for interactive presentation.

    Returns a dict with question/header/options/multiSelect fields that map
    directly to Claude Code's AskUserQuestion tool, or None if the question
    type doesn't support interactive selection.
    """
    input_type = question_dict.get("input_type")
    question_text = question_dict.get("question", "")

    # Derive header: remove common prefixes, title case, max 12 chars
    header = key.removeprefix("has_").removeprefix("is_").replace("_", " ").title()
    if len(header) > 12:
        header = header[:12]

    if input_type == "select":
        raw_options = question_dict.get("options", [])
        if not raw_options:
            return None

        if getattr(definition, "type", None) == "boolean":
            options = [
                {"label": "Yes", "description": definition.hint or "Yes, this applies"},
                {"label": "No", "description": "No, this does not apply"},
            ]
        else:
            # Enum: show up to 4 values, "Other" is always available
            display = getattr(definition, "allowed_values", None) or raw_options
            options = [
                {"label": str(v), "description": f"Select '{v}'"}
                for v in display[:4]
            ]

        return {
            "question": question_text,
            "header": header,
            "options": options,
            "multiSelect": False,
        }

    elif input_type == "confirm":
        detected = question_dict.get("detected_value")
        method = question_dict.get("detection_method", "auto-detected")
        return {
            "question": question_text,
            "header": header,
            "options": [
                {"label": "Yes", "description": f"Accept: {detected} ({method})"},
                {"label": "No", "description": "Specify a different value"},
            ],
            "multiSelect": False,
        }

    elif input_type == "free_text":
        # Use examples as options if available
        examples = getattr(definition, "examples", None)
        if examples and isinstance(examples, list) and len(examples) >= 2:
            options = [
                {"label": str(ex), "description": f"Use '{ex}'"}
                for ex in examples[:4]
            ]
            return {
                "question": question_text,
                "header": header,
                "options": options,
                "multiSelect": False,
            }

    return None


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

    Analyzes the codebase for entry points, auth mechanisms, data stores,
    potential vulnerabilities, and hardcoded secrets.

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
    from darnit_baseline.threat_model import (
        analyze_stride_threats,
        detect_attack_chains,
        detect_frameworks,
        discover_all_assets,
        discover_injection_sinks,
        generate_json_summary,
        generate_markdown_threat_model,
        generate_sarif_threat_model,
        identify_control_gaps,
    )

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    from darnit.core.utils import detect_owner_repo

    detected_owner, detected_repo = detect_owner_repo(str(repo_path))
    owner = owner or detected_owner
    repo = repo or detected_repo

    try:
        # Detect frameworks
        frameworks = detect_frameworks(str(repo_path))

        # Discover assets
        assets = discover_all_assets(str(repo_path), frameworks)

        # Discover injection sinks
        injection_sinks = discover_injection_sinks(str(repo_path))

        # Analyze threats
        threats = analyze_stride_threats(assets, injection_sinks)

        # Detect attack chains
        attack_chains = detect_attack_chains(threats, assets)

        # Identify control gaps
        control_gaps = identify_control_gaps(assets, threats)

        # Validate detail_level
        if detail_level not in ("summary", "detailed"):
            detail_level = "detailed"

        # Generate output
        if output_format == "sarif":
            content = json.dumps(generate_sarif_threat_model(str(repo_path), threats, attack_chains), indent=2)
        elif output_format == "json":
            content = json.dumps(generate_json_summary(str(repo_path), frameworks, assets, threats, control_gaps, attack_chains), indent=2)
        else:
            content = generate_markdown_threat_model(str(repo_path), assets, threats, control_gaps, frameworks, detail_level, attack_chains)

        # Write to disk if output_path provided
        if output_path:
            target = repo_path / output_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            return f"Threat model written to {output_path} ({len(content)} bytes)"

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

    Returns:
        JSON attestation and path to saved file
    """
    from darnit_baseline.attestation import generate_attestation as _generate

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    from darnit.core.utils import detect_owner_repo

    detected_owner, detected_repo = detect_owner_repo(str(repo_path))
    owner = owner or detected_owner
    repo = repo or detected_repo

    try:
        result = _generate(
            owner=owner,
            repo=repo,
            local_path=str(repo_path),
            level=level,
            sign=sign,
            staging=staging,
            output_path=output_path,
            output_dir=output_dir,
        )
        return result
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
) -> str:
    """
    Apply automated remediations for failed audit controls.

    By default remediates ALL failed controls that have TOML-defined
    remediation.  Use ``categories`` to filter to a subset by domain.

    Domain-based category filters:
    - access_control, build_release, documentation, governance, legal,
      quality, security_architecture, vulnerability_management

    Args:
        local_path: ABSOLUTE path to repo
        owner: GitHub org/user (auto-detected if not provided)
        repo: Repository name (auto-detected if not provided)
        categories: Optional filter — list of category names, or ["all"]
        dry_run: If True (default), show what would be changed without applying

    Returns:
        Summary of applied or planned remediations
    """
    from darnit_baseline.remediation import remediate_audit_findings as apply_remediations

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    from darnit.core.utils import detect_owner_repo

    detected_owner, detected_repo = detect_owner_repo(str(repo_path))
    owner = owner or detected_owner
    repo = repo or detected_repo

    # Guard: check for unresolved context before remediating
    try:
        from darnit.config.context_storage import get_pending_context as _get_pending

        pending = _get_pending(
            local_path=str(repo_path), owner=owner, repo=repo,
        )
        if pending:
            keys = [p.key for p in pending]
            return (
                "⚠️ Cannot remediate yet — there are unresolved context questions.\n\n"
                f"**Pending context keys**: {', '.join(keys)}\n\n"
                "Please call `get_pending_context()` first to collect the missing "
                "project context, then confirm each answer with `confirm_project_context()`. "
                "Once all context is resolved, call `remediate_audit_findings()` again."
            )
    except Exception:
        pass  # If context check fails, proceed with remediation anyway

    try:
        result = apply_remediations(
            local_path=str(repo_path),
            owner=owner,
            repo=repo,
            categories=categories or ["all"],
            dry_run=dry_run,
        )
        return result
    except Exception as e:
        return f"❌ Error applying remediations: {e}"


# =============================================================================
# Git Workflow Tools
# =============================================================================


def create_remediation_branch(
    branch_name: str = "fix/openssf-baseline-compliance",
    local_path: str = ".",
    base_branch: str | None = None,
) -> str:
    """
    Create a new branch for remediation work.

    Use this before applying remediations so changes can be reviewed via PR.

    Args:
        branch_name: Name for the new branch
        local_path: Path to the repository
        base_branch: Branch to base off of (default: current branch)

    Returns:
        Success message with branch name or error
    """
    from darnit.server.tools.git_operations import create_remediation_branch_impl

    return create_remediation_branch_impl(
        branch_name=branch_name,
        local_path=local_path,
        base_branch=base_branch,
    )


def commit_remediation_changes(
    local_path: str = ".",
    message: str | None = None,
    add_all: bool = True,
) -> str:
    """
    Commit remediation changes with a descriptive message.

    Use this after applying remediations to commit the changes.

    Args:
        local_path: Path to the repository
        message: Commit message (auto-generated if not provided)
        add_all: Whether to stage all changes (default: True)

    Returns:
        Success message with commit info or error
    """
    from darnit.server.tools.git_operations import commit_remediation_changes_impl

    return commit_remediation_changes_impl(
        local_path=local_path,
        message=message,
        add_all=add_all,
    )


def create_remediation_pr(
    local_path: str = ".",
    title: str | None = None,
    body: str | None = None,
    base_branch: str | None = None,
    draft: bool = False,
) -> str:
    """
    Create a pull request for remediation changes.

    Use this after committing remediation changes to open a PR for review.

    Args:
        local_path: Path to the repository
        title: PR title (auto-generated if not provided)
        body: PR body/description (auto-generated if not provided)
        base_branch: Target branch for PR (default: repo default branch)
        draft: Create as draft PR (default: False)

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

    result = _audit_single_repo(owner, repo, level, tags_list)

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
    "confirm_project_context",
    "get_pending_context",
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
