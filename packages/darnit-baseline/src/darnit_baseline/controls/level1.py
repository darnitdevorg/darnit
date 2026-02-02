"""Level 1 OSPS Control Definitions for Sieve System (24 controls).

This module defines all Level 1 controls using the 4-phase sieve architecture:
1. DETERMINISTIC: File existence, API booleans, config lookups
2. PATTERN: Regex matching, content analysis
3. LLM: Ask calling LLM via consultation protocol
4. MANUAL: Always returns WARN with verification steps
"""

import glob as glob_module
import json
import os
import re
import subprocess
from collections.abc import Callable

from darnit.core.logging import get_logger
from darnit.sieve.models import (
    CheckContext,
    ControlSpec,
    PassOutcome,
    PassResult,
    VerificationPhase,
)
from darnit.sieve.passes import DeterministicPass, ManualPass, PatternPass
from darnit.sieve.project_context import get_context_value, is_context_confirmed
from darnit.sieve.registry import register_control

logger = get_logger("sieve.level1")
# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _gh_api(endpoint: str) -> dict | None:
    """Call GitHub API via gh CLI. Returns None on error."""
    try:
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"gh api timed out for {endpoint}")
        return None
    except FileNotFoundError:
        logger.debug("gh CLI not found - is it installed?")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"gh api returned invalid JSON for {endpoint}: {e}")
        return None
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"gh api failed for {endpoint}: {type(e).__name__}")
        return None


def _file_exists(local_path: str, *patterns: str) -> bool:
    """Check if any of the given file patterns exist."""
    for pattern in patterns:
        if "*" in pattern:
            matches = glob_module.glob(os.path.join(local_path, pattern), recursive=True)
            if matches:
                return True
        else:
            if os.path.exists(os.path.join(local_path, pattern)):
                return True
    return False


def _read_file(local_path: str, filename: str) -> str | None:
    """Read file content, return None if doesn't exist."""
    filepath = os.path.join(local_path, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding='utf-8', errors='ignore') as f:
                return f.read()
        except OSError as e:
            logger.debug(f"Could not read {filepath}: {type(e).__name__}")
            return None
    return None


# =============================================================================
# ACCESS CONTROL (AC) - 4 controls
# =============================================================================


def _create_mfa_check() -> Callable[[CheckContext], PassResult]:
    """Create API check for MFA requirement (OSPS-AC-01.01)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            # Check if owner is org or user
            user_data = _gh_api(f"/users/{ctx.owner}")
            if not user_data:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="Could not fetch owner data",
                )

            if user_data.get("type") == "Organization":
                org_data = _gh_api(f"/orgs/{ctx.owner}")
                if org_data:
                    mfa_required = org_data.get("two_factor_requirement_enabled")
                    if mfa_required is True:
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.PASS,
                            message="Organization MFA requirement is enabled",
                            evidence={"org": ctx.owner, "mfa_required": True},
                        )
                    elif mfa_required is False:
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.FAIL,
                            message="Organization MFA requirement is NOT enabled",
                            evidence={"org": ctx.owner, "mfa_required": False},
                        )

            # Personal account or cannot verify
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message="MFA status cannot be verified via API for personal accounts",
                evidence={"owner_type": user_data.get("type", "unknown")},
            )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"MFA check failed for {ctx.owner}: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check MFA: {e}",
            )

    return check


def _create_permissions_check() -> Callable[[CheckContext], PassResult]:
    """Create API check for default collaborator permissions (OSPS-AC-02.01).

    Spec: When a new collaborator is added, the version control system MUST
    require manual permission assignment, or restrict the collaborator
    permissions to the lowest available privileges by default.
    """

    def check(ctx: CheckContext) -> PassResult:
        try:
            # Check if owner is an organization
            user_data = _gh_api(f"/users/{ctx.owner}")
            if not user_data:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="Could not fetch owner data",
                )

            if user_data.get("type") == "Organization":
                # For orgs, check default_repository_permission
                org_data = _gh_api(f"/orgs/{ctx.owner}")
                if org_data:
                    default_perm = org_data.get("default_repository_permission", "read")
                    # "none" or "read" are acceptable (lowest privileges)
                    if default_perm in ("none", "read"):
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.PASS,
                            message=f"Org default permission is '{default_perm}' (lowest privilege)",
                            evidence={"default_repository_permission": default_perm},
                        )
                    else:
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.FAIL,
                            message=f"Org default permission is '{default_perm}' - should be 'read' or 'none'",
                            evidence={"default_repository_permission": default_perm},
                        )

            # For personal repos: GitHub requires explicit permission selection
            # when adding collaborators, so manual assignment is inherently required
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Personal repo: GitHub requires manual permission assignment when adding collaborators",
                evidence={"owner_type": "User"},
            )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Permissions check failed for {ctx.owner}: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check permissions: {e}",
            )

    return check


def _create_branch_protection_check() -> Callable[[CheckContext], PassResult]:
    """Create API check for branch protection (OSPS-AC-03.01)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            protection = _gh_api(
                f"/repos/{ctx.owner}/{ctx.repo}/branches/{ctx.default_branch}/protection"
            )

            if protection is None:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message=f"Branch '{ctx.default_branch}' is not protected",
                    evidence={"branch": ctx.default_branch},
                )

            has_pr_reviews = protection.get("required_pull_request_reviews") is not None
            has_restrictions = protection.get("restrictions") is not None

            if has_pr_reviews or has_restrictions:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Branch protection enabled on '{ctx.default_branch}'",
                    evidence={
                        "branch": ctx.default_branch,
                        "has_pr_reviews": has_pr_reviews,
                        "has_restrictions": has_restrictions,
                    },
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="Branch protection exists but doesn't prevent direct commits",
                    evidence={"branch": ctx.default_branch},
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Branch protection check failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check branch protection: {e}",
            )

    return check


def _create_branch_deletion_check() -> Callable[[CheckContext], PassResult]:
    """Create API check for branch deletion prevention (OSPS-AC-03.02)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            protection = _gh_api(
                f"/repos/{ctx.owner}/{ctx.repo}/branches/{ctx.default_branch}/protection"
            )

            if protection is None:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message=f"No protection rules for '{ctx.default_branch}'",
                    evidence={"branch": ctx.default_branch},
                )

            allow_deletions = protection.get("allow_deletions", {}).get("enabled", True)

            if not allow_deletions:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Deletion of '{ctx.default_branch}' is prevented",
                    evidence={"branch": ctx.default_branch, "allow_deletions": False},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message=f"Branch '{ctx.default_branch}' can be deleted",
                    evidence={"branch": ctx.default_branch, "allow_deletions": True},
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Branch deletion check failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not verify branch deletion protection: {e}",
            )

    return check


# Register AC controls
register_control(ControlSpec(
    control_id="OSPS-AC-01.01",
    level=1,
    domain="AC",
    name="MFARequired",
    description="Multi-factor authentication required for contributors",
    passes=[
        DeterministicPass(config_check=_create_mfa_check()),
        ManualPass(
            verification_steps=[
                "For organizations: Check Settings → Authentication security → Require two-factor authentication",
                "For personal accounts: Verify MFA is enabled in personal settings",
                "Ask repository administrators to confirm MFA status",
            ],
            verification_docs_url="https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication",
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-AC-02.01",
    level=1,
    domain="AC",
    name="MinimalPermissions",
    description="New collaborators require manual permission assignment or default to lowest privileges",
    passes=[
        DeterministicPass(config_check=_create_permissions_check()),
        ManualPass(
            verification_steps=[
                "For orgs: Check Settings → Member privileges → Base permissions (should be 'Read' or 'No permission')",
                "For personal repos: GitHub requires explicit permission selection when adding collaborators",
                "Review access levels for all collaborators",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-AC-03.01",
    level=1,
    domain="AC",
    name="PreventDirectCommits",
    description="Prevent direct commits to primary branch",
    passes=[
        DeterministicPass(config_check=_create_branch_protection_check()),
        ManualPass(
            verification_steps=[
                "Navigate to Repository Settings → Branches",
                "Check if branch protection rule exists for main/master",
                "Verify 'Require a pull request before merging' is enabled",
                "Confirm no bypasses are configured for regular contributors",
            ],
            verification_docs_url="https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches",
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-AC-03.02",
    level=1,
    domain="AC",
    name="PreventBranchDeletion",
    description="Prevent deletion of primary branch",
    passes=[
        DeterministicPass(config_check=_create_branch_deletion_check()),
        ManualPass(
            verification_steps=[
                "Navigate to Repository Settings → Branches",
                "Check branch protection rules for default branch",
                "Verify 'Allow deletions' is NOT enabled",
            ],
        ),
    ],
))


# =============================================================================
# BUILD & RELEASE (BR) - 5 controls
# =============================================================================

# Constants for workflow analysis
DANGEROUS_CONTEXTS = [
    "github.event.issue.title",
    "github.event.issue.body",
    "github.event.pull_request.title",
    "github.event.pull_request.body",
    "github.event.comment.body",
    "github.event.review.body",
    "github.event.pages.*.page_name",
    "github.event.commits.*.message",
    "github.event.commits.*.author.name",
    "github.event.commits.*.author.email",
]


def _create_workflow_injection_check() -> Callable[[CheckContext], PassResult]:
    """Check for injection vulnerabilities in workflows (OSPS-BR-01.01).

    Spec: When a CI/CD pipeline accepts an input parameter, that parameter MUST
    be sanitized and validated prior to use in the pipeline.
    """

    def check(ctx: CheckContext) -> PassResult:
        workflow_dir = os.path.join(ctx.local_path, ".github", "workflows")

        if not os.path.exists(workflow_dir):
            # Check if user has confirmed a different CI provider
            if is_context_confirmed(ctx.local_path, "ci_provider"):
                ci_provider = get_context_value(ctx.local_path, "ci_provider")
                if ci_provider == "none":
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.PASS,
                        message="No CI/CD used (confirmed in .project.yaml)",
                        evidence={"ci_provider": "none", "source": ".project.yaml"},
                    )
                elif ci_provider != "github":
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.INCONCLUSIVE,
                        message=f"Using {ci_provider} CI - manual review required for input sanitization",
                        evidence={
                            "ci_provider": ci_provider,
                            "source": ".project.yaml",
                            "manual_check": "Review CI config for unsanitized input parameters",
                        },
                    )

            # No confirmation - prompt user
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message="No GitHub Actions found. Please confirm CI provider in .project.yaml",
                evidence={
                    "has_workflows": False,
                    "needs_confirmation": True,
                    "confirmation_key": "ci_provider",
                    "confirmation_prompt": "What CI/CD system does this project use? (github, gitlab, jenkins, circleci, none, other)",
                },
            )

        injection_risks = []

        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            lines = content.splitlines()

                        in_run_block = False
                        for i, line in enumerate(lines):
                            stripped = line.strip()

                            if "run:" in stripped and not stripped.startswith("#"):
                                in_run_block = True
                            elif stripped.startswith("- name:") or stripped.startswith("- uses:"):
                                in_run_block = False

                            is_shell_context = in_run_block and ("run:" in stripped or "${{" in line)

                            if is_shell_context and "${{" in line:
                                if any(ctx_name in line for ctx_name in DANGEROUS_CONTEXTS):
                                    injection_risks.append(f"{file}:{i+1}")
                    except OSError as e:
                        logger.debug(f"Could not read workflow {filepath}: {type(e).__name__}")
                        continue

        if not injection_risks:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="No obvious input injection vulnerabilities in workflows",
                evidence={"workflows_checked": True, "risks_found": 0},
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.FAIL,
                message=f"Potential injection risks: {', '.join(injection_risks[:3])}",
                evidence={"risks": injection_risks},
            )

    return check


def _create_branch_name_injection_check() -> Callable[[CheckContext], PassResult]:
    """Check for branch name injection in workflows (OSPS-BR-01.02).

    Spec: When a CI/CD pipeline uses a branch name in its functionality, that
    name value MUST be sanitized and validated prior to use in the pipeline.
    """

    def check(ctx: CheckContext) -> PassResult:
        workflow_dir = os.path.join(ctx.local_path, ".github", "workflows")

        if not os.path.exists(workflow_dir):
            # Check if user has confirmed a different CI provider
            if is_context_confirmed(ctx.local_path, "ci_provider"):
                ci_provider = get_context_value(ctx.local_path, "ci_provider")
                if ci_provider == "none":
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.PASS,
                        message="No CI/CD used (confirmed in .project.yaml)",
                        evidence={"ci_provider": "none", "source": ".project.yaml"},
                    )
                elif ci_provider != "github":
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.INCONCLUSIVE,
                        message=f"Using {ci_provider} CI - manual review required for branch name sanitization",
                        evidence={"ci_provider": ci_provider, "source": ".project.yaml"},
                    )

            # No confirmation - prompt user
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message="No GitHub Actions found. Please confirm CI provider in .project.yaml",
                evidence={
                    "has_workflows": False,
                    "needs_confirmation": True,
                    "confirmation_key": "ci_provider",
                },
            )

        branch_name_risks = []

        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            lines = content.splitlines()

                        in_run_block = False
                        for i, line in enumerate(lines):
                            stripped = line.strip()

                            if "run:" in stripped:
                                in_run_block = True
                            elif stripped.startswith("- name:") or stripped.startswith("- uses:"):
                                in_run_block = False

                            if in_run_block and "${{" in line:
                                if "github.head_ref" in line or "github.ref_name" in line:
                                    branch_name_risks.append(f"{file}:{i+1}")
                    except OSError as e:
                        logger.debug(f"Could not read workflow {filepath}: {type(e).__name__}")
                        continue

        if not branch_name_risks:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Branch names appear to be safely handled in workflows",
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.FAIL,
                message=f"Branch name injection risks: {', '.join(branch_name_risks[:3])}",
                evidence={"risks": branch_name_risks},
            )

    return check


def _create_https_check() -> Callable[[CheckContext], PassResult]:
    """Check that official URIs use HTTPS (OSPS-BR-03.01, OSPS-BR-03.02)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            repo_data = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}")
            if not repo_data:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="Could not fetch repository data",
                )

            html_url = repo_data.get("html_url", "")
            homepage = repo_data.get("homepage", "")

            issues = []
            if html_url and not html_url.startswith("https://"):
                issues.append("Repository URL does not use HTTPS")
            if homepage and not homepage.startswith("https://"):
                issues.append(f"Homepage uses non-HTTPS: {homepage}")

            if not issues:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="All URIs use HTTPS",
                    evidence={"html_url": html_url, "homepage": homepage or "(not set)"},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="; ".join(issues),
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"HTTPS check failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not verify URL encryption: {e}",
            )

    return check


DANGEROUS_SECRET_FILES = [".env", ".env.local", ".env.production", "credentials.json", "secrets.json", "config/secrets.yml"]


def _create_secrets_check() -> Callable[[CheckContext], PassResult]:
    """Check for unencrypted secrets in VCS (OSPS-BR-07.01)."""

    def check(ctx: CheckContext) -> PassResult:
        secrets_found = []

        # Check for common secret files
        for df in DANGEROUS_SECRET_FILES:
            if _file_exists(ctx.local_path, df):
                secrets_found.append(df)

        # Check gitignore
        gitignore_content = _read_file(ctx.local_path, ".gitignore") or ""
        env_in_gitignore = ".env" in gitignore_content or "*.env" in gitignore_content

        if secrets_found:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.FAIL,
                message=f"Potential secrets in repo: {', '.join(secrets_found[:3])}",
                evidence={"secrets_found": secrets_found},
            )
        elif env_in_gitignore:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Secret files appear to be gitignored",
                evidence={"gitignore_has_env": True},
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message="Verify .gitignore excludes secret files",
            )

    return check


# Register BR controls
register_control(ControlSpec(
    control_id="OSPS-BR-01.01",
    level=1,
    domain="BR",
    name="InputSanitization",
    description="CI/CD input parameters are sanitized",
    passes=[
        DeterministicPass(config_check=_create_workflow_injection_check()),
        ManualPass(
            verification_steps=[
                "Review GitHub Actions workflows for ${{ }} expressions",
                "Check if user-controlled inputs are used in run: blocks",
                "Verify inputs are sanitized before shell execution",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-BR-01.02",
    level=1,
    domain="BR",
    name="BranchNameSanitization",
    description="Branch names are sanitized in CI/CD",
    passes=[
        DeterministicPass(config_check=_create_branch_name_injection_check()),
        ManualPass(
            verification_steps=[
                "Check workflows for github.head_ref or github.ref_name usage",
                "Verify branch names are quoted or escaped in shell commands",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-BR-03.01",
    level=1,
    domain="BR",
    name="HTTPSForOfficialURIs",
    description="Official URIs use HTTPS",
    passes=[
        DeterministicPass(config_check=_create_https_check()),
        ManualPass(
            verification_steps=[
                "Verify repository URL uses HTTPS",
                "Check homepage URL in repository settings",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-BR-03.02",
    level=1,
    domain="BR",
    name="HTTPSForDistribution",
    description="Distribution URIs use HTTPS",
    passes=[
        DeterministicPass(config_check=_create_https_check()),  # Same check
        ManualPass(
            verification_steps=[
                "Verify download links use HTTPS",
                "Check package registry URLs",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-BR-07.01",
    level=1,
    domain="BR",
    name="NoSecretsInVCS",
    description="Prevent unencrypted secrets in VCS",
    passes=[
        DeterministicPass(config_check=_create_secrets_check()),
        PatternPass(
            file_patterns=[".gitignore"],
            content_patterns={
                "env_excluded": r"(\.env|\.env\.\*|\*\.env|credentials|secrets)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check .gitignore for secret file patterns",
                "Search for hardcoded credentials in codebase",
                "Verify no .env files are committed",
            ],
        ),
    ],
))


# =============================================================================
# DOCUMENTATION (DO) - 2 controls
# =============================================================================

register_control(ControlSpec(
    control_id="OSPS-DO-01.01",
    level=1,
    domain="DO",
    name="UserGuides",
    description="Project documentation includes user guides for all basic functionality",
    passes=[
        DeterministicPass(
            file_must_exist=[
                "README.md",
                "README.rst",
                "README.txt",
                "README",
                "readme.md",
            ]
        ),
        PatternPass(
            file_patterns=["README.md", "README.rst", "docs/*.md"],
            content_patterns={
                "usage_docs": r"(usage|getting.started|how.to|install|quick.start|example)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Verify documentation includes user guides for basic functionality",
                "Check README contains usage instructions",
                "Confirm examples or getting started guide exists",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-DO-02.01",
    level=1,
    domain="DO",
    name="DefectReportingGuide",
    description="Instructions for reporting defects",
    passes=[
        DeterministicPass(
            file_must_exist=[
                ".github/ISSUE_TEMPLATE/bug_report.md",
                ".github/ISSUE_TEMPLATE/bug_report.yml",
                ".github/ISSUE_TEMPLATE/bug-report.md",
                ".github/ISSUE_TEMPLATE/bug-report.yml",
                ".github/ISSUE_TEMPLATE.md",
            ]
        ),
        PatternPass(
            file_patterns=["README.md", "CONTRIBUTING.md"],
            content_patterns={
                "bug_reporting": r"(bug|issue|report|defect|problem)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check for issue templates in .github/ISSUE_TEMPLATE/",
                "Verify README mentions how to report issues",
                "Confirm Issues are enabled on the repository",
            ],
        ),
    ],
))


# =============================================================================
# GOVERNANCE (GV) - 2 controls
# =============================================================================

def _create_discussion_check() -> Callable[[CheckContext], PassResult]:
    """Check for public discussion mechanisms (OSPS-GV-02.01)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            repo_data = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}")
            if not repo_data:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="Could not fetch repository data",
                )

            has_issues = repo_data.get("has_issues", False)
            has_discussions = repo_data.get("has_discussions", False)

            if has_issues or has_discussions:
                mechanisms = []
                if has_issues:
                    mechanisms.append("Issues")
                if has_discussions:
                    mechanisms.append("Discussions")
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Public discussion via: {', '.join(mechanisms)}",
                    evidence={"has_issues": has_issues, "has_discussions": has_discussions},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="No public discussion mechanism (Issues/Discussions disabled)",
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Discussion check failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check discussion mechanisms: {e}",
            )

    return check


register_control(ControlSpec(
    control_id="OSPS-GV-02.01",
    level=1,
    domain="GV",
    name="PublicDiscussion",
    description="Public discussion mechanisms available",
    passes=[
        DeterministicPass(config_check=_create_discussion_check()),
        ManualPass(
            verification_steps=[
                "Check repository Settings → Features",
                "Verify Issues or Discussions are enabled",
                "Confirm there's a way for the public to communicate",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-GV-03.01",
    level=1,
    domain="GV",
    name="ContributionProcess",
    description="Contribution process is documented",
    passes=[
        DeterministicPass(
            file_must_exist=[
                "CONTRIBUTING.md",
                ".github/CONTRIBUTING.md",
                "docs/CONTRIBUTING.md",
                "CONTRIBUTING",
            ]
        ),
        PatternPass(
            file_patterns=["README.md"],
            content_patterns={
                "contributing_section": r"(contribut|how to contribute|pull request|PR guidelines)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check for CONTRIBUTING.md file",
                "Verify README has contribution section",
                "Confirm PR process is documented",
            ],
        ),
    ],
))


# =============================================================================
# LEGAL (LE) - 4 controls
# =============================================================================

OSI_LICENSES = {
    "mit", "apache-2.0", "gpl-2.0", "gpl-3.0", "lgpl-2.1", "lgpl-3.0",
    "bsd-2-clause", "bsd-3-clause", "isc", "mpl-2.0", "unlicense",
    "artistic-2.0", "0bsd", "osl-3.0", "afl-3.0", "agpl-3.0",
}


def _detect_license_from_file(local_path: str) -> str | None:
    """Detect OSI license from local LICENSE file content."""
    for license_file in ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "license"]:
        content = _read_file(local_path, license_file)
        if content:
            content_lower = content.lower()
            # Check common OSI licenses
            if "mit license" in content_lower or "permission is hereby granted, free of charge" in content_lower:
                return "mit"
            elif "apache license" in content_lower and "version 2.0" in content_lower:
                return "apache-2.0"
            elif "gnu general public license" in content_lower:
                if "version 3" in content_lower:
                    return "gpl-3.0"
                elif "version 2" in content_lower:
                    return "gpl-2.0"
            elif "gnu lesser general public license" in content_lower:
                if "version 3" in content_lower:
                    return "lgpl-3.0"
                elif "version 2.1" in content_lower:
                    return "lgpl-2.1"
            elif "bsd" in content_lower:
                if "3-clause" in content_lower or "new bsd" in content_lower:
                    return "bsd-3-clause"
                elif "2-clause" in content_lower or "simplified" in content_lower:
                    return "bsd-2-clause"
            elif "mozilla public license" in content_lower and "2.0" in content_lower:
                return "mpl-2.0"
            elif "isc license" in content_lower:
                return "isc"
            elif "unlicense" in content_lower or "this is free and unencumbered software" in content_lower:
                return "unlicense"
    return None


def _create_license_check() -> Callable[[CheckContext], PassResult]:
    """Check for OSI-approved license (OSPS-LE-02.01, OSPS-LE-02.02).

    Tries GitHub API first, then falls back to local file detection.
    """

    def check(ctx: CheckContext) -> PassResult:
        # Try GitHub API first
        try:
            repo_data = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}")
            if repo_data:
                license_info = repo_data.get("license")
                if license_info:
                    spdx_id = license_info.get("spdx_id", "").lower()
                    if spdx_id in OSI_LICENSES:
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.PASS,
                            message=f"OSI-approved license: {spdx_id}",
                            evidence={"license": spdx_id, "source": "github_api"},
                        )
                    elif spdx_id and spdx_id != "noassertion":
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.FAIL,
                            message=f"License '{spdx_id}' may not be OSI-approved",
                            evidence={"license": spdx_id, "source": "github_api"},
                        )
                    # noassertion or empty - fall through to local check
        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"GitHub API license check failed: {type(e).__name__}: {e}")
            # Fall through to local file check

        # Fallback: Check local LICENSE file
        detected = _detect_license_from_file(ctx.local_path)
        if detected and detected in OSI_LICENSES:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message=f"OSI-approved license detected from file: {detected}",
                evidence={"license": detected, "source": "local_file"},
            )

        # Check if LICENSE file exists at all
        if _file_exists(ctx.local_path, "LICENSE", "LICENSE.*", "COPYING", "license"):
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message="LICENSE file found but type not auto-detected",
                evidence={"has_license_file": True},
            )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="No license detected",
        )

    return check


register_control(ControlSpec(
    control_id="OSPS-LE-02.01",
    level=1,
    domain="LE",
    name="OSILicenseSource",
    description="OSI-approved license for source code",
    passes=[
        DeterministicPass(config_check=_create_license_check()),
        ManualPass(
            verification_steps=[
                "Check LICENSE file in repository",
                "Verify license is OSI-approved",
                "See https://opensource.org/licenses",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-LE-02.02",
    level=1,
    domain="LE",
    name="OSILicenseReleases",
    description="OSI-approved license for releases",
    passes=[
        DeterministicPass(config_check=_create_license_check()),  # Same check
        ManualPass(
            verification_steps=[
                "Verify releases include license file",
                "Check package manifest includes license",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-LE-03.01",
    level=1,
    domain="LE",
    name="LicenseFileExists",
    description="License file in repository",
    passes=[
        DeterministicPass(
            file_must_exist=[
                "LICENSE",
                "LICENSE.md",
                "LICENSE.txt",
                "COPYING",
                "COPYING.md",
                "license",
                "License.md",
            ]
        ),
        ManualPass(
            verification_steps=[
                "Check repository root for LICENSE file",
                "Verify license text is complete",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-LE-03.02",
    level=1,
    domain="LE",
    name="LicenseInReleases",
    description="License included in releases",
    passes=[
        DeterministicPass(
            file_must_exist=[
                "LICENSE",
                "LICENSE.md",
                "LICENSE.txt",
                "COPYING",
            ]
        ),
        ManualPass(
            verification_steps=[
                "Check that LICENSE is included in release artifacts",
                "Verify package manifest references license",
            ],
        ),
    ],
))


# =============================================================================
# QUALITY ASSURANCE (QA) - 6 controls
# =============================================================================

def _is_github_com_remote(local_path: str) -> bool:
    """Check if the git remote is on github.com (not GitHub Enterprise)."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
            cwd=local_path
        )
        if result.returncode == 0:
            url = result.stdout.strip().lower()
            # Check for github.com (not enterprise instances)
            return "github.com" in url
    except (subprocess.SubprocessError, OSError):
        pass
    return False


def _create_visibility_check() -> Callable[[CheckContext], PassResult]:
    """Check repository visibility (OSPS-QA-01.01, OSPS-QA-01.02).

    Tries GitHub API first, then infers from remote URL and accessibility.
    """

    def check(ctx: CheckContext) -> PassResult:
        # Try GitHub API first
        try:
            repo_data = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}")
            if repo_data:
                is_private = repo_data.get("private", True)
                if not is_private:
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.PASS,
                        message="Repository is publicly readable",
                        evidence={"private": False, "source": "github_api"},
                    )
                else:
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.FAIL,
                        message="Repository is private",
                        evidence={"private": True, "source": "github_api"},
                    )
        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"GitHub API visibility check failed: {type(e).__name__}: {e}")
            # Fall through to inference

        # Fallback: If we're on github.com and can access the repo locally,
        # it's very likely public (private repos need auth to clone)
        if _is_github_com_remote(ctx.local_path):
            # The fact that we can run this audit on a github.com repo
            # strongly suggests it's public (otherwise couldn't clone without auth)
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Repository accessible on github.com (inferred public)",
                evidence={"source": "git_remote_inference", "remote_host": "github.com"},
            )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.INCONCLUSIVE,
            message="Could not determine repository visibility",
        )

    return check


DEPENDENCY_FILES = [
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "Pipfile", "Pipfile.lock", "py.project.yaml", "poetry.lock",
    "Gemfile", "Gemfile.lock", "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock", "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "composer.lock", "mix.exs", "mix.lock",
]


def _create_dependency_check() -> Callable[[CheckContext], PassResult]:
    """Check for dependency manifest (OSPS-QA-02.01)."""

    def check(ctx: CheckContext) -> PassResult:
        found_files = [f for f in DEPENDENCY_FILES if _file_exists(ctx.local_path, f)]

        if found_files:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message=f"Dependency files found: {', '.join(found_files[:3])}",
                evidence={"dependency_files": found_files},
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message="No standard dependency manifest found",
            )

    return check


def _create_subproject_check() -> Callable[[CheckContext], PassResult]:
    """Check for subproject documentation (OSPS-QA-04.01).

    Spec: While active, the project documentation MUST contain a list of any
    codebases that are considered subprojects.

    This check uses .project.yaml context if available to determine if the
    project has subprojects. If not confirmed, it will prompt the user.
    """

    def check(ctx: CheckContext) -> PassResult:
        # First check if user has confirmed whether they have subprojects
        if is_context_confirmed(ctx.local_path, "has_subprojects"):
            has_subprojects_confirmed = get_context_value(ctx.local_path, "has_subprojects")
            if not has_subprojects_confirmed:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="No subprojects (confirmed in .project.yaml)",
                    evidence={"has_subprojects": False, "source": ".project.yaml"},
                )
            # User confirmed they DO have subprojects - check if documented
            readme_content = _read_file(ctx.local_path, "README.md") or ""
            if re.search(r'(subproject|workspace|package|monorepo|related.*repo)', readme_content, re.IGNORECASE):
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="Subprojects documented in README",
                    evidence={"has_subprojects": True, "documented": True},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="Project has subprojects (per .project.yaml) but they are not documented",
                    evidence={"has_subprojects": True, "documented": False},
                )

        # No user confirmation - try to auto-detect
        has_subprojects_detected = _file_exists(
            ctx.local_path, "packages/*", "apps/*", "modules/*", "workspaces/*"
        )

        if has_subprojects_detected:
            # Detected subprojects - check if documented
            readme_content = _read_file(ctx.local_path, "README.md") or ""
            if re.search(r'(subproject|workspace|package|monorepo)', readme_content, re.IGNORECASE):
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="Subprojects detected and documented in README",
                    evidence={"has_subprojects": True, "auto_detected": True},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="Subprojects detected but not documented in README",
                    evidence={"has_subprojects": True, "auto_detected": True},
                )

        # No subprojects detected - but we can't be sure
        # Return WARN to prompt user confirmation
        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.INCONCLUSIVE,
            message="No subprojects detected. Please confirm in .project.yaml: has_subprojects = false",
            evidence={
                "has_subprojects": None,
                "needs_confirmation": True,
                "confirmation_key": "has_subprojects",
                "confirmation_prompt": "Does this project have any subprojects or related repositories?",
            },
        )

    return check


BINARY_EXTENSIONS = [".exe", ".dll", ".so", ".dylib", ".a", ".o", ".obj", ".class", ".jar", ".war", ".pyc", ".pyo"]


def _create_binary_check() -> Callable[[CheckContext], PassResult]:
    """Check for binary files in VCS (OSPS-QA-05.01, OSPS-QA-05.02)."""

    def check(ctx: CheckContext) -> PassResult:
        binary_files = []
        skip_dirs = [".git", "node_modules", "vendor", "__pycache__", "venv", ".venv"]

        for ext in BINARY_EXTENSIONS:
            matches = glob_module.glob(os.path.join(ctx.local_path, f"**/*{ext}"), recursive=True)
            for m in matches:
                if not any(skip in m for skip in skip_dirs):
                    binary_files.append(os.path.basename(m))

        if not binary_files:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="No generated executables found in repository",
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.FAIL,
                message=f"Binary files found: {', '.join(binary_files[:5])}",
                evidence={"binary_files": binary_files},
            )

    return check


register_control(ControlSpec(
    control_id="OSPS-QA-01.01",
    level=1,
    domain="QA",
    name="PublicReadable",
    description="Repository is publicly readable",
    passes=[
        DeterministicPass(config_check=_create_visibility_check()),
        ManualPass(
            verification_steps=[
                "Check repository visibility in Settings",
                "Verify repository is not private",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-01.02",
    level=1,
    domain="QA",
    name="PublicCommitHistory",
    description="Commit history is publicly visible",
    passes=[
        DeterministicPass(config_check=_create_visibility_check()),  # Same check
        ManualPass(
            verification_steps=[
                "Verify commit history is accessible",
                "Check that repository is not private",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-02.01",
    level=1,
    domain="QA",
    name="DependencyList",
    description="Dependency list for direct dependencies",
    passes=[
        DeterministicPass(config_check=_create_dependency_check()),
        ManualPass(
            verification_steps=[
                "Check for package.json, requirements.txt, go.mod, etc.",
                "Verify dependencies are listed with versions",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-04.01",
    level=1,
    domain="QA",
    name="SubprojectList",
    description="Project documentation lists any codebases considered subprojects",
    passes=[
        DeterministicPass(config_check=_create_subproject_check()),
        ManualPass(
            verification_steps=[
                "Check if monorepo/workspace structure exists",
                "Verify any subprojects or additional repositories are documented",
                "Confirm README or docs list related codebases",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-05.01",
    level=1,
    domain="QA",
    name="NoGeneratedExecutables",
    description="No generated executables in VCS",
    passes=[
        DeterministicPass(config_check=_create_binary_check()),
        ManualPass(
            verification_steps=[
                "Search for .exe, .dll, .so, .class files",
                "Verify build artifacts are gitignored",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-05.02",
    level=1,
    domain="QA",
    name="NoUnreviewableBinaries",
    description="No unreviewable binary artifacts",
    passes=[
        DeterministicPass(config_check=_create_binary_check()),  # Same check
        ManualPass(
            verification_steps=[
                "Review any binary files in repository",
                "Verify binaries have source available",
            ],
        ),
    ],
))


# =============================================================================
# VULNERABILITY MANAGEMENT (VM) - 1 control
# =============================================================================

register_control(ControlSpec(
    control_id="OSPS-VM-02.01",
    level=1,
    domain="VM",
    name="SecurityContacts",
    description="Project documentation includes security contacts for vulnerability reporting",
    passes=[
        DeterministicPass(
            file_must_exist=[
                "SECURITY.md",
                ".github/SECURITY.md",
                "docs/SECURITY.md",
                "SECURITY.rst",
                "SECURITY",
            ]
        ),
        PatternPass(
            file_patterns=["SECURITY.md", ".github/SECURITY.md", "README.md"],
            content_patterns={
                "security_contact": r"(report|contact|email|security@|vulnerability|disclose)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Verify SECURITY.md or equivalent exists",
                "Check that security contact information is documented",
                "Confirm vulnerability reporting process is described",
            ],
        ),
    ],
))
