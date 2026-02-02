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
    def test_maintainers_full_flow_prompts_then_creates(self, temp_git_repo):
        """Test complete maintainers flow: prompt → confirm → create."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        # Step 1: Run remediation without confirmation - should prompt
        result1 = remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["maintainers"],
            dry_run=False,
        )

        # Should show "Needs Confirmation" section with prompt
        assert "Needs Confirmation" in result1
        assert "confirm_project_context" in result1
        assert not (Path(temp_git_repo) / "MAINTAINERS.md").exists()

        # Step 2: Confirm maintainers
        confirm_result = confirm_project_context_impl(
            local_path=temp_git_repo,
            maintainers=["@alice", "@bob"],
        )
        assert "✅" in confirm_result

        # Step 3: Run remediation again - should create file
        result2 = remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["maintainers"],
            dry_run=False,
        )

        # Should show "Applied" section
        assert "Applied" in result2 or "✅" in result2
        assert (Path(temp_git_repo) / "MAINTAINERS.md").exists()

        # Verify file content
        content = (Path(temp_git_repo) / "MAINTAINERS.md").read_text()
        assert "@alice" in content
        assert "@bob" in content

    @pytest.mark.integration
    def test_security_policy_creates_with_vex_section(self, temp_git_repo):
        """Test that security_policy creates SECURITY.md with VEX policy section."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["security_policy"],
            dry_run=False,
        )

        # Should create file
        assert (Path(temp_git_repo) / "SECURITY.md").exists()

        # Should have VEX policy section (not create vex.json)
        content = (Path(temp_git_repo) / "SECURITY.md").read_text()
        assert "VEX" in content or "Vulnerability Exploitability" in content

        # Should NOT create vex.json
        assert not (Path(temp_git_repo) / "vex.json").exists()

    @pytest.mark.integration
    def test_vex_policy_adds_to_existing_security_md(self, temp_git_repo):
        """Test that vex_policy adds section to existing SECURITY.md."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        # Create a SECURITY.md without VEX section
        (Path(temp_git_repo) / "SECURITY.md").write_text("""# Security Policy

## Reporting a Vulnerability

Please report issues responsibly.
""")

        remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["vex_policy"],
            dry_run=False,
        )

        # Should update file with VEX section
        content = (Path(temp_git_repo) / "SECURITY.md").read_text()
        assert "VEX" in content or "Vulnerability Exploitability" in content

        # Should NOT create vex.json
        assert not (Path(temp_git_repo) / "vex.json").exists()


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
    def test_remediation_registry_controls_exist_in_catalog(self):
        """Verify all controls in remediation registry exist in catalog."""
        from darnit_baseline.remediation.registry import REMEDIATION_REGISTRY
        from darnit_baseline.rules.catalog import OSPS_RULES

        missing = []
        for category, info in REMEDIATION_REGISTRY.items():
            for control_id in info.get("controls", []):
                if control_id not in OSPS_RULES:
                    missing.append(f"{category}: {control_id}")

        assert len(missing) == 0, f"Remediation registry references missing controls: {missing}"


class TestOutputContainsExpectedContent:
    """Test that tool outputs contain expected content for users."""

    @pytest.mark.unit
    def test_needs_confirmation_output_has_prompt(self, temp_git_repo):
        """Verify needs_confirmation results include the actual prompt."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="maintainers",
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
