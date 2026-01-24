"""Control registry with sieve-enabled control definitions."""

from typing import Dict, Optional, List, Callable
import subprocess
import json

from darnit.core.logging import get_logger
from .models import (
    ControlSpec,
    VerificationPhase,
    PassResult,
    PassOutcome,
)
from .passes import DeterministicPass, PatternPass, LLMPass, ManualPass

logger = get_logger("sieve.registry")


class ControlRegistry:
    """Registry of controls with sieve verification definitions."""

    def __init__(self):
        self._specs: Dict[str, ControlSpec] = {}
        self._legacy_checks: Dict[str, Callable] = {}

    def register(self, spec: ControlSpec, overwrite: bool = False) -> bool:
        """Register a control specification.

        Args:
            spec: The control specification to register
            overwrite: If False (default), skip if control already registered
                      If True, overwrite existing registration

        Returns:
            True if registered, False if skipped (already exists)
        """
        if not overwrite and spec.control_id in self._specs:
            logger.debug(f"Control {spec.control_id} already registered, skipping")
            return False
        self._specs[spec.control_id] = spec
        return True

    def register_legacy(self, control_id: str, check_fn: Callable) -> None:
        """Register a legacy check function for gradual migration."""
        self._legacy_checks[control_id] = check_fn

    def get(self, control_id: str) -> Optional[ControlSpec]:
        """Get control specification by ID."""
        return self._specs.get(control_id)

    def has_sieve(self, control_id: str) -> bool:
        """Check if control has sieve definition."""
        return control_id in self._specs

    def has_legacy(self, control_id: str) -> bool:
        """Check if control has legacy check."""
        return control_id in self._legacy_checks

    def get_legacy(self, control_id: str) -> Optional[Callable]:
        """Get legacy check function."""
        return self._legacy_checks.get(control_id)

    def list_sieve_controls(self) -> List[str]:
        """List all controls with sieve definitions."""
        return list(self._specs.keys())

    def list_legacy_controls(self) -> List[str]:
        """List all controls with legacy checks."""
        return list(self._legacy_checks.keys())

    def get_all_specs(self) -> List[ControlSpec]:
        """Get all registered control specifications."""
        return list(self._specs.values())

    def get_specs_by_level(self, level: int) -> List[ControlSpec]:
        """Get control specifications for a specific level."""
        return [s for s in self._specs.values() if s.level == level]

    def get_specs_by_domain(self, domain: str) -> List[ControlSpec]:
        """Get control specifications for a specific domain."""
        return [s for s in self._specs.values() if s.domain == domain]


# Global registry instance
_registry = ControlRegistry()


def get_control_registry() -> ControlRegistry:
    """Get the global control registry."""
    return _registry


def register_control(spec: ControlSpec) -> bool:
    """Register a control specification in the global registry.

    Returns:
        True if registered, False if skipped (already exists)
    """
    return _registry.register(spec)


# ============================================================================
# Helper functions for creating API checks
# ============================================================================


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
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def create_branch_protection_check() -> Callable[[str, str], PassResult]:
    """Create API check for branch protection."""

    def check(owner: str, repo: str) -> PassResult:
        try:
            # Get default branch
            repo_data = _gh_api(f"/repos/{owner}/{repo}")
            if not repo_data:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="Could not fetch repository data",
                )

            default_branch = repo_data.get("default_branch", "main")

            # Check protection
            protection = _gh_api(
                f"/repos/{owner}/{repo}/branches/{default_branch}/protection"
            )

            if protection is None:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message=f"Branch '{default_branch}' is not protected",
                    evidence={"branch": default_branch},
                )

            # Check for meaningful protection
            has_pr_reviews = protection.get("required_pull_request_reviews") is not None
            has_restrictions = protection.get("restrictions") is not None

            if has_pr_reviews or has_restrictions:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"Branch protection enabled on '{default_branch}'",
                    evidence={
                        "branch": default_branch,
                        "has_pr_reviews": has_pr_reviews,
                        "has_restrictions": has_restrictions,
                    },
                )
            else:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.FAIL,
                    message=f"Branch protection exists but doesn't prevent direct commits",
                    evidence={"branch": default_branch, "protection": protection},
                )

        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check branch protection: {e}",
                evidence={"error": str(e)},
            )

    return check


def create_mfa_check() -> Callable[[str, str], PassResult]:
    """Create API check for MFA requirement."""

    def check(owner: str, repo: str) -> PassResult:
        try:
            # Check if owner is org or user
            user_data = _gh_api(f"/users/{owner}")
            if not user_data:
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="Could not fetch owner data",
                )

            if user_data.get("type") == "Organization":
                # Organizations expose MFA settings
                org_data = _gh_api(f"/orgs/{owner}")
                if org_data:
                    mfa_required = org_data.get("two_factor_requirement_enabled")
                    if mfa_required is True:
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.PASS,
                            message="Organization MFA requirement is enabled",
                            evidence={"org": owner, "mfa_required": True},
                        )
                    elif mfa_required is False:
                        return PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.FAIL,
                            message="Organization MFA requirement is NOT enabled",
                            evidence={"org": owner, "mfa_required": False},
                        )

            # Personal account - cannot verify MFA via API
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message="MFA status cannot be verified for personal accounts via API",
                evidence={"owner_type": user_data.get("type", "unknown")},
            )

        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            return PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.INCONCLUSIVE,
                message=f"Could not check MFA: {e}",
                evidence={"error": str(e)},
            )

    return check


# ============================================================================
# Example Control Definitions
# ============================================================================


def _get_rule_metadata(control_id: str) -> Dict:
    """Try to get rule metadata from rules catalog."""
    try:
        from darnit.formatters.rules_catalog import get_rule

        return get_rule(control_id) or {}
    except ImportError:
        return {}


# Register OSPS-AC-03.01: Prevent direct commits to primary branch
register_control(
    ControlSpec(
        control_id="OSPS-AC-03.01",
        level=1,
        domain="AC",
        name="PreventDirectCommits",
        description="Prevent direct commits to primary branch",
        passes=[
            DeterministicPass(api_check=create_branch_protection_check()),
            ManualPass(
                verification_steps=[
                    "Navigate to Repository Settings -> Branches",
                    "Check if branch protection rule exists for main/master",
                    "Verify 'Require a pull request before merging' is enabled",
                    "Confirm no bypasses are configured for regular contributors",
                ],
                verification_docs_url="https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches",
            ),
        ],
        metadata=_get_rule_metadata("OSPS-AC-03.01"),
    )
)


# Register OSPS-AC-01.01: MFA for contributors
register_control(
    ControlSpec(
        control_id="OSPS-AC-01.01",
        level=1,
        domain="AC",
        name="MFARequired",
        description="Multi-factor authentication required for contributors",
        passes=[
            DeterministicPass(api_check=create_mfa_check()),
            ManualPass(
                verification_steps=[
                    "For organizations: Check Settings -> Authentication security -> Require two-factor authentication",
                    "For personal accounts: Verify MFA is enabled in personal settings",
                    "Ask repository administrators to confirm MFA status",
                ],
                verification_docs_url="https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication",
            ),
        ],
        metadata=_get_rule_metadata("OSPS-AC-01.01"),
    )
)


# Register OSPS-VM-02.01: Security contacts documented
register_control(
    ControlSpec(
        control_id="OSPS-VM-02.01",
        level=1,
        domain="VM",
        name="SecurityContacts",
        description="Security contacts documented in SECURITY.md",
        passes=[
            # Pass 1: Check if SECURITY.md exists
            DeterministicPass(
                file_must_exist=[
                    "SECURITY.md",
                    ".github/SECURITY.md",
                    "docs/SECURITY.md",
                ]
            ),
            # Pass 2: Check if it contains contact info
            PatternPass(
                file_patterns=["SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"],
                content_patterns={
                    "email_or_contact": r"([\w.-]+@[\w.-]+\.\w+|security\s*contact|report.*vulnerabilit|how\s+to\s+report)",
                },
                pass_if_any_match=True,
            ),
            # Pass 3: LLM analysis if patterns don't clearly indicate
            LLMPass(
                prompt_template="""Analyze whether this SECURITY.md file provides adequate
security contact information for vulnerability disclosure.

Requirements (OSPS-VM-02.01):
- Must contain clear contact method (email, form, etc.)
- Should explain how to report security issues
- Should include expected response timeline (optional but recommended)

Does this file adequately meet the requirements?""",
                files_to_include=["SECURITY.md", ".github/SECURITY.md"],
                analysis_hints=[
                    "Look for email addresses or contact forms",
                    "Check for vulnerability disclosure process",
                    "Verify response time commitments if present",
                    "Consider if a security researcher could easily understand what to do",
                ],
                confidence_threshold=0.8,
            ),
            # Pass 4: Manual verification
            ManualPass(
                verification_steps=[
                    "Open SECURITY.md (or .github/SECURITY.md)",
                    "Verify it contains a clear contact method",
                    "Check that vulnerability reporting process is documented",
                    "Confirm the contact method is currently monitored",
                ],
                verification_docs_url="https://baseline.openssf.org/versions/2025-10-10#OSPS-VM-02.01",
            ),
        ],
        metadata=_get_rule_metadata("OSPS-VM-02.01"),
    )
)


# Register OSPS-DO-01.01: README exists
register_control(
    ControlSpec(
        control_id="OSPS-DO-01.01",
        level=1,
        domain="DO",
        name="READMEExists",
        description="Project has a README file",
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
            ManualPass(
                verification_steps=[
                    "Check repository root for README file",
                    "Verify README contains project description",
                ]
            ),
        ],
        metadata=_get_rule_metadata("OSPS-DO-01.01"),
    )
)


# Register OSPS-LE-01.01: License file exists
register_control(
    ControlSpec(
        control_id="OSPS-LE-01.01",
        level=1,
        domain="LE",
        name="LicenseExists",
        description="Project has a license file",
        passes=[
            DeterministicPass(
                file_must_exist=[
                    "LICENSE",
                    "LICENSE.md",
                    "LICENSE.txt",
                    "COPYING",
                    "license",
                ]
            ),
            ManualPass(
                verification_steps=[
                    "Check repository root for LICENSE file",
                    "Verify license is OSI-approved if claiming open source",
                ]
            ),
        ],
        metadata=_get_rule_metadata("OSPS-LE-01.01"),
    )
)
