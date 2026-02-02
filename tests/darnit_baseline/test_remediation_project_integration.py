"""Tests for remediation integration with .project/ configuration.

The project configuration uses a .project/ directory structure:
- .project/project.yaml: CNCF standard fields
- .project/darnit.yaml: x-openssf-baseline extension fields
"""

from pathlib import Path

import pytest

from darnit.config.loader import clear_config_cache
from darnit_baseline.remediation.orchestrator import _apply_remediation


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear config cache before each test to avoid cross-test contamination."""
    clear_config_cache()
    yield
    clear_config_cache()


def _create_project_config(
    tmp_path: Path,
    control_overrides: dict = None,
    project_name: str = "test-project",
):
    """Helper to create .project/ directory structure.

    Args:
        tmp_path: Base path for the test
        control_overrides: Dict of control_id -> {status, reason}
        project_name: Name for the project
    """
    project_dir = tmp_path / ".project"
    project_dir.mkdir(exist_ok=True)

    # Write project.yaml (CNCF standard fields)
    (project_dir / "project.yaml").write_text(f"""# .project/project.yaml - CNCF Project Configuration
name: {project_name}
description: Test project
type: software
schema_version: "1.0"
""")

    # Write darnit.yaml (extension fields)
    if control_overrides:
        controls_yaml = "\n".join(
            f"""  {ctrl_id}:
    status: {info['status']}
    reason: "{info['reason']}" """
            for ctrl_id, info in control_overrides.items()
        )
        darnit_yaml = f"""# .project/darnit.yaml - Darnit Extension
version: "1.0"
controls:
{controls_yaml}
"""
    else:
        darnit_yaml = """# .project/darnit.yaml - Darnit Extension
version: "1.0"
"""
    (project_dir / "darnit.yaml").write_text(darnit_yaml)


class TestProjectConfigIntegration:
    """Test that remediation respects .project/ control overrides."""

    def test_skip_remediation_for_na_controls(self, tmp_path):
        """Test that remediation is skipped when all controls are marked N/A."""
        # Create .project/ config with all security_policy controls as N/A
        # security_policy now covers: VM-01.01, VM-02.01, VM-03.01, VM-04.02
        _create_project_config(
            tmp_path,
            control_overrides={
                "OSPS-VM-01.01": {"status": "n/a", "reason": "Security policy exists in parent organization"},
                "OSPS-VM-02.01": {"status": "n/a", "reason": "Security policy exists in parent organization"},
                "OSPS-VM-03.01": {"status": "n/a", "reason": "Security policy exists in parent organization"},
                "OSPS-VM-04.02": {"status": "n/a", "reason": "VEX policy managed externally"},
            }
        )

        # Try to apply security_policy remediation
        result = _apply_remediation(
            category="security_policy",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        # Should be skipped since all controls are N/A
        assert result["status"] == "skipped"
        assert result["category"] == "security_policy"
        assert "skipped_controls" in result
        assert len(result["skipped_controls"]) == 4

        # Verify the reason is included for each skipped control
        reasons = [s["reason"] for s in result["skipped_controls"]]
        assert all(len(r) > 0 for r in reasons)  # All should have a reason

    def test_partial_na_controls(self, tmp_path):
        """Test that remediation runs when only some controls are N/A."""
        # Create .project/ config with only some controls marked N/A
        _create_project_config(
            tmp_path,
            control_overrides={
                "OSPS-VM-01.01": {"status": "n/a", "reason": "Only this one is N/A"},
            }
        )

        # Try to apply security_policy remediation
        result = _apply_remediation(
            category="security_policy",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        # Should proceed with remediation (would_apply)
        assert result["status"] == "would_apply"
        assert result["category"] == "security_policy"

        # Should include info about the skipped control
        if "skipped_controls" in result:
            assert len(result["skipped_controls"]) == 1
            assert result["skipped_controls"][0]["id"] == "OSPS-VM-01.01"

    def test_remediation_proceeds_without_project_config(self, tmp_path):
        """Test that remediation proceeds normally without .project/ config."""
        # No .project/ directory

        result = _apply_remediation(
            category="security_policy",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        # Should proceed with remediation
        assert result["status"] == "would_apply"
        assert result["category"] == "security_policy"
        assert "skipped_controls" not in result or len(result.get("skipped_controls", [])) == 0

    def test_remediation_with_enabled_override(self, tmp_path):
        """Test that enabled status doesn't skip remediation."""
        # Create .project/ config with enabled status
        _create_project_config(
            tmp_path,
            control_overrides={
                "OSPS-VM-02.01": {"status": "enabled", "reason": "Explicitly enabled"},
            }
        )

        result = _apply_remediation(
            category="security_policy",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        # Should proceed with remediation
        assert result["status"] == "would_apply"
        assert result["category"] == "security_policy"


class TestDeclarativeRemediationWithProjectConfig:
    """Test that declarative remediation works with .project/ integration."""

    def test_declarative_remediation_respects_na(self, tmp_path):
        """Test that declarative TOML remediation respects N/A status."""
        # Create .project/ config marking contributing controls as N/A
        _create_project_config(
            tmp_path,
            control_overrides={
                "OSPS-GV-03.01": {"status": "n/a", "reason": "Contributing guide maintained externally"},
                "OSPS-GV-03.02": {"status": "n/a", "reason": "Contributing guide maintained externally"},
            }
        )

        result = _apply_remediation(
            category="contributing",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        # Should be skipped
        assert result["status"] == "skipped"
        assert "Contributing guide maintained externally" in str(result)


class TestConfigUpdateAfterRemediation:
    """Test that .project/ is updated after successful remediation."""

    def test_config_updated_after_file_create(self, tmp_path):
        """Test that .project/ is updated after creating a file."""
        # Create minimal .project/ config
        _create_project_config(tmp_path)

        # Run remediation (not dry_run)
        result = _apply_remediation(
            category="security_policy",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=False,  # Actually apply
        )

        # Should succeed
        assert result["status"] == "applied"

        # Should indicate config was updated
        assert result.get("config_updated") is True

        # Verify .project/ was updated with the reference
        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config is not None
        assert config.security is not None
        assert config.security.policy is not None
        assert config.security.policy.path == "SECURITY.md"

    def test_config_not_updated_on_dry_run(self, tmp_path):
        """Test that .project/ is NOT updated on dry run."""
        # Create minimal .project/ config
        _create_project_config(tmp_path)

        # Run remediation (dry_run)
        result = _apply_remediation(
            category="security_policy",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,  # Dry run only
        )

        # Should show would_apply
        assert result["status"] == "would_apply"

        # .project/ should NOT be updated
        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config is not None
        # security.policy should still be None (not set)
        if config.security:
            assert config.security.policy is None

    def test_config_created_if_missing(self, tmp_path):
        """Test that .project/ is created if it doesn't exist."""
        # No .project/ directory

        # Run remediation
        result = _apply_remediation(
            category="security_policy",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should succeed
        assert result["status"] == "applied"
        assert result.get("config_updated") is True

        # .project/ should now exist with reference
        assert (tmp_path / ".project" / "project.yaml").exists()

        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config is not None
        assert config.security.policy.path == "SECURITY.md"
