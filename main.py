"""Darnit MCP Server - Entry Point.

This module provides the MCP server entry point for the darnit compliance audit framework.
The included darnit-baseline implementation provides OpenSSF Baseline (OSPS v2025.10.10) checks.

=============================================================================
IMPORTANT: .project.yaml Specification (for AI Agents)
=============================================================================

The `.project.yaml` file is a USER-MAINTAINED CONFIGURATION file, not a cache
or results store. It follows the CNCF .project specification with OpenSSF
Baseline extensions and should ONLY contain:

ALLOWED in .project.yaml:
- Project metadata (name, type, description)
- File location pointers (paths to SECURITY.md, LICENSE, etc.)
- Control overrides with user-provided reasoning
- CI/CD configuration references
- Documentation cross-references

NEVER write to .project.yaml:
- Audit results (pass/fail counts, control lists)
- Timestamps or run metadata
- Auto-generated evidence
- Compliance percentages or scores

THE GOLDEN RULE:
  .project.yaml changes when the USER changes something about their project.
  .project.yaml does NOT change when an audit runs.

Audit results should be:
1. Returned directly from tool calls (markdown, JSON, SARIF)
2. Saved to dedicated report files (e.g., .darnit/reports/)
3. Stored as attestations for cryptographic proof

See example.project.yaml for the correct schema.
=============================================================================
"""

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

# =============================================================================
# IMPORTS FROM darnit FRAMEWORK
# =============================================================================
from darnit.core.logging import get_logger

logger = get_logger("main")

# Core models and utilities
# Attestation - import only what's used by MCP tools
from darnit.attestation import generate_attestation_from_results
from darnit.config.discovery import (
    discover_ci_config,
    discover_files,
    discover_project_name,
)

# Configuration
from darnit.config.loader import (
    load_project_config,
    save_project_config,
)
from darnit.core.models import AuditResult
from darnit.core.utils import (
    detect_repo_from_git,
    file_contains,
    file_exists,
    get_git_commit,
    get_git_ref,
    gh_api,
    gh_api_safe,
    make_result,
    read_file,
    validate_local_path,
)

# Remediation (framework utilities)
from darnit.remediation import enable_branch_protection as _enable_branch_protection_impl

# Server tools (extracted implementations)
from darnit.server import (
    commit_remediation_changes_impl,
    confirm_project_context_impl,
    create_remediation_branch_impl,
    create_remediation_pr_impl,
    create_test_repository_impl,
    get_remediation_status_impl,
)

# validate_reference available if needed but not currently used
# Threat Model - import only what's used by MCP tools
from darnit.threat_model import (
    analyze_stride_threats,
    detect_frameworks,
    discover_all_assets,
    discover_injection_sinks,
    generate_json_summary,
    generate_markdown_threat_model,
    generate_sarif_threat_model,
    identify_control_gaps,
)

# Tools - import only what's used by MCP tools
from darnit.tools import (
    SERVER_NAME,
    calculate_compliance,
    format_results_markdown,
    prepare_audit,
    run_checks,
    summarize_results,
)
from darnit.tools import (
    list_available_checks as get_available_checks,
)

# Configuration models
from darnit_baseline.config.mappings import (
    ProjectConfig,
    ResourceReference,
)

# Formatters (OSPS-specific)
from darnit_baseline.formatters import (
    generate_sarif_audit,
)

# Remediation (OSPS-specific orchestrator)
from darnit_baseline.remediation import (
    remediate_audit_findings as _remediate_audit_findings_impl,
)

# =============================================================================
# IMPORTS FROM darnit-baseline IMPLEMENTATION
# =============================================================================
# Remediation actions
from darnit_baseline.remediation.actions import (
    create_security_policy as _create_security_policy_impl,
)

# =============================================================================
# MCP SERVER INSTANCE
# =============================================================================

mcp = FastMCP(SERVER_NAME)

# =============================================================================
# HELPER FUNCTIONS (Aliases for backward compatibility)
# =============================================================================

# Use package functions with underscore prefix for internal use
_gh_api = gh_api
_gh_api_safe = gh_api_safe
_validate_local_path = validate_local_path
_detect_repo_from_git = detect_repo_from_git
_file_exists = file_exists
_file_contains = file_contains
_read_file = read_file
_result = make_result
_get_git_commit = get_git_commit
_get_git_ref = get_git_ref


def _run_baseline_checks(
    owner: str | None,
    repo: str | None,
    local_path: str,
    level: int = 3,
    auto_init_config: bool = True,
    use_sieve: bool = True,
) -> tuple[AuditResult | None, str | None]:
    """Run baseline checks and return audit result or error.

    Args:
        auto_init_config: If True (default), create .project.yaml if it doesn't exist.
        use_sieve: Use progressive verification pipeline (sieve) instead of legacy checks.
                   Default True. Set to False to use legacy check functions.
    """
    # Prepare audit
    owner, repo, resolved_path, default_branch, error = prepare_audit(owner, repo, local_path)
    if error:
        return None, error

    # Run checks
    all_results, skipped = run_checks(owner, repo, resolved_path, default_branch, level, use_sieve=use_sieve)

    # Calculate summary
    summary = summarize_results(all_results)
    compliance = calculate_compliance(all_results, level)

    # Get git info
    commit = get_git_commit(resolved_path)
    ref = get_git_ref(resolved_path)

    # Load or create project config
    project_config = None
    config_was_created = False
    config_error = None

    try:
        project_config = load_project_config(resolved_path)
    except Exception as e:
        # Error loading config
        logger.debug(f"Could not load project config: {e}")

    # Config doesn't exist - create if auto_init_config is True
    if project_config is None and auto_init_config:
        try:
            # Auto-detect project name
            project_name = discover_project_name(resolved_path) or os.path.basename(resolved_path)

            # Discover files
            discovered = discover_files(resolved_path)
            ci_config = discover_ci_config(resolved_path)

            # Build section dicts from discovered files
            def build_section(section_name: str) -> dict[str, Any]:
                section_refs = {}
                prefix = f"{section_name}."
                for ref_path, file_path in discovered.items():
                    if ref_path.startswith(prefix):
                        key = ref_path[len(prefix):]
                        section_refs[key] = ResourceReference(ref_type="path", path=file_path)
                return section_refs

            # Create config
            project_config = ProjectConfig(
                name=project_name,
                project_type="software",
                security=build_section("security"),
                governance=build_section("governance"),
                legal=build_section("legal"),
                artifacts=build_section("artifacts"),
                quality=build_section("quality"),
                documentation=build_section("documentation"),
                dependencies=build_section("dependencies"),
                testing=build_section("testing"),
                releases=build_section("releases"),
                ci=ci_config,
            )

            # Save config
            save_project_config(project_config, resolved_path)
            config_was_created = True
            logger.info(f"Created .project.yaml for {project_name}")

        except (OSError, PermissionError) as e:
            config_error = f"Failed to create .project.yaml: {e}"
            logger.warning(config_error)
        except Exception as e:
            config_error = f"Error creating .project.yaml: {e}"
            logger.warning(config_error)

    # Create audit result
    from datetime import datetime
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
        config_was_created=config_was_created,
        config_was_updated=False,
        config_changes=[],
        skipped_controls=skipped,
        commit=commit,
        ref=ref,
    )

    # Add config creation error as a warning in results if it failed
    if config_error:
        result.all_results.append({
            "id": "CONFIG-INIT",
            "status": "WARN",
            "level": 0,
            "details": config_error,
        })

    return result, None


def _generate_attestation_from_results(
    audit_result: AuditResult,
    sign: bool = True,
    staging: bool = False,
    output_path: str | None = None,
    output_dir: str | None = None
) -> str:
    """Generate attestation from audit results."""
    return generate_attestation_from_results(
        audit_result=audit_result,
        sign=sign,
        staging=staging,
        output_path=output_path,
        output_dir=output_dir
    )


# =============================================================================
# MCP TOOLS - AUDIT
# =============================================================================

@mcp.tool()
def audit_openssf_baseline(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    level: int = 3,
    output_format: str = "markdown",
    auto_init_config: bool = True,
    attest: bool = False,
    sign_attestation: bool = True,
    staging: bool = False,
    use_sieve: bool = True
) -> str:
    """
    Run a comprehensive OpenSSF Baseline audit on a repository.

    This checks compliance with OSPS v2025.10.10 across 61 controls at 3 maturity levels.

    IMPORTANT - REMEDIATION:
    To fix audit failures, use the MCP tools provided by this server:
    - `remediate_audit_findings()` - Auto-fix multiple issues at once
    - `enable_branch_protection()` - Configure branch protection rules
    - `create_security_policy()` - Generate SECURITY.md

    **DO NOT run `gh api`, `git push`, or other shell commands directly.**
    Always use the MCP tools for remediation to ensure proper error handling.

    IMPORTANT - RESULTS STORAGE:
    Audit results are RETURNED by this function, not stored in .project.yaml.
    The .project.yaml file is a user-maintained configuration with a defined schema.
    Never write audit results, scores, or pass/fail lists to .project.yaml.

    To persist results, use:
    - The returned output directly (markdown, JSON, SARIF)
    - The attest=True option for cryptographic attestations
    - Save to a dedicated reports directory (e.g., .darnit/reports/)

    Args:
        owner: GitHub Org/User (auto-detected from git if not provided)
        repo: Repository Name (auto-detected from git if not provided)
        local_path: ABSOLUTE path to repo (e.g., "/Users/you/projects/repo")
        level: Maximum OSPS level to check (1, 2, or 3). Default: 3
        output_format: Output format - "markdown", "json", or "sarif". Default: "markdown"
        auto_init_config: Create .project.yaml if missing. Default: True
        attest: Generate in-toto attestation after audit. Default: False
        sign_attestation: Sign attestation with Sigstore. Default: True
        staging: Use Sigstore staging environment. Default: False
        use_sieve: Use progressive verification pipeline (sieve) instead of legacy checks.
                   Default: True. Set to False to use legacy check functions for comparison.

    Returns:
        Formatted audit report with compliance status and remediation instructions
    """
    # Run checks
    audit_result, error = _run_baseline_checks(
        owner=owner,
        repo=repo,
        local_path=local_path,
        level=level,
        auto_init_config=auto_init_config,
        use_sieve=use_sieve
    )

    if error:
        return f"❌ Error: {error}"

    # Build config status message
    config_status = ""
    if audit_result.config_was_created:
        config_status = "📄 Created .project.yaml (auto_init_config=true)\n\n"
    elif audit_result.project_config:
        config_status = "📄 Using existing .project.yaml\n\n"

    # Format output
    if output_format == "json":
        output = json.dumps({
            "owner": audit_result.owner,
            "repo": audit_result.repo,
            "level": level,
            "summary": audit_result.summary,
            "compliance": audit_result.level_compliance,
            "results": audit_result.all_results,
            "timestamp": audit_result.timestamp,
            "config_created": audit_result.config_was_created,
        }, indent=2)
    elif output_format == "sarif":
        # Generate SARIF format with full rules and locations
        sarif = generate_sarif_audit(audit_result)
        output = json.dumps(sarif, indent=2)
    else:
        # Default markdown
        output = config_status + format_results_markdown(
            owner=audit_result.owner,
            repo=audit_result.repo,
            results=audit_result.all_results,
            summary=audit_result.summary,
            compliance=audit_result.level_compliance,
            level=level,
            local_path=local_path,
        )

    # Generate attestation if requested
    if attest:
        attestation_output = _generate_attestation_from_results(
            audit_result=audit_result,
            sign=sign_attestation,
            staging=staging
        )
        output += f"\n\n---\n\n## Attestation\n\n{attestation_output}"

    return output


@mcp.tool()
def list_available_checks() -> str:
    """
    List all available OpenSSF Baseline checks organized by level.

    Returns:
        Formatted list of all 61 OSPS controls across 3 levels
    """
    checks = get_available_checks()
    return json.dumps(checks, indent=2)


# =============================================================================
# MCP TOOLS - CONFIGURATION
# =============================================================================

@mcp.tool()
def get_project_config(local_path: str = ".") -> str:
    """
    Get the current project configuration for OpenSSF Baseline.

    Returns the .project.yaml configuration which contains ONLY:
    - Project metadata (name, type)
    - File location pointers
    - Control overrides with reasoning
    - CI/CD configuration references

    NOTE: .project.yaml is a USER-MAINTAINED config file with a defined schema.
    Never write audit results, scores, or timestamps to .project.yaml.
    Use audit_openssf_baseline to get compliance results.

    Args:
        local_path: Path to repository

    Returns:
        Current configuration or instructions to create one
    """
    resolved_path, error = _validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    try:
        config = load_project_config(resolved_path)
        if config:
            return json.dumps({
                "project_name": config.project_name,
                "project_type": config.project_type,
                "file_locations": config.file_locations,
                "control_overrides": config.control_overrides,
            }, indent=2)
        else:
            return "No .project.yaml found. Run audit_openssf_baseline to create one."
    except Exception as e:
        return f"❌ Error loading config: {e}"


@mcp.tool()
def init_project_config(
    local_path: str = ".",
    project_name: str | None = None,
    project_type: str = "software"
) -> str:
    """
    Initialize a new OpenSSF Baseline configuration file (.project.yaml).

    Creates a .project.yaml with discovered file locations. This file is a
    USER-MAINTAINED configuration with a defined schema. It should contain:
    - Project metadata (name, type)
    - Pointers to documentation files (SECURITY.md, LICENSE, etc.)
    - Control overrides with human-provided reasoning
    - CI/CD configuration references

    IMPORTANT: .project.yaml should NEVER contain:
    - Audit results or scores
    - Pass/fail lists
    - Timestamps or run metadata

    Args:
        local_path: Path to repository
        project_name: Project name (auto-detected if not provided)
        project_type: Type of project (software, library, framework, specification)

    Returns:
        Success message with created configuration
    """
    resolved_path, error = _validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    # Auto-detect project name
    if not project_name:
        project_name = discover_project_name(resolved_path) or os.path.basename(resolved_path)

    # Discover files - returns dict like {"security.policy": "SECURITY.md", ...}
    discovered = discover_files(resolved_path)

    # Discover CI config
    ci_config = discover_ci_config(resolved_path)

    # Build section dicts from discovered files
    def build_section(section_name: str) -> dict[str, Any]:
        """Extract discovered files for a section."""
        section_refs = {}
        prefix = f"{section_name}."
        for ref_path, file_path in discovered.items():
            if ref_path.startswith(prefix):
                key = ref_path[len(prefix):]
                section_refs[key] = ResourceReference(ref_type="path", path=file_path)
        return section_refs

    # Create config with properly structured sections
    config = ProjectConfig(
        name=project_name,
        project_type=project_type,
        security=build_section("security"),
        governance=build_section("governance"),
        legal=build_section("legal"),
        artifacts=build_section("artifacts"),
        quality=build_section("quality"),
        documentation=build_section("documentation"),
        dependencies=build_section("dependencies"),
        testing=build_section("testing"),
        releases=build_section("releases"),
        ci=ci_config,
    )

    # Save
    try:
        save_project_config(config, resolved_path)
        return f"✅ Created .project.yaml for {project_name}"
    except Exception as e:
        return f"❌ Error saving config: {e}"


# =============================================================================
# MCP TOOLS - THREAT MODEL
# =============================================================================

@mcp.tool()
def generate_threat_model(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    output_format: str = "markdown"
) -> str:
    """
    Generate a STRIDE-based threat model for a repository.

    Analyzes the codebase for:
    - Entry points (API routes, server actions)
    - Authentication mechanisms
    - Data stores and sensitive data
    - Potential injection vulnerabilities
    - Hardcoded secrets

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: ABSOLUTE path to repo
        output_format: Output format - "markdown", "sarif", or "json"

    Returns:
        Threat model report with identified threats and recommendations
    """
    # Validate path
    resolved_path, error = _validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    # Auto-detect owner/repo
    if not owner or not repo:
        detected = _detect_repo_from_git(resolved_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            owner = owner or "unknown"
            repo = repo or os.path.basename(resolved_path)

    # Detect frameworks
    frameworks = detect_frameworks(resolved_path)

    # Discover assets
    assets = discover_all_assets(resolved_path, frameworks)

    # Discover injection sinks
    injection_sinks = discover_injection_sinks(resolved_path)

    # Analyze threats
    threats = analyze_stride_threats(assets, injection_sinks)

    # Identify control gaps
    control_gaps = identify_control_gaps(assets, threats)

    # Generate output
    if output_format == "sarif":
        return json.dumps(generate_sarif_threat_model(resolved_path, threats), indent=2)
    elif output_format == "json":
        return json.dumps(generate_json_summary(resolved_path, frameworks, assets, threats, control_gaps), indent=2)
    else:
        return generate_markdown_threat_model(resolved_path, assets, threats, control_gaps, frameworks)


# =============================================================================
# MCP TOOLS - ATTESTATION
# =============================================================================

@mcp.tool()
def generate_attestation(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    level: int = 3,
    sign: bool = True,
    staging: bool = False,
    output_path: str | None = None,
    output_dir: str | None = None,
    use_sieve: bool = True
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
    # Run checks
    audit_result, error = _run_baseline_checks(
        owner=owner,
        repo=repo,
        local_path=local_path,
        level=level,
        auto_init_config=True,
        use_sieve=use_sieve
    )

    if error:
        return json.dumps({"error": error}, indent=2)

    # Generate attestation
    return _generate_attestation_from_results(
        audit_result=audit_result,
        sign=sign,
        staging=staging,
        output_path=output_path,
        output_dir=output_dir
    )


# =============================================================================
# MCP TOOLS - REMEDIATION
# =============================================================================
# Implementation is in baseline_mcp.remediation module.
# These are thin MCP tool wrappers that delegate to the module implementations.


@mcp.tool()
def create_security_policy(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    template: str = "standard"
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
    return _create_security_policy_impl(
        owner=owner,
        repo=repo,
        local_path=local_path,
        template=template
    )


@mcp.tool()
def enable_branch_protection(
    owner: str | None = None,
    repo: str | None = None,
    branch: str = "main",
    required_approvals: int = 1,
    enforce_admins: bool = True,
    require_pull_request: bool = True,
    require_status_checks: bool = False,
    status_checks: list[str] | None = None,
    local_path: str = ".",
    dry_run: bool = False
) -> str:
    """
    Enable branch protection rules to satisfy OSPS-AC-03.01, OSPS-AC-03.02, and OSPS-QA-07.01.

    Args:
        owner: GitHub Org/User (auto-detected from git if not provided)
        repo: Repository Name (auto-detected from git if not provided)
        branch: Branch to protect (default: main)
        required_approvals: Number of required PR approvals (default: 1)
        enforce_admins: Apply rules to admins too (default: True)
        require_pull_request: Require pull requests for changes (default: True).
            Set to False to allow direct pushes while still protecting against
            force-push and deletion. **NOTE**: Disabling this means OSPS-QA-07.01
            (peer review) will NOT be satisfied - suitable for solo maintainers
            but not fully OpenSSF Baseline compliant.
        require_status_checks: Require status checks to pass (default: False)
        status_checks: List of required status check contexts (e.g., ["ci/test"])
        local_path: Local path to repo for auto-detection (default: ".")
        dry_run: If True, show what would be configured without making changes (default: False)

    Returns:
        Success message with configuration details or error message
    """
    return _enable_branch_protection_impl(
        owner=owner,
        repo=repo,
        branch=branch,
        required_approvals=required_approvals,
        enforce_admins=enforce_admins,
        require_pull_request=require_pull_request,
        require_status_checks=require_status_checks,
        status_checks=status_checks,
        local_path=local_path,
        dry_run=dry_run
    )


@mcp.tool()
def remediate_audit_findings(
    local_path: str = ".",
    owner: str | None = None,
    repo: str | None = None,
    categories: list[str] | None = None,
    dry_run: bool = True
) -> str:
    """
    Apply automated remediations for failed audit controls.

    This tool can fix common compliance gaps automatically. By default it runs in
    dry_run mode to show what would be changed without making modifications.

    **Available remediation categories:**
    - `branch_protection`: Enable branch protection (OSPS-AC-03.01, AC-03.02, QA-07.01)
    - `status_checks`: Configure required status checks (OSPS-QA-03.01)
    - `security_policy`: Create SECURITY.md (OSPS-VM-01.01, VM-02.01, VM-03.01)
    - `codeowners`: Create CODEOWNERS (OSPS-GV-01.01, GV-01.02, GV-04.01)
    - `governance`: Create GOVERNANCE.md (OSPS-GV-01.01, GV-01.02)
    - `contributing`: Create CONTRIBUTING.md (OSPS-GV-03.01, GV-03.02)
    - `dco_enforcement`: Configure DCO (OSPS-LE-01.01)
    - `bug_report_template`: Create bug report template (OSPS-DO-02.01)
    - `dependabot`: Configure Dependabot (OSPS-VM-05.*)
    - `support_doc`: Create SUPPORT.md (OSPS-DO-03.01)

    Args:
        local_path: ABSOLUTE path to repo
        owner: GitHub org/user (auto-detected if not provided)
        repo: Repository name (auto-detected if not provided)
        categories: List of remediation categories to apply, or ["all"] for all available
        dry_run: If True (default), show what would be changed without applying

    Returns:
        Summary of applied or planned remediations
    """
    return _remediate_audit_findings_impl(
        local_path=local_path,
        owner=owner,
        repo=repo,
        categories=categories,
        dry_run=dry_run
    )


# =============================================================================
# MCP TOOLS - GIT OPERATIONS
# =============================================================================


@mcp.tool()
def create_remediation_branch(
    branch_name: str = "fix/openssf-baseline-compliance",
    local_path: str = ".",
    base_branch: str | None = None
) -> str:
    """
    Create a new branch for remediation work.

    Use this tool to create a branch before applying remediations, so changes
    can be reviewed via pull request.

    **DO NOT run `git checkout -b` or `git branch` directly.** Use this tool.

    Args:
        branch_name: Name for the new branch (default: fix/openssf-baseline-compliance)
        local_path: Path to the repository
        base_branch: Branch to base off of (default: current branch)

    Returns:
        Success message with branch name or error
    """
    return create_remediation_branch_impl(branch_name, local_path, base_branch)


@mcp.tool()
def commit_remediation_changes(
    local_path: str = ".",
    message: str | None = None,
    add_all: bool = True
) -> str:
    """
    Commit remediation changes with a descriptive message.

    Use this tool after applying remediations to commit the changes.

    **DO NOT run `git add` or `git commit` directly.** Use this tool.

    Args:
        local_path: Path to the repository
        message: Commit message (auto-generated if not provided)
        add_all: Whether to stage all changes (default: True)

    Returns:
        Success message with commit info or error
    """
    return commit_remediation_changes_impl(local_path, message, add_all)


@mcp.tool()
def create_remediation_pr(
    local_path: str = ".",
    title: str | None = None,
    body: str | None = None,
    base_branch: str | None = None,
    draft: bool = False
) -> str:
    """
    Create a pull request for remediation changes.

    Use this tool after committing remediation changes to open a PR for review.

    **DO NOT run `gh pr create` directly.** Use this tool.

    Args:
        local_path: Path to the repository
        title: PR title (auto-generated if not provided)
        body: PR body/description (auto-generated if not provided)
        base_branch: Target branch for PR (default: repo default branch)
        draft: Create as draft PR (default: False)

    Returns:
        Success message with PR URL or error
    """
    return create_remediation_pr_impl(local_path, title, body, base_branch, draft)


@mcp.tool()
def get_remediation_status(
    local_path: str = "."
) -> str:
    """
    Get the current git status for remediation work.

    Use this to check the state of the repository before/after remediation.

    Args:
        local_path: Path to the repository

    Returns:
        Current branch, uncommitted changes, and next steps
    """
    return get_remediation_status_impl(local_path)


# =============================================================================
# MCP TOOLS - TEST REPOSITORY
# =============================================================================

@mcp.tool()
def create_test_repository(
    repo_name: str = "baseline-test-repo",
    parent_dir: str = ".",
    github_org: str | None = None,
    create_github: bool = True,
    make_template: bool = False
) -> str:
    """
    Create a minimal test repository that intentionally fails all OpenSSF Baseline controls.

    This is useful for:
    - Testing the baseline-mcp audit tools
    - Learning what each control requires
    - Practicing implementing security controls from scratch

    The created repo has working code but NO security/governance artifacts:
    - No LICENSE, README, SECURITY.md, CONTRIBUTING.md
    - No CI/CD workflows
    - No branch protection
    - Minimal .gitignore (missing security exclusions)

    Args:
        repo_name: Name of the repository (default: baseline-test-repo)
        parent_dir: Directory to create the repo in (default: current directory)
        github_org: GitHub org/username (auto-detected if not provided)
        create_github: Whether to create a GitHub repo (requires gh CLI)
        make_template: Whether to make it a GitHub template repository

    Returns:
        Success message with next steps
    """
    return create_test_repository_impl(repo_name, parent_dir, github_org, create_github, make_template)


# =============================================================================
# MCP TOOLS - PROJECT CONTEXT CONFIRMATION
# =============================================================================


@mcp.tool()
def confirm_project_context(
    local_path: str = ".",
    has_subprojects: bool | None = None,
    has_releases: bool | None = None,
    is_library: bool | None = None,
    has_compiled_assets: bool | None = None,
    ci_provider: str | None = None,
) -> str:
    """
    Record user-confirmed project context in .project.yaml.

    Some controls depend on context that can't be auto-detected (e.g., whether
    a project has subprojects, or which CI system is used). Use this tool to
    record your answers so the audit can give accurate results.

    Args:
        local_path: Path to the repository
        has_subprojects: Does this project have subprojects or related repositories?
                        Set to False if this is a standalone project.
        has_releases: Does this project make official releases?
        is_library: Is this a library/framework consumed by other projects?
        has_compiled_assets: Does this project release compiled binaries?
        ci_provider: What CI/CD system does this project use?
                    Options: "github", "gitlab", "jenkins", "circleci", "azure", "travis", "none", "other"

    Returns:
        Confirmation of what was recorded
    """
    return confirm_project_context_impl(
        local_path, has_subprojects, has_releases, is_library, has_compiled_assets, ci_provider
    )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    mcp.run()
