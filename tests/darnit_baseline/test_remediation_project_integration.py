"""Tests for remediation integration with .project/ configuration.

The project configuration uses a .project/ directory structure:
- .project/project.yaml: CNCF standard fields
- .project/darnit.yaml: x-openssf-baseline extension fields
"""

from pathlib import Path

import pytest

from darnit.config.loader import clear_config_cache
from darnit_baseline.remediation.orchestrator import _apply_control_remediation

TARGET = "github.com/test-owner/test-repo"


def _confirm_security_contact(repo: Path) -> None:
    """Confirm the security contact OSPS-VM-02.01's template reads.

    Feature 042 (FR-007): a template that reads a context key without a
    usable value stops with "confirmation required" (was: rendered empty).
    Recorded operator-side, so the repository's ``.project/`` is unchanged.
    """
    from darnit.config.context_keys import value_digest
    from darnit.config.operator.schema import OperatorConfig
    from darnit.trust.confirmations import record_context_confirmation

    value = "security@test-project.dev"
    operator = OperatorConfig.model_validate({"schema_version": 1})
    record_context_confirmation(
        TARGET, "security_contact", value_digest("security_contact", value), value, None, operator, checkout=repo
    )


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

    def test_raw_na_claim_does_not_skip_remediation(self, tmp_path):
        """A .project/ N/A claim alone does not skip remediation (feature 040, T053).

        Only an honored claim, known from the audit result, exempts a control.
        """
        _create_project_config(
            tmp_path,
            control_overrides={
                "OSPS-VM-02.01": {"status": "n/a", "reason": "Security policy exists in parent organization"},
            }
        )

        result = _apply_control_remediation(
            control_id="OSPS-VM-02.01",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] != "skipped"
        assert result["control_id"] == "OSPS-VM-02.01"

    def test_remediation_proceeds_for_applicable_control(self, tmp_path):
        """Test that remediation proceeds when a different control is N/A."""
        # Mark VM-01.01 as N/A but VM-02.01 is still applicable
        _create_project_config(
            tmp_path,
            control_overrides={
                "OSPS-VM-01.01": {"status": "n/a", "reason": "Only this one is N/A"},
            }
        )

        _confirm_security_contact(tmp_path)
        result = _apply_control_remediation(
            control_id="OSPS-VM-02.01",
            target=TARGET,
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] == "would_apply"
        assert result["control_id"] == "OSPS-VM-02.01"

    def test_remediation_proceeds_without_project_config(self, tmp_path):
        """Test that remediation proceeds normally without .project/ config."""
        _confirm_security_contact(tmp_path)
        result = _apply_control_remediation(
            control_id="OSPS-VM-02.01",
            target=TARGET,
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] == "would_apply"
        assert result["control_id"] == "OSPS-VM-02.01"

    def test_remediation_with_enabled_override(self, tmp_path):
        """Test that enabled status doesn't skip remediation."""
        _create_project_config(
            tmp_path,
            control_overrides={
                "OSPS-VM-02.01": {"status": "enabled", "reason": "Explicitly enabled"},
            }
        )

        _confirm_security_contact(tmp_path)
        result = _apply_control_remediation(
            control_id="OSPS-VM-02.01",
            target=TARGET,
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] == "would_apply"
        assert result["control_id"] == "OSPS-VM-02.01"


class TestDeclarativeRemediationWithProjectConfig:
    """Test that declarative remediation works with .project/ integration."""

    def test_declarative_remediation_ignores_raw_na_claim(self, tmp_path):
        """A raw .project/ N/A claim does not skip declarative remediation (feature 040, T053)."""
        _create_project_config(
            tmp_path,
            control_overrides={
                "OSPS-GV-03.01": {"status": "n/a", "reason": "Contributing guide maintained externally"},
            }
        )

        result = _apply_control_remediation(
            control_id="OSPS-GV-03.01",
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] != "skipped"


class TestConfigUpdateAfterRemediation:
    """Test that .project/ is updated after successful remediation."""

    def test_config_updated_after_file_create(self, tmp_path):
        """Test that .project/ is updated after creating a file."""
        _create_project_config(tmp_path)

        _confirm_security_contact(tmp_path)
        result = _apply_control_remediation(
            control_id="OSPS-VM-02.01",
            target=TARGET,
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "applied"
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
        _create_project_config(tmp_path)

        _confirm_security_contact(tmp_path)
        result = _apply_control_remediation(
            control_id="OSPS-VM-02.01",
            target=TARGET,
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] == "would_apply"

        # .project/ should NOT be updated
        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config is not None
        if config.security:
            assert config.security.policy is None

    def test_config_created_if_missing(self, tmp_path):
        """Test that .project/ is created if it doesn't exist."""
        _confirm_security_contact(tmp_path)
        result = _apply_control_remediation(
            control_id="OSPS-VM-02.01",
            target=TARGET,
            local_path=str(tmp_path),
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "applied"
        assert result.get("config_updated") is True

        assert (tmp_path / ".project" / "project.yaml").exists()

        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config is not None
        assert config.security.policy.path == "SECURITY.md"
