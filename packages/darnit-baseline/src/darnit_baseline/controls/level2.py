"""Level 2 OSPS Control Definitions for Sieve System (18 controls).

Level 2 represents enhanced security requirements for more mature open source projects.
"""

import os
import re
import json
import subprocess
from typing import Dict, List, Optional, Callable

from darnit.core.logging import get_logger

logger = get_logger("sieve.level2")

from darnit.sieve.models import (
    ControlSpec,
    CheckContext,
    VerificationPhase,
    PassResult,
    PassOutcome,
)
from darnit.sieve.passes import DeterministicPass, PatternPass, LLMPass, ManualPass
from darnit.sieve.registry import register_control
from darnit.sieve.project_context import is_context_confirmed, get_context_value


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _gh_api(endpoint: str) -> Optional[Dict]:
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


def _read_file(local_path: str, filename: str) -> Optional[str]:
    """Read file content, return None if doesn't exist."""
    filepath = os.path.join(local_path, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except (IOError, OSError) as e:
            logger.debug(f"Could not read {filepath}: {type(e).__name__}")
            return None
    return None


# =============================================================================
# ACCESS CONTROL (AC) - 1 control
# =============================================================================


def _create_permissions_check() -> Callable[[CheckContext], PassResult]:
    """Check CI/CD default to lowest permissions (OSPS-AC-04.01).

    Spec: When a CI/CD task is executed with no permissions specified, the CI/CD
    system MUST default the task's permissions to the lowest permissions granted
    in the pipeline.
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
                        message=f"Using {ci_provider} CI - verify default permissions are minimal",
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
                    "confirmation_prompt": "What CI/CD system does this project use?",
                },
            )

        has_permissions_defined = False
        workflows_checked = []

        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    workflows_checked.append(file)
                    content = _read_file(root, file) or ""
                    if re.search(r'^permissions:', content, re.MULTILINE):
                        has_permissions_defined = True

        if has_permissions_defined:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Workflows define explicit permissions",
                evidence={"workflows": workflows_checked},
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.FAIL,
                message="Workflows should define explicit permissions",
                evidence={"workflows": workflows_checked},
            )

    return check


register_control(ControlSpec(
    control_id="OSPS-AC-04.01",
    level=2,
    domain="AC",
    name="CICDLowestPermissions",
    description="CI/CD pipelines default to lowest permissions",
    passes=[
        DeterministicPass(config_check=_create_permissions_check()),
        ManualPass(
            verification_steps=[
                "Check GitHub Actions workflows for 'permissions:' block",
                "Verify permissions are set to minimum required",
                "Consider adding 'permissions: {}' at workflow level",
            ],
        ),
    ],
))


# =============================================================================
# BUILD & RELEASE (BR) - 4 controls
# =============================================================================


def _create_releases_check() -> Callable[[CheckContext], PassResult]:
    """Check releases for unique versions (OSPS-BR-02.01)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            releases = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}/releases?per_page=5")

            if not releases:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,  # N/A
                    message="No releases found",
                    evidence={"has_releases": False},
                )

            versions = [r.get("tag_name") for r in releases if r.get("tag_name")]
            if len(versions) == len(set(versions)):
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Releases have unique versions: {', '.join(versions[:3])}",
                    evidence={"versions": versions},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="Duplicate version identifiers found",
                    evidence={"versions": versions},
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Release version check failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check releases: {e}",
            )

    return check


def _create_changelog_check() -> Callable[[CheckContext], PassResult]:
    """Check release contains changelog (OSPS-BR-04.01)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            releases = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}/releases?per_page=5")

            if not releases:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,  # N/A
                    message="No releases found",
                )

            latest = releases[0]
            if latest.get("body"):
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="Latest release has release notes",
                    evidence={"tag": latest.get("tag_name")},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="Latest release has no release notes",
                    evidence={"tag": latest.get("tag_name")},
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Changelog check failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check releases: {e}",
            )

    return check


LOCKFILE_PATTERNS = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Pipfile.lock", "poetry.lock", "pdm.lock", "uv.lock",
    "Gemfile.lock", "go.sum", "Cargo.lock",
    "composer.lock", "mix.lock", "pubspec.lock",
]


def _create_lockfile_check() -> Callable[[CheckContext], PassResult]:
    """Check for standardized dependency tooling (OSPS-BR-05.01)."""

    def check(ctx: CheckContext) -> PassResult:
        found_lockfiles = [f for f in LOCKFILE_PATTERNS if _file_exists(ctx.local_path, f)]

        if found_lockfiles:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message=f"Uses standardized dependency tooling: {', '.join(found_lockfiles)}",
                evidence={"lockfiles": found_lockfiles},
            )
        else:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.FAIL,
                message="No lockfile found. Dependencies are not pinned.",
            )

    return check


def _create_signed_releases_check() -> Callable[[CheckContext], PassResult]:
    """Check for signed releases or checksums (OSPS-BR-06.01)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            releases = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}/releases?per_page=5")

            if not releases:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,  # N/A
                    message="No releases found",
                )

            latest = releases[0]
            assets = latest.get("assets", [])
            has_signature = any(
                a.get("name", "").endswith((".sig", ".asc", ".gpg"))
                for a in assets
            )
            has_checksum = any(
                a.get("name", "").endswith((".sha256", ".sha512", "checksums.txt", "SHASUMS"))
                for a in assets
            )

            if has_signature or has_checksum:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="Release has signatures or checksums",
                    evidence={"tag": latest.get("tag_name"), "has_sig": has_signature, "has_checksum": has_checksum},
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="Release lacks signatures/checksums",
                    evidence={"tag": latest.get("tag_name")},
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Release hash check failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check releases: {e}",
            )

    return check


register_control(ControlSpec(
    control_id="OSPS-BR-02.01",
    level=2,
    domain="BR",
    name="UniqueVersions",
    description="Releases have unique version identifiers",
    passes=[
        DeterministicPass(config_check=_create_releases_check()),
        ManualPass(
            verification_steps=[
                "Check release tags in repository",
                "Verify each release has a unique version number",
                "Use semantic versioning (semver.org)",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-BR-04.01",
    level=2,
    domain="BR",
    name="ReleaseChangelog",
    description="Releases contain changelog/release notes",
    passes=[
        DeterministicPass(config_check=_create_changelog_check()),
        DeterministicPass(
            file_must_exist=["CHANGELOG.md", "CHANGELOG", "HISTORY.md", "NEWS.md"]
        ),
        ManualPass(
            verification_steps=[
                "Check release notes on GitHub releases",
                "Verify CHANGELOG.md exists and is updated",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-BR-05.01",
    level=2,
    domain="BR",
    name="StandardizedDependencyTooling",
    description="Uses standardized dependency tooling with lockfiles",
    passes=[
        DeterministicPass(config_check=_create_lockfile_check()),
        ManualPass(
            verification_steps=[
                "Check for package-lock.json, yarn.lock, poetry.lock, etc.",
                "Verify dependencies are pinned to specific versions",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-BR-06.01",
    level=2,
    domain="BR",
    name="SignedReleases",
    description="Releases are signed or have checksums",
    passes=[
        DeterministicPass(config_check=_create_signed_releases_check()),
        ManualPass(
            verification_steps=[
                "Check release assets for .sig, .asc, or checksum files",
                "Verify signatures can be validated",
            ],
        ),
    ],
))


# =============================================================================
# DOCUMENTATION (DO) - 1 control
# =============================================================================


register_control(ControlSpec(
    control_id="OSPS-DO-06.01",
    level=2,
    domain="DO",
    name="DependencyManagementDocs",
    description="Dependency management process is documented",
    passes=[
        DeterministicPass(
            file_must_exist=["DEPENDENCIES.md", "docs/DEPENDENCIES.md", "docs/dependencies.md"]
        ),
        PatternPass(
            file_patterns=["README.md", "CONTRIBUTING.md"],
            content_patterns={
                "dependency_docs": r"(dependenc|package|install|requirements)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check README for dependency installation instructions",
                "Verify CONTRIBUTING.md mentions dependency management",
            ],
        ),
    ],
))


# =============================================================================
# GOVERNANCE (GV) - 3 controls
# =============================================================================


GOVERNANCE_FILES = [
    "GOVERNANCE.md", "MAINTAINERS.md", "MAINTAINERS", "CODEOWNERS",
    ".github/CODEOWNERS", "docs/GOVERNANCE.md", "OWNERS.md",
]


def _create_governance_check() -> Callable[[CheckContext], PassResult]:
    """Check for governance documentation (OSPS-GV-01.01, OSPS-GV-01.02)."""

    def check(ctx: CheckContext) -> PassResult:
        for f in GOVERNANCE_FILES:
            if _file_exists(ctx.local_path, f):
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Governance documentation found: {f}",
                    evidence={"file": f},
                )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="No GOVERNANCE.md, MAINTAINERS.md, or CODEOWNERS found",
        )

    return check


register_control(ControlSpec(
    control_id="OSPS-GV-01.01",
    level=2,
    domain="GV",
    name="SensitiveAccessList",
    description="List of members with sensitive access is documented",
    passes=[
        DeterministicPass(config_check=_create_governance_check()),
        ManualPass(
            verification_steps=[
                "Check for MAINTAINERS.md or CODEOWNERS",
                "Verify list of people with commit/admin access",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-GV-01.02",
    level=2,
    domain="GV",
    name="RolesAndResponsibilities",
    description="Roles and responsibilities are documented",
    passes=[
        DeterministicPass(config_check=_create_governance_check()),
        ManualPass(
            verification_steps=[
                "Check GOVERNANCE.md for role definitions",
                "Verify responsibilities are clearly defined",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-GV-03.02",
    level=2,
    domain="GV",
    name="ContributionRequirements",
    description="Contribution requirements are documented",
    passes=[
        DeterministicPass(
            file_must_exist=["CONTRIBUTING.md", ".github/CONTRIBUTING.md"]
        ),
        PatternPass(
            file_patterns=["CONTRIBUTING.md", ".github/CONTRIBUTING.md"],
            content_patterns={
                "requirements": r"(requirement|guideline|standard|convention|must|should)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check CONTRIBUTING.md for specific requirements",
                "Verify coding standards are documented",
            ],
        ),
    ],
))


# =============================================================================
# LEGAL (LE) - 1 control
# =============================================================================


def _create_dco_check() -> Callable[[CheckContext], PassResult]:
    """Check for DCO/CLA requirement (OSPS-LE-01.01)."""

    def check(ctx: CheckContext) -> PassResult:
        # Check for DCO/CLA files
        if _file_exists(ctx.local_path, "DCO", "DCO.md", ".github/DCO", "CLA", "CLA.md", ".github/CLA"):
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="DCO or CLA file found",
            )

        # Check for DCO config
        if _file_exists(ctx.local_path, ".github/dco.yml", ".github/dco.yaml"):
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="DCO configuration found",
            )

        # Check workflows for DCO/CLA
        workflow_dir = os.path.join(ctx.local_path, ".github", "workflows")
        if os.path.exists(workflow_dir):
            for root, _, files in os.walk(workflow_dir):
                for file in files:
                    if file.endswith(('.yml', '.yaml')):
                        content = _read_file(root, file) or ""
                        if any(kw in content.lower() for kw in ["dco", "cla", "signed-off-by"]):
                            return PassResult(
                                phase=VerificationPhase.DETERMINISTIC,
                                outcome=PassOutcome.PASS,
                                message="DCO/CLA check found in workflows",
                            )

        # Check CONTRIBUTING.md
        contributing = _read_file(ctx.local_path, "CONTRIBUTING.md") or ""
        dco_markers = [
            "signed-off-by", "sign-off", "signoff",
            "developer certificate of origin", "dco",
            "git commit -s", "commit -s -m",
            "contributor license agreement", "cla"
        ]
        if any(marker in contributing.lower() for marker in dco_markers):
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="DCO/CLA mentioned in CONTRIBUTING.md",
            )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="No DCO/CLA requirement found",
        )

    return check


register_control(ControlSpec(
    control_id="OSPS-LE-01.01",
    level=2,
    domain="LE",
    name="DCOCLARequirement",
    description="DCO or CLA is required for contributions",
    passes=[
        DeterministicPass(config_check=_create_dco_check()),
        ManualPass(
            verification_steps=[
                "Check for DCO.md or CLA.md file",
                "Verify CONTRIBUTING.md mentions sign-off requirement",
                "Check if DCO GitHub App is installed",
            ],
        ),
    ],
))


# =============================================================================
# QUALITY ASSURANCE (QA) - 2 controls
# =============================================================================


def _create_status_checks_check() -> Callable[[CheckContext], PassResult]:
    """Check for required status checks (OSPS-QA-03.01)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            protection = _gh_api(
                f"/repos/{ctx.owner}/{ctx.repo}/branches/{ctx.default_branch}/protection"
            )

            if protection and protection.get("required_status_checks"):
                contexts = protection["required_status_checks"].get("contexts", [])
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Required status checks: {', '.join(contexts) or 'enabled'}",
                    evidence={"contexts": contexts},
                )
            elif protection:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="Branch protection exists but no required status checks",
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="No branch protection with status checks",
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Status check verification failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not verify status checks: {e}",
            )

    return check


def _create_automated_tests_check() -> Callable[[CheckContext], PassResult]:
    """Check for automated test suite in CI (OSPS-QA-06.01).

    Spec: Prior to a commit being accepted, the project's CI/CD pipelines MUST
    run at least one automated test suite to ensure the changes meet expectations.
    """

    def check(ctx: CheckContext) -> PassResult:
        workflow_dir = os.path.join(ctx.local_path, ".github", "workflows")

        # CI config locations for different providers
        ci_configs = {
            "gitlab": [".gitlab-ci.yml"],
            "jenkins": ["Jenkinsfile", "jenkins.yml"],
            "circleci": [".circleci/config.yml"],
            "azure": ["azure-pipelines.yml", ".azure-pipelines.yml"],
            "travis": [".travis.yml"],
        }

        test_patterns = [
            r'npm\s+test', r'yarn\s+test', r'pnpm\s+test',
            r'pytest', r'python\s+-m\s+pytest',
            r'jest', r'mocha', r'vitest',
            r'go\s+test', r'cargo\s+test',
            r'rspec', r'bundle\s+exec\s+rspec',
            r'mvn\s+test', r'gradle\s+test',
            r'dotnet\s+test', r'mix\s+test',
        ]

        if not os.path.exists(workflow_dir):
            # Check if user has confirmed a different CI provider
            if is_context_confirmed(ctx.local_path, "ci_provider"):
                ci_provider = get_context_value(ctx.local_path, "ci_provider")
                if ci_provider == "none":
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.FAIL,
                        message="No CI/CD used - automated tests are required before merging",
                        evidence={"ci_provider": "none", "source": ".project.yaml"},
                    )
                elif ci_provider != "github":
                    # Check for other CI config files
                    config_files = ci_configs.get(ci_provider, [])
                    for config in config_files:
                        config_path = os.path.join(ctx.local_path, config)
                        if os.path.exists(config_path):
                            content = _read_file(ctx.local_path, config) or ""
                            for pattern in test_patterns:
                                if re.search(pattern, content, re.IGNORECASE):
                                    return PassResult(
                                        phase=VerificationPhase.DETERMINISTIC,
                                        outcome=PassOutcome.PASS,
                                        message=f"Automated tests found in {ci_provider} CI ({config})",
                                        evidence={"ci_provider": ci_provider, "config": config},
                                    )
                            return PassResult(
                                phase=VerificationPhase.DETERMINISTIC,
                                outcome=PassOutcome.INCONCLUSIVE,
                                message=f"Using {ci_provider} CI - verify automated tests are configured",
                                evidence={"ci_provider": ci_provider, "config": config},
                            )
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.INCONCLUSIVE,
                        message=f"Using {ci_provider} CI but config file not found - verify tests are configured",
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
                    "confirmation_prompt": "What CI/CD system does this project use?",
                },
            )

        # GitHub Actions found - check for tests
        test_patterns = [
            r'npm\s+test', r'yarn\s+test', r'pnpm\s+test',
            r'pytest', r'python\s+-m\s+pytest',
            r'jest', r'mocha', r'vitest',
            r'go\s+test', r'cargo\s+test',
            r'rspec', r'bundle\s+exec\s+rspec',
            r'mvn\s+test', r'gradle\s+test',
            r'dotnet\s+test', r'mix\s+test',
        ]

        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    content = _read_file(root, file) or ""
                    for pattern in test_patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            return PassResult(
                                phase=VerificationPhase.DETERMINISTIC,
                                outcome=PassOutcome.PASS,
                                message="CI workflows include automated tests",
                                evidence={"workflow": file},
                            )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="CI workflows exist but no test commands found",
        )

    return check


register_control(ControlSpec(
    control_id="OSPS-QA-03.01",
    level=2,
    domain="QA",
    name="RequiredStatusChecks",
    description="Status checks must pass before merging",
    passes=[
        DeterministicPass(config_check=_create_status_checks_check()),
        ManualPass(
            verification_steps=[
                "Check branch protection settings",
                "Verify required status checks are configured",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-QA-06.01",
    level=2,
    domain="QA",
    name="AutomatedTestSuite",
    description="Automated test suite runs in CI",
    passes=[
        DeterministicPass(config_check=_create_automated_tests_check()),
        ManualPass(
            verification_steps=[
                "Check GitHub Actions for test commands",
                "Verify tests run on pull requests",
            ],
        ),
    ],
))


# =============================================================================
# SECURITY ARCHITECTURE (SA) - 3 controls
# =============================================================================


DESIGN_DOCS = [
    "ARCHITECTURE.md", "DESIGN.md", "docs/ARCHITECTURE.md", "docs/DESIGN.md",
    "docs/architecture/", "docs/design/", "doc/architecture.md",
]

API_DOCS = [
    "API.md", "docs/API.md", "docs/api/", "openapi.yaml", "openapi.json",
    "swagger.yaml", "swagger.json", "api-docs/",
]


def _create_design_docs_check() -> Callable[[CheckContext], PassResult]:
    """Check for design documentation (OSPS-SA-01.01)."""

    def check(ctx: CheckContext) -> PassResult:
        for doc in DESIGN_DOCS:
            if _file_exists(ctx.local_path, doc):
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Architecture/design documentation found: {doc}",
                    evidence={"file": doc},
                )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="No architecture documentation found",
        )

    return check


def _create_api_docs_check() -> Callable[[CheckContext], PassResult]:
    """Check for API documentation (OSPS-SA-02.01)."""

    def check(ctx: CheckContext) -> PassResult:
        for doc in API_DOCS:
            if _file_exists(ctx.local_path, doc):
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"API/interface documentation found: {doc}",
                    evidence={"file": doc},
                )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="No API/interface documentation found",
        )

    return check


register_control(ControlSpec(
    control_id="OSPS-SA-01.01",
    level=2,
    domain="SA",
    name="DesignDocumentation",
    description="Architecture/design documentation exists",
    passes=[
        DeterministicPass(config_check=_create_design_docs_check()),
        ManualPass(
            verification_steps=[
                "Check for ARCHITECTURE.md or DESIGN.md",
                "Verify docs/ folder contains architecture documentation",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-SA-02.01",
    level=2,
    domain="SA",
    name="ExternalInterfaceDocs",
    description="External interface documentation exists",
    passes=[
        DeterministicPass(config_check=_create_api_docs_check()),
        ManualPass(
            verification_steps=[
                "Check for API.md or openapi.yaml",
                "Verify API documentation is complete",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-SA-03.01",
    level=2,
    domain="SA",
    name="SecurityAssessment",
    description="Security assessment documentation exists",
    passes=[
        PatternPass(
            file_patterns=["SECURITY.md", ".github/SECURITY.md"],
            content_patterns={
                "threat_assessment": r"(threat|risk|assessment|vulnerability|attack)",
            },
            pass_if_any_match=True,
        ),
        DeterministicPass(
            file_must_exist=["SECURITY.md", ".github/SECURITY.md", "docs/security/"]
        ),
        ManualPass(
            verification_steps=[
                "Check SECURITY.md for threat modeling",
                "Verify security considerations are documented",
            ],
        ),
    ],
))


# =============================================================================
# VULNERABILITY MANAGEMENT (VM) - 3 controls
# =============================================================================


register_control(ControlSpec(
    control_id="OSPS-VM-01.01",
    level=2,
    domain="VM",
    name="CVDPolicy",
    description="Coordinated vulnerability disclosure policy with timeframe",
    passes=[
        PatternPass(
            file_patterns=["SECURITY.md", ".github/SECURITY.md"],
            content_patterns={
                "disclosure_policy": r"(disclosure|response|timeframe|\d+\s*days)",
            },
            pass_if_any_match=True,
        ),
        DeterministicPass(
            file_must_exist=["SECURITY.md", ".github/SECURITY.md"]
        ),
        ManualPass(
            verification_steps=[
                "Check SECURITY.md for disclosure timeline",
                "Verify response timeframe is documented",
            ],
        ),
    ],
))

register_control(ControlSpec(
    control_id="OSPS-VM-03.01",
    level=2,
    domain="VM",
    name="PrivateVulnerabilityReporting",
    description="Private vulnerability reporting mechanism exists",
    passes=[
        PatternPass(
            file_patterns=["SECURITY.md", ".github/SECURITY.md"],
            content_patterns={
                "private_reporting": r"(private|confidential|email|pgp|gpg|security@|privately)",
            },
            pass_if_any_match=True,
        ),
        ManualPass(
            verification_steps=[
                "Check SECURITY.md for private contact method",
                "Verify email or PGP key is provided",
                "Check if GitHub private vulnerability reporting is enabled",
            ],
        ),
    ],
))


def _create_advisories_check() -> Callable[[CheckContext], PassResult]:
    """Check for security advisories capability (OSPS-VM-04.01)."""

    def check(ctx: CheckContext) -> PassResult:
        try:
            repo_data = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}")
            if not repo_data:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="Could not access repository settings",
                )

            has_issues = repo_data.get("has_issues", False)
            advisories = _gh_api(f"/repos/{ctx.owner}/{ctx.repo}/security-advisories")

            if advisories is not None:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Security advisories enabled ({len(advisories)} published)",
                    evidence={"count": len(advisories)},
                )
            elif has_issues:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message="Repository supports security advisories",
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message="Issues disabled - security advisories require issues",
                )

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Advisories check failed: {type(e).__name__}: {e}")
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not verify advisories: {e}",
            )

    return check


register_control(ControlSpec(
    control_id="OSPS-VM-04.01",
    level=2,
    domain="VM",
    name="PublicVulnerabilityData",
    description="Public vulnerability data via security advisories",
    passes=[
        DeterministicPass(config_check=_create_advisories_check()),
        ManualPass(
            verification_steps=[
                "Check if GitHub Security Advisories are enabled",
                "Verify Issues are enabled (required for advisories)",
            ],
        ),
    ],
))
