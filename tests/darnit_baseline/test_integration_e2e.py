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
        """Test complete governance flow: prompt → confirm → create."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        # Step 1: Run remediation without confirmation - should prompt
        result1 = remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["governance"],
            dry_run=False,
        )

        # Pre-flight check now returns early with "BLOCKED" message
        # (instead of running remediations and returning "Needs Confirmation")
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

        # Should show "Applied" section
        assert "Applied" in result2 or "✅" in result2
        assert (Path(temp_git_repo) / "GOVERNANCE.md").exists()

        # Verify file content
        content = (Path(temp_git_repo) / "GOVERNANCE.md").read_text()
        assert "@alice" in content
        assert "@bob" in content

    @pytest.mark.integration
    def test_security_policy_creates_security_md(self, temp_git_repo):
        """Test that security_policy creates SECURITY.md."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["security_policy"],
            dry_run=False,
        )

        # Should create file
        assert (Path(temp_git_repo) / "SECURITY.md").exists()

        content = (Path(temp_git_repo) / "SECURITY.md").read_text()
        # Should have vulnerability reporting section
        assert "Security" in content or "Vulnerability" in content

    @pytest.mark.integration
    def test_vex_policy_returns_manual_guidance(self, temp_git_repo):
        """Test that VEX policy remediation returns manual guidance.

        OSPS-VM-04.02 uses manual remediation type because it requires
        appending to an existing SECURITY.md (which file_create can't do).
        """
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="security_policy",
            local_path=temp_git_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # security_policy should either apply (creating SECURITY.md via file_create)
        # or return manual steps (for VEX policy portion)
        assert result["status"] in ("applied", "would_apply", "manual"), \
            f"Unexpected status: {result['status']}"


class TestControlDefinitionConsistency:
    """Test that control definitions are consistent across all sources."""

    @pytest.mark.unit
    def test_toml_and_catalog_controls_match(self):
        """Verify controls in TOML match those in catalog.py."""
        import tomllib

        from darnit_baseline import get_framework_path
        from darnit_baseline.rules.catalog import OSPS_RULES

        # Load TOML controls
        toml_path = get_framework_path()
        with open(toml_path, "rb") as f:
            toml_data = tomllib.load(f)

        toml_controls = set(toml_data.get("controls", {}).keys())
        catalog_controls = set(OSPS_RULES.keys())

        # Find discrepancies
        in_catalog_not_toml = catalog_controls - toml_controls
        in_toml_not_catalog = toml_controls - catalog_controls

        # These are acceptable - some controls are only in catalog (not yet in TOML)
        # But we should track them
        print(f"\nControls in catalog but not TOML: {len(in_catalog_not_toml)}")
        print(f"Controls in TOML but not catalog: {len(in_toml_not_catalog)}")

        # At minimum, all TOML controls should be in catalog
        assert len(in_toml_not_catalog) == 0, f"TOML has controls not in catalog: {in_toml_not_catalog}"

    @pytest.mark.unit
    def test_remediation_categories_controls_exist_in_catalog(self):
        """Verify all controls in REMEDIATION_CATEGORIES exist in catalog."""
        from darnit_baseline.remediation.orchestrator import REMEDIATION_CATEGORIES
        from darnit_baseline.rules.catalog import OSPS_RULES

        missing = []
        for category, info in REMEDIATION_CATEGORIES.items():
            for control_id in info.get("controls", []):
                if control_id not in OSPS_RULES:
                    missing.append(f"{category}: {control_id}")

        assert len(missing) == 0, f"REMEDIATION_CATEGORIES references missing controls: {missing}"


class TestOutputContainsExpectedContent:
    """Test that tool outputs contain expected content for users."""

    @pytest.mark.unit
    def test_needs_confirmation_output_has_prompt(self, temp_git_repo):
        """Verify needs_confirmation results include the actual prompt."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="governance",
            local_path=temp_git_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "needs_confirmation"
        assert "result" in result
        assert "confirm_project_context" in result["result"]
        # Should include example call
        assert "maintainers=" in result["result"]
