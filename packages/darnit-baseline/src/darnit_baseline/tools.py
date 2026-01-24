"""MCP tool handlers for OpenSSF Baseline.

This module provides standalone tool functions that can be registered
with the darnit MCP server via TOML configuration.

Each function is designed to be used as an MCP tool handler.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union, List


def audit_openssf_baseline(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    local_path: str = ".",
    level: int = 3,
    tags: Optional[Union[str, List[str]]] = None,
    output_format: str = "markdown",
    auto_init_config: bool = True,
    attest: bool = False,
    sign_attestation: bool = True,
    staging: bool = False,
    use_sieve: bool = True,
) -> str:
    """
    Run a comprehensive OpenSSF Baseline audit on a repository.

    This checks compliance with OSPS v2025.10.10 across 61 controls at 3 maturity levels.

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
        use_sieve: Use progressive verification pipeline. Default: True

    Returns:
        Formatted audit report with compliance status and remediation instructions
    """
    from darnit.config import (
        load_effective_config_by_name,
        load_controls_from_effective,
    )
    from darnit.filtering import parse_tags_arg, filter_controls
    from darnit.sieve import SieveOrchestrator, CheckContext
    from darnit.tools.audit import format_results_markdown

    # Resolve path
    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    # Auto-detect owner/repo from git
    detected_owner, detected_repo = _detect_owner_repo(repo_path)
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

    # Apply tag-based filtering if specified
    if tags:
        # Normalize tags to a list
        if isinstance(tags, str):
            tags_list = [tags]
        else:
            tags_list = list(tags)
        tag_filters = parse_tags_arg(tags_list)
        controls = filter_controls(controls, filters=tag_filters)

    if not controls:
        return "❌ No controls loaded"

    # Run checks via sieve
    orchestrator = SieveOrchestrator()
    default_branch = _detect_default_branch(repo_path)

    results = []
    for control in controls:
        context = CheckContext(
            owner=owner,
            repo=repo,
            local_path=str(repo_path),
            default_branch=default_branch,
            control_id=control.control_id,
            control_metadata={
                "name": control.name,
                "description": control.description,
            },
        )
        result = orchestrator.verify(control, context)
        results.append(result.to_legacy_dict())

    # Calculate summary (uppercase keys for format_results_markdown compatibility)
    summary = {
        "total": len(results),
        "PASS": len([r for r in results if r.get("status") == "PASS"]),
        "FAIL": len([r for r in results if r.get("status") == "FAIL"]),
        "WARN": len([r for r in results if r.get("status") == "WARN"]),
        "N/A": len([r for r in results if r.get("status") == "NA"]),
        "ERROR": len([r for r in results if r.get("status") == "ERROR"]),
        "PENDING_LLM": len([r for r in results if r.get("status") == "PENDING_LLM"]),
    }

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
        return format_results_markdown(
            owner=owner,
            repo=repo,
            results=results,
            summary=summary,
            compliance={},
            level=level,
        )


def list_available_checks() -> str:
    """
    List all available OpenSSF Baseline checks organized by level.

    Returns:
        Formatted list of all 61 OSPS controls across 3 levels
    """
    from darnit_baseline.rules.catalog import OSPS_RULES

    checks = {"level1": [], "level2": [], "level3": []}

    for rule_id, rule in OSPS_RULES.items():
        level = rule.get("level", 1)
        level_key = f"level{level}"
        if level_key in checks:
            checks[level_key].append({
                "id": rule_id,
                "name": rule.get("name", rule_id),
                "description": rule.get("short", ""),
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
    from darnit.config import get_project_config as _get_config, config_exists

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
    owner: Optional[str] = None,
    repo: Optional[str] = None,
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
    from darnit_baseline.remediation.actions import create_security_policy as _create

    repo_path = Path(local_path).resolve()

    # Auto-detect owner/repo
    detected_owner, detected_repo = _detect_owner_repo(repo_path)
    owner = owner or detected_owner
    repo = repo or detected_repo

    try:
        result = _create(
            local_path=str(repo_path),
            owner=owner,
            repo=repo,
            template=template,
        )
        return result
    except Exception as e:
        return f"❌ Error creating SECURITY.md: {e}"


def enable_branch_protection(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: str = "main",
    required_approvals: int = 1,
    enforce_admins: bool = True,
    require_pull_request: bool = True,
    require_status_checks: bool = False,
    status_checks: Optional[list] = None,
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
    detected_owner, detected_repo = _detect_owner_repo(repo_path)
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
    project_name: Optional[str] = None,
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
    from darnit.config import init_project_config as _init, config_exists

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
    has_subprojects: Optional[bool] = None,
    has_releases: Optional[bool] = None,
    is_library: Optional[bool] = None,
    has_compiled_assets: Optional[bool] = None,
    ci_provider: Optional[str] = None,
) -> str:
    """
    Record user-confirmed project context in .project.yaml.

    Some controls depend on context that can't be auto-detected.

    Args:
        local_path: Path to the repository
        has_subprojects: Does this project have subprojects?
        has_releases: Does this project make official releases?
        is_library: Is this a library/framework consumed by other projects?
        has_compiled_assets: Does this project release compiled binaries?
        ci_provider: CI/CD system (github, gitlab, jenkins, circleci, azure, travis, none, other)

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
    )


# =============================================================================
# Threat Model & Attestation Tools
# =============================================================================


def generate_threat_model(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    local_path: str = ".",
    output_format: str = "markdown",
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

    Returns:
        Threat model report with identified threats and recommendations
    """
    from darnit.threat_model import (
        detect_frameworks,
        discover_all_assets,
        discover_injection_sinks,
        analyze_stride_threats,
        identify_control_gaps,
        generate_markdown_threat_model,
        generate_sarif_threat_model,
        generate_json_summary,
    )

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    detected_owner, detected_repo = _detect_owner_repo(repo_path)
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

        # Identify control gaps
        control_gaps = identify_control_gaps(assets, threats)

        # Generate output
        if output_format == "sarif":
            return json.dumps(generate_sarif_threat_model(str(repo_path), threats), indent=2)
        elif output_format == "json":
            return json.dumps(generate_json_summary(str(repo_path), frameworks, assets, threats, control_gaps), indent=2)
        else:
            return generate_markdown_threat_model(str(repo_path), assets, threats, control_gaps, frameworks)
    except Exception as e:
        return f"❌ Error generating threat model: {e}"


def generate_attestation(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    local_path: str = ".",
    level: int = 3,
    sign: bool = True,
    staging: bool = False,
    output_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    use_sieve: bool = True,
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
        use_sieve: Use progressive verification pipeline. Default: True

    Returns:
        JSON attestation and path to saved file
    """
    from darnit.attestation import generate_attestation as _generate

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    detected_owner, detected_repo = _detect_owner_repo(repo_path)
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
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    categories: Optional[list] = None,
    dry_run: bool = True,
) -> str:
    """
    Apply automated remediations for failed audit controls.

    Available categories:
    - branch_protection: Enable branch protection
    - status_checks: Configure required status checks
    - security_policy: Create SECURITY.md
    - codeowners: Create CODEOWNERS
    - governance: Create GOVERNANCE.md
    - contributing: Create CONTRIBUTING.md
    - dco_enforcement: Configure DCO
    - bug_report_template: Create bug report template
    - dependabot: Configure Dependabot
    - support_doc: Create SUPPORT.md

    Args:
        local_path: ABSOLUTE path to repo
        owner: GitHub org/user (auto-detected if not provided)
        repo: Repository name (auto-detected if not provided)
        categories: List of remediation categories, or ["all"] for all
        dry_run: If True (default), show what would be changed without applying

    Returns:
        Summary of applied or planned remediations
    """
    from darnit_baseline.remediation import remediate_audit_findings as apply_remediations

    repo_path = Path(local_path).resolve()
    if not repo_path.exists():
        return f"❌ Error: Repository path not found: {repo_path}"

    detected_owner, detected_repo = _detect_owner_repo(repo_path)
    owner = owner or detected_owner
    repo = repo or detected_repo

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
    base_branch: Optional[str] = None,
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
    message: Optional[str] = None,
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
    title: Optional[str] = None,
    body: Optional[str] = None,
    base_branch: Optional[str] = None,
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
    github_org: Optional[str] = None,
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


def _detect_owner_repo(repo_path: Path) -> tuple[str, str]:
    """Detect owner/repo from git remote."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            if "github.com" in url:
                parts = url.replace(".git", "").split("/")
                if len(parts) >= 2:
                    return parts[-2], parts[-1]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return "unknown", repo_path.name


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


__all__ = [
    # Audit
    "audit_openssf_baseline",
    "list_available_checks",
    # Configuration
    "get_project_config",
    "init_project_config",
    "confirm_project_context",
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
