"""Level 3 OSPS Control Definitions for Sieve System (20 controls).

Level 3 represents the highest security requirements for critical open source projects.
"""

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

logger = get_logger("sieve.level3")


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
        logger.warning(f"GitHub API call timed out for {endpoint}")
        return None
    except FileNotFoundError:
        logger.debug("gh CLI not found - is it installed?")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"GitHub API returned invalid JSON for {endpoint}: {e}")
        return None
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"GitHub API call failed for {endpoint}: {type(e).__name__}")
        return None


def _file_exists(local_path: str, *patterns: str) -> bool:
    """Check if any of the given file patterns exist."""
    import glob as glob_module
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
# ACCESS CONTROL (AC) - 1 control
# =============================================================================


def _create_minimum_privileges_check() -> Callable[[CheckContext], PassResult]:
    """Check CI/CD uses minimum privileges (OSPS-AC-04.02).

    Spec: When a job is assigned permissions in a CI/CD pipeline, the source code
    or configuration MUST only assign the minimum privileges necessary for the
    corresponding activity.
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
                        message=f"Using {ci_provider} CI - manually verify jobs use minimum required privileges",
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

        critical_issues = []
        workflows_without_permissions = []

        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    content = _read_file(root, file) or ""
                    content_lower = content.lower()

                    # Critical: permissions: write-all
                    if "permissions: write-all" in content_lower:
                        critical_issues.append(f"{file} (uses write-all)")
                        continue

                    has_permissions_block = "permissions:" in content_lower
                    if not has_permissions_block:
                        workflows_without_permissions.append(file)
                        continue

                    # Check for dangerous patterns
                    if "pull_request_target" in content_lower and "checkout" in content_lower:
                        if "head.sha" in content_lower or "head_ref" in content_lower:
                            critical_issues.append(f"{file} (pull_request_target with PR checkout)")

                    if "contents: write" in content_lower:
                        legitimate_patterns = [
                            "auto-update", "release", "deploy", "publish",
                            "gh-pages", "changelog", "docs", "git push"
                        ]
                        is_legitimate = any(p in content_lower for p in legitimate_patterns)
                        if not is_legitimate and "pull_request_target" in content_lower:
                            critical_issues.append(f"{file} (contents:write with pull_request_target)")

        if critical_issues:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.FAIL,
                message=f"Critical permission issues: {', '.join(critical_issues[:3])}",
                evidence={"issues": critical_issues},
            )
        elif workflows_without_permissions:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message=f"Workflows use appropriate permissions ({len(workflows_without_permissions)} lack explicit blocks)",
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Workflows use appropriately scoped permissions",
            )

    return check


register_control(ControlSpec(
    control_id="OSPS-AC-04.02",
    level=3,
    domain="AC",
    name="MinimumPrivileges",
    description="CI/CD pipelines use minimum privileges",
    passes=[
        DeterministicPass(config_check=_create_minimum_privileges_check()),
        ManualPass(
            verification_steps=[
                "Review workflow permissions blocks",
                "Verify no workflows use 'write-all'",
                "Check pull_request_target workflows for security issues",
            ],
        ),
    ],
))


# =============================================================================
# BUILD & RELEASE (BR) - 2 controls
# =============================================================================


def _create_versioned_assets_check() -> Callable[[CheckContext], PassResult]:
    """Check release assets are versioned (OSPS-BR-02.02)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            releases = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}/releases?per_page=1")

            if not releases or not releases[0].get("assets"):
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,  # N/A
                    message="No release assets found",
                )

            assets = releases[0]["assets"]
            tag = releases[0].get("tag_name", "")

            named_correctly = all(
                tag in a.get("name", "") or "latest" not in a.get("name", "").lower()
                for a in assets
            )

            if named_correctly:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="Release assets are clearly versioned",
                    evidence={"tag": tag},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="Some assets may not be clearly versioned",
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Could not verify release assets: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not verify release assets: {e}",
            )

    return check


register_control(ControlSpec(
    control_id="OSPS-BR-02.02",
    level=3,
    domain="BR",
    name="VersionedAssets",
    description="Release assets are clearly associated with version",
    passes=[
        DeterministicPass(config_check=_create_versioned_assets_check()),
        ManualPass(
            verification_steps=[
                "Check release assets include version in filename",
                "Verify no 'latest' naming that could cause confusion",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-BR-07.02",
    level=3,
    domain="BR",
    name="SecretsManagementPolicy",
    description="Secrets management policy is documented",
    passes=[
        PatternPass(
            file_patterns=["SECURITY.md", "CONTRIBUTING.md", ".github/SECURITY.md"],
            content_patterns={
                "secrets_policy": r"(secret|credential|key management|rotation|vault)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check SECURITY.md for secrets management policy",
                "Verify key rotation procedures are documented",
            ],
        ),
    ],
))


# =============================================================================
# DOCUMENTATION (DO) - 4 controls
# =============================================================================


register_control(ControlSpec(
    control_id="OSPS-DO-03.01",
    level=3,
    domain="DO",
    name="ReleaseIntegrityInstructions",
    description="Instructions to verify release integrity",
    passes=[
        PatternPass(
            file_patterns=["README.md", "SECURITY.md", "docs/INSTALL.md"],
            content_patterns={
                "verification": r"(verify|signature|checksum|sha256|gpg|pgp|signing)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check README for checksum verification instructions",
                "Verify GPG signing documentation exists",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-DO-03.02",
    level=3,
    domain="DO",
    name="AuthorIdentityVerification",
    description="Instructions to verify release author identity",
    passes=[
        PatternPass(
            file_patterns=["README.md", "SECURITY.md"],
            content_patterns={
                "author_verification": r"(gpg|pgp|sign|author|identity|key)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check for GPG signing key documentation",
                "Verify author identity verification process",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-DO-04.01",
    level=3,
    domain="DO",
    name="SupportScope",
    description="Support scope and duration is documented",
    passes=[
        DeterministicPass(
            file_must_exist=["SUPPORT.md", "docs/SUPPORT.md"]
        ),
        PatternPass(
            file_patterns=["README.md", "SUPPORT.md"],
            content_patterns={
                "support_policy": r"(support|maintenance|lts|long.term|eol|end.of.life)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check for SUPPORT.md file",
                "Verify maintenance policy is documented",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-DO-05.01",
    level=3,
    domain="DO",
    name="EndOfSupportNotice",
    description="End of security updates notice is documented",
    passes=[
        PatternPass(
            file_patterns=["SUPPORT.md", "README.md", "SECURITY.md"],
            content_patterns={
                "eol_policy": r"(end.of.support|end.of.life|eol|deprecat|unsupported|no longer maintained)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check SUPPORT.md for EOL policy",
                "Verify deprecated versions are documented",
            ],
        ),
    ],
))


# =============================================================================
# GOVERNANCE (GV) - 1 control
# =============================================================================


register_control(ControlSpec(
    control_id="OSPS-GV-04.01",
    level=3,
    domain="GV",
    name="CollaboratorReviewPolicy",
    description="Collaborator vetting policy is documented",
    passes=[
        PatternPass(
            file_patterns=["GOVERNANCE.md", "SECURITY.md"],
            content_patterns={
                "review_policy": r"(collaborator|maintainer|review|vetting|access.review)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check GOVERNANCE.md for access review policy",
                "Verify maintainer vetting process is documented",
            ],
        ),
    ],
))


# =============================================================================
# QUALITY ASSURANCE (QA) - 5 controls
# =============================================================================


def _create_sbom_check() -> Callable[[CheckContext], PassResult]:
    """Check for SBOM in releases (OSPS-QA-02.02)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            releases = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}/releases?per_page=1")

            if not releases:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,  # N/A
                    message="No releases found",
                )

            assets = releases[0].get("assets", [])
            has_sbom = any(
                "sbom" in a.get("name", "").lower() or
                "bom" in a.get("name", "").lower() or
                a.get("name", "").endswith((".spdx", ".spdx.json", ".cdx.json"))
                for a in assets
            )

            if has_sbom:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="SBOM included in release",
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="No SBOM found in release assets",
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Could not verify SBOM: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not verify SBOM: {e}",
            )

    return check


def _create_subproject_security_check() -> Callable[[CheckContext], PassResult]:
    """Check subprojects have equivalent security (OSPS-QA-04.02)."""

    def check(ctx: CheckContext) -> PassResult:
        has_subprojects = _file_exists(ctx.local_path, "packages/*", "apps/*", "modules/*")

        if not has_subprojects:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,  # N/A
                message="No subprojects detected",
            )

        has_shared_config = _file_exists(ctx.local_path, ".github/workflows/*.yml")
        if has_shared_config:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Subprojects share CI/security config",
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message="Verify subprojects have equivalent security",
            )

    return check


def _create_approval_check() -> Callable[[CheckContext], PassResult]:
    """Check for non-author human approval requirement (OSPS-QA-07.01).

    Spec: When a commit is made to the primary branch, the project's version
    control system MUST require at least one non-author human approval of the
    changes before merging.
    """

    def check(ctx: CheckContext) -> PassResult:
        try:
            protection = _gh_api(
                f"/repos/{ctx.owner}/{ctx.repo}/branches/{ctx.default_branch}/protection"
            )

            if protection:
                pr_reviews = protection.get("required_pull_request_reviews", {})
                approvals = pr_reviews.get("required_approving_review_count", 0)

                if approvals >= 1:
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.PASS,
                        message=f"Requires {approvals} non-author human approval(s) before merge",
                        evidence={"required_approvals": approvals},
                    )
                else:
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.FAIL,
                        message="No required human approvals configured",
                    )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="No branch protection configured - human approval not enforced",
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Could not verify approval requirements: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not verify approval requirements: {e}",
            )

    return check


register_control(ControlSpec(
    control_id="OSPS-QA-02.02",
    level=3,
    domain="QA",
    name="SBOMInReleases",
    description="SBOM included in compiled releases",
    passes=[
        DeterministicPass(config_check=_create_sbom_check()),
        ManualPass(
            verification_steps=[
                "Check release assets for SBOM files",
                "Verify SPDX or CycloneDX format",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-04.02",
    level=3,
    domain="QA",
    name="SubprojectSecurity",
    description="Subprojects have equivalent security requirements",
    passes=[
        DeterministicPass(config_check=_create_subproject_security_check()),
        ManualPass(
            verification_steps=[
                "Verify all subprojects use shared CI config",
                "Check security requirements are consistent",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-06.02",
    level=3,
    domain="QA",
    name="TestDocumentation",
    description="Test instructions are documented",
    passes=[
        PatternPass(
            file_patterns=["README.md", "CONTRIBUTING.md"],
            content_patterns={
                "test_docs": r"(how to.*test|running tests|test.*instruction)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check README for test instructions",
                "Verify CONTRIBUTING.md explains testing",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-06.03",
    level=3,
    domain="QA",
    name="TestPolicyForChanges",
    description="Test requirements for contributions are documented",
    passes=[
        PatternPass(
            file_patterns=["CONTRIBUTING.md"],
            content_patterns={
                "test_requirements": r"(test.*required|must.*test|test.*coverage)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check CONTRIBUTING.md for test requirements",
                "Verify coverage expectations are documented",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-07.01",
    level=3,
    domain="QA",
    name="NonAuthorHumanApproval",
    description="At least one non-author human approval required before merging to primary branch",
    passes=[
        DeterministicPass(config_check=_create_approval_check()),
        ManualPass(
            verification_steps=[
                "Check branch protection settings require PR reviews",
                "Verify at least 1 approving review is required",
                "Confirm approvals must come from humans (not bots)",
            ],
        ),
    ],
))


# =============================================================================
# SECURITY ARCHITECTURE (SA) - 1 control
# =============================================================================


THREAT_MODEL_DOCS = [
    "THREAT_MODEL.md", "docs/THREAT_MODEL.md", "docs/security/threat-model.md",
    "SECURITY.md", "docs/SECURITY.md",
]


register_control(ControlSpec(
    control_id="OSPS-SA-03.02",
    level=3,
    domain="SA",
    name="ThreatModeling",
    description="Threat modeling documentation exists",
    passes=[
        DeterministicPass(
            file_must_exist=["THREAT_MODEL.md", "docs/THREAT_MODEL.md", "docs/security/threat-model.md"]
        ),
        PatternPass(
            file_patterns=["SECURITY.md", ".github/SECURITY.md"],
            content_patterns={
                "threat_model": r"(threat.model|attack.surface|attack.vector)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check for THREAT_MODEL.md",
                "Verify SECURITY.md discusses threat modeling",
            ],
        ),
    ],
))


# =============================================================================
# VULNERABILITY MANAGEMENT (VM) - 6 controls
# =============================================================================


register_control(ControlSpec(
    control_id="OSPS-VM-04.02",
    level=3,
    domain="VM",
    name="VEXPolicy",
    description="VEX policy documented in SECURITY.md",
    passes=[
        # Primary: VEX policy section in SECURITY.md (preferred)
        PatternPass(
            file_patterns=["SECURITY.md", ".github/SECURITY.md"],
            content_patterns={
                "vex_policy": r"(vex|vulnerability.exploitability|exploitability.exchange|affected.*not.affected)",
            },
            pass_if_any_match=True,
        ),
        # Secondary: VEX documents exist (acceptable but policy is preferred)
        DeterministicPass(
            file_must_exist=["*.vex.json", "vex.json", ".vex/*", "vex/*.json"]
        ),
        ManualPass(
            verification_steps=[
                "Verify SECURITY.md has a VEX policy section",
                "Policy should explain how VEX statements will be handled",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-VM-05.01",
    level=3,
    domain="VM",
    name="SCARemediationPolicy",
    description="SCA remediation threshold policy is documented",
    passes=[
        PatternPass(
            file_patterns=["SECURITY.md", ".github/SECURITY.md"],
            content_patterns={
                "sca_policy": r"(sca|software.composition|dependency.*scan|remediation.*policy)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check SECURITY.md for SCA policy",
                "Verify remediation thresholds are documented",
            ],
        ),
    ],
))


def _create_sca_check() -> Callable[[CheckContext], PassResult]:
    """Check for pre-release SCA (OSPS-VM-05.02)."""

    def check(ctx: CheckContext) -> PassResult:
        workflow_dir = os.path.join(ctx.local_path, ".github", "workflows")

        # Check for Kusari or other SCA apps
        try:
            check_runs = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}/check-runs?per_page=10")
            if check_runs and check_runs.get("check_runs"):
                for check_run in check_runs["check_runs"]:
                    app_name = check_run.get("app", {}).get("slug", "").lower()
                    if "kusari" in app_name:
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.PASS,
                            message="Pre-release SCA check found (Kusari)",
                        )
        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Could not check for Kusari SCA app: {type(e).__name__}: {e}")

        # Check workflows for SCA tools
        sca_patterns = [
            (r'dependency-review-action', "dependency-review-action"),
            (r'snyk', "Snyk"),
            (r'trivy', "Trivy"),
            (r'grype', "Grype"),
            (r'anchore', "Anchore"),
            (r'dependabot', "Dependabot"),
        ]

        if os.path.exists(workflow_dir):
            for root, _, files in os.walk(workflow_dir):
                for file in files:
                    if file.endswith(('.yml', '.yaml')):
                        content = _read_file(root, file) or ""

                        for pattern, tool_name in sca_patterns:
                            if re.search(pattern, content, re.IGNORECASE):
                                # Check if runs on PRs
                                if re.search(r'pull_request', content, re.IGNORECASE):
                                    return PassResult(
                                        phase=VerificationPhase.DETERMINISTIC,
                                        outcome=PassOutcome.PASS,
                                        message=f"Pre-release SCA check found ({tool_name})",
                                    )

        # No GitHub Actions SCA found - check CI provider context
        if is_context_confirmed(ctx.local_path, "ci_provider"):
            ci_provider = get_context_value(ctx.local_path, "ci_provider")
            if ci_provider == "none":
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="No CI/CD configured - SCA check not applicable",
                    evidence={"ci_provider": "none"},
                )
            elif ci_provider != "github":
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message=f"Using {ci_provider} CI - manually verify pre-release SCA is configured",
                    evidence={"ci_provider": ci_provider},
                )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.INCONCLUSIVE,
            message="No pre-release SCA workflow found. Please confirm CI provider in .project.yaml",
            evidence={"needs_confirmation": True, "confirmation_key": "ci_provider"},
        )

    return check


def _create_dependency_scanning_check() -> Callable[[CheckContext], PassResult]:
    """Check for automated dependency scanning (OSPS-VM-05.03)."""

    def check(ctx: CheckContext) -> PassResult:
        # Dependabot/Renovate are CI-agnostic tools
        has_dependabot = _file_exists(ctx.local_path, ".github/dependabot.yml", ".github/dependabot.yaml")
        has_renovate = _file_exists(ctx.local_path, "renovate.json", ".renovaterc", ".renovaterc.json")

        if has_dependabot:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Dependabot configured for dependency scanning",
            )
        elif has_renovate:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Renovate configured for dependency scanning",
            )

        # Check GitHub workflows for scanning tools
        workflow_dir = os.path.join(ctx.local_path, ".github", "workflows")
        if os.path.exists(workflow_dir):
            for root, _, files in os.walk(workflow_dir):
                for file in files:
                    if file.endswith(('.yml', '.yaml')):
                        content = _read_file(root, file) or ""
                        if re.search(r'(snyk|trivy|grype|dependency.check|npm audit|safety check)', content, re.IGNORECASE):
                            return PassResult(
                                phase=VerificationPhase.DETERMINISTIC,
                                outcome=PassOutcome.PASS,
                                message="Dependency scanning found in CI",
                            )

        # Check other CI providers for dependency scanning
        ci_configs = {
            "gitlab": [".gitlab-ci.yml"],
            "jenkins": ["Jenkinsfile", "jenkins.yml"],
            "circleci": [".circleci/config.yml"],
            "azure": ["azure-pipelines.yml", ".azure-pipelines.yml"],
            "travis": [".travis.yml"],
        }

        for provider, config_files in ci_configs.items():
            for config_file in config_files:
                config_path = os.path.join(ctx.local_path, config_file)
                if os.path.exists(config_path):
                    content = _read_file(ctx.local_path, config_file) or ""
                    if re.search(r'(snyk|trivy|grype|dependency.check|npm audit|safety check|pip-audit|bundler-audit)', content, re.IGNORECASE):
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.PASS,
                            message=f"Dependency scanning found in {provider} CI",
                            evidence={"ci_provider": provider},
                        )

        # No scanning found - check CI provider context
        if is_context_confirmed(ctx.local_path, "ci_provider"):
            ci_provider = get_context_value(ctx.local_path, "ci_provider")
            if ci_provider == "none":
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="No CI/CD configured - dependency scanning check not applicable",
                    evidence={"ci_provider": "none"},
                )
            elif ci_provider not in ["github", "gitlab", "jenkins", "circleci", "azure", "travis"]:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message=f"Using {ci_provider} CI - manually verify dependency scanning is configured",
                    evidence={"ci_provider": ci_provider},
                )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="No automated dependency scanning found. Configure Dependabot, Renovate, or add scanning to CI",
        )

    return check


def _create_sast_check() -> Callable[[CheckContext], PassResult]:
    """Check for automated SAST in CI (OSPS-VM-06.02)."""

    def check(ctx: CheckContext) -> PassResult:
        sast_patterns = [
            r'codeql', r'semgrep', r'sonar', r'bandit',
            r'brakeman', r'gosec', r'eslint.*security',
            r'security-code-scan', r'checkmarx',
        ]

        # Check GitHub Actions workflows
        workflow_dir = os.path.join(ctx.local_path, ".github", "workflows")
        if os.path.exists(workflow_dir):
            for root, _, files in os.walk(workflow_dir):
                for file in files:
                    if file.endswith(('.yml', '.yaml')):
                        content = _read_file(root, file) or ""
                        for pattern in sast_patterns:
                            if re.search(pattern, content, re.IGNORECASE):
                                return PassResult(
                                    phase=VerificationPhase.DETERMINISTIC,
                                    outcome=PassOutcome.PASS,
                                    message=f"Automated SAST found in CI ({pattern})",
                                )

        # Check other CI providers for SAST tools
        ci_configs = {
            "gitlab": [".gitlab-ci.yml"],
            "jenkins": ["Jenkinsfile", "jenkins.yml"],
            "circleci": [".circleci/config.yml"],
            "azure": ["azure-pipelines.yml", ".azure-pipelines.yml"],
            "travis": [".travis.yml"],
        }

        for provider, config_files in ci_configs.items():
            for config_file in config_files:
                config_path = os.path.join(ctx.local_path, config_file)
                if os.path.exists(config_path):
                    content = _read_file(ctx.local_path, config_file) or ""
                    for pattern in sast_patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            return PassResult(
                                phase=VerificationPhase.DETERMINISTIC,
                                outcome=PassOutcome.PASS,
                                message=f"Automated SAST found in {provider} CI ({pattern})",
                                evidence={"ci_provider": provider},
                            )

        # No SAST found - check CI provider context
        if is_context_confirmed(ctx.local_path, "ci_provider"):
            ci_provider = get_context_value(ctx.local_path, "ci_provider")
            if ci_provider == "none":
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="No CI/CD configured - SAST check not applicable",
                    evidence={"ci_provider": "none"},
                )
            elif ci_provider not in ["github", "gitlab", "jenkins", "circleci", "azure", "travis"]:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message=f"Using {ci_provider} CI - manually verify SAST is configured",
                    evidence={"ci_provider": ci_provider},
                )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.INCONCLUSIVE,
            message="No automated SAST found in CI. Please confirm CI provider in .project.yaml",
            evidence={"needs_confirmation": True, "confirmation_key": "ci_provider"},
        )

    return check


register_control(ControlSpec(
    control_id="OSPS-VM-05.02",
    level=3,
    domain="VM",
    name="PreReleaseSCA",
    description="SCA runs before releases",
    passes=[
        DeterministicPass(config_check=_create_sca_check()),
        ManualPass(
            verification_steps=[
                "Check for dependency-review-action in workflows",
                "Verify SCA runs on pull requests",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-VM-05.03",
    level=3,
    domain="VM",
    name="AutomatedDependencyScanning",
    description="Automated dependency scanning is configured",
    passes=[
        DeterministicPass(config_check=_create_dependency_scanning_check()),
        ManualPass(
            verification_steps=[
                "Check for dependabot.yml or renovate.json",
                "Verify dependency scanning runs in CI",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-VM-06.01",
    level=3,
    domain="VM",
    name="SASTRemediationPolicy",
    description="SAST remediation threshold is documented",
    passes=[
        PatternPass(
            file_patterns=["SECURITY.md", ".github/SECURITY.md"],
            content_patterns={
                "sast_policy": r"(sast|static.analysis|code.*scan.*policy)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check SECURITY.md for SAST policy",
                "Verify remediation thresholds are documented",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-VM-06.02",
    level=3,
    domain="VM",
    name="AutomatedSAST",
    description="Automated SAST runs in CI",
    passes=[
        DeterministicPass(config_check=_create_sast_check()),
        ManualPass(
            verification_steps=[
                "Check for CodeQL, Semgrep, or other SAST tools",
                "Verify SAST runs on pull requests",
            ],
        ),
    ],
))
