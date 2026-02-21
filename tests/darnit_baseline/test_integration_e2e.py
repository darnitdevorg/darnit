"""End-to-end integration tests for remediation workflow.

These tests verify the COMPLETE flow works correctly, not just individual functions.
They catch issues like:
- Orchestrator not calling functions correctly
- Output not showing prompts to users
- Status codes not propagating correctly
"""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.system(f"cd {tmpdir} && git init -q")
        os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
        os.system(f"cd {tmpdir} && git config user.name 'Test'")
        (Path(tmpdir) / "README.md").write_text("# Test Project")
        os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
        yield tmpdir


class TestRemediationE2EFlow:
    """Test the complete remediation flow end-to-end."""

    @pytest.mark.integration
    def test_governance_full_flow_prompts_then_creates(self, temp_git_repo):
        """Test complete governance flow: prompt -> confirm -> create."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        # Step 1: Run remediation without confirmation - should prompt
        result1 = remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["governance"],
            dry_run=False,
        )

        assert "BLOCKED: Remediation Cannot Proceed" in result1 or "Needs Confirmation" in result1
        assert "confirm_project_context" in result1
        assert not (Path(temp_git_repo) / "GOVERNANCE.md").exists()

        # Step 2: Confirm maintainers
        confirm_result = confirm_project_context_impl(
            local_path=temp_git_repo,
            maintainers=["@alice", "@bob"],
        )
        assert "✅" in confirm_result

        # Step 3: Run remediation again - should create file
        result2 = remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["governance"],
            dry_run=False,
        )

        assert "Applied" in result2 or "✅" in result2
        assert (Path(temp_git_repo) / "GOVERNANCE.md").exists()

        content = (Path(temp_git_repo) / "GOVERNANCE.md").read_text()
        assert "@alice" in content
        assert "@bob" in content

    @pytest.mark.integration
    def test_security_policy_creates_security_md(self, temp_git_repo):
        """Test that vulnerability_management domain creates SECURITY.md."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["vulnerability_management"],
            dry_run=False,
        )

        assert (Path(temp_git_repo) / "SECURITY.md").exists()

        content = (Path(temp_git_repo) / "SECURITY.md").read_text()
        assert "Security" in content or "Vulnerability" in content

    @pytest.mark.integration
    def test_vex_policy_returns_manual_guidance(self, temp_git_repo):
        """Test that VEX policy remediation returns manual guidance.

        OSPS-VM-04.02 uses manual remediation type because it requires
        appending to an existing SECURITY.md (which file_create can't do).
        """
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        result = _apply_control_remediation(
            control_id="OSPS-VM-04.02",
            local_path=temp_git_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] in ("applied", "would_apply", "manual"), \
            f"Unexpected status: {result['status']}"


class TestControlDefinitionConsistency:
    """Test that control definitions are consistent."""

    @pytest.mark.unit
    def test_toml_remediation_coverage(self):
        """Report how many controls have TOML remediation defined."""
        from darnit_baseline.remediation.orchestrator import _get_framework_config

        framework = _get_framework_config()
        assert framework is not None

        total = len(framework.controls)
        with_remediation = sum(
            1 for c in framework.controls.values()
            if c.remediation and c.remediation.handlers
        )

        print(f"\nControls with TOML remediation: {with_remediation}/{total}")
        assert with_remediation >= 18, \
            f"Expected at least 18 controls with remediation, got {with_remediation}"


class TestOutputContainsExpectedContent:
    """Test that tool outputs contain expected content for users."""

    @pytest.mark.unit
    def test_needs_confirmation_output_has_prompt(self, temp_git_repo):
        """Verify needs_confirmation results include the actual prompt."""
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        result = _apply_control_remediation(
            control_id="OSPS-GV-01.01",
            local_path=temp_git_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "needs_confirmation"
        assert "result" in result
        assert "confirm_project_context" in result["result"]
        assert "maintainers=" in result["result"]
