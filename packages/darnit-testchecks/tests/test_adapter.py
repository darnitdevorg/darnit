"""Tests for the TrivialCheckAdapter and user config integration."""

import sys
from pathlib import Path

# Add package paths for testing without installation
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "darnit" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from darnit.config.merger import load_effective_config, load_user_config
from darnit.core.models import CheckStatus

from darnit_testchecks import get_framework_path
from darnit_testchecks.adapters import (
    TrivialCheckAdapter,
    TrivialRemediationAdapter,
    get_test_check_adapter,
    get_test_remediation_adapter,
)


class TestAdapterBasics:
    """Tests for adapter basic functionality."""

    def test_adapter_singleton(self):
        """Adapter should be a singleton."""
        adapter1 = get_test_check_adapter()
        adapter2 = get_test_check_adapter()
        assert adapter1 is adapter2

    def test_adapter_name(self):
        """Adapter should have correct name."""
        adapter = get_test_check_adapter()
        assert adapter.name() == "testchecks"

    def test_adapter_capabilities(self):
        """Adapter should report capabilities."""
        adapter = get_test_check_adapter()
        caps = adapter.capabilities()

        assert caps.supports_batch is True
        assert len(caps.control_ids) == 12
        assert "TEST-DOC-01" in caps.control_ids
        assert "TEST-SEC-01" in caps.control_ids

    def test_remediation_adapter_singleton(self):
        """Remediation adapter should be a singleton."""
        adapter1 = get_test_remediation_adapter()
        adapter2 = get_test_remediation_adapter()
        assert adapter1 is adapter2

    def test_remediation_capabilities(self):
        """Remediation adapter should report limited capabilities."""
        adapter = get_test_remediation_adapter()
        caps = adapter.capabilities()

        assert caps.supports_batch is False
        assert "TEST-DOC-01" in caps.control_ids
        assert "TEST-IGN-01" in caps.control_ids


class TestAdapterCheck:
    """Tests for adapter check() method."""

    def test_check_single_control(self, minimal_repo: Path):
        """Should check a single control."""
        adapter = TrivialCheckAdapter()
        result = adapter.check(
            control_id="TEST-DOC-01",
            owner="",
            repo="test",
            local_path=str(minimal_repo),
            config={},
        )

        assert result.control_id == "TEST-DOC-01"
        assert result.status == CheckStatus.PASS
        assert result.source == "testchecks"

    def test_check_unknown_control(self, temp_repo: Path):
        """Should return error for unknown control."""
        adapter = TrivialCheckAdapter()
        result = adapter.check(
            control_id="UNKNOWN-01",
            owner="",
            repo="test",
            local_path=str(temp_repo),
            config={},
        )

        assert result.control_id == "UNKNOWN-01"
        assert result.status == CheckStatus.ERROR
        assert "Unknown control" in result.message


class TestAdapterBatch:
    """Tests for adapter check_batch() method."""

    def test_batch_check_all_controls(self, complete_repo: Path):
        """Should check all controls in batch."""
        adapter = TrivialCheckAdapter()
        control_ids = list(adapter.capabilities().control_ids)

        results = adapter.check_batch(
            control_ids=control_ids,
            owner="",
            repo="test",
            local_path=str(complete_repo),
            config={},
        )

        assert len(results) == 12
        # All should pass for complete_repo
        for result in results:
            assert result.status == CheckStatus.PASS, f"{result.control_id}: {result.message}"

    def test_batch_check_subset(self, minimal_repo: Path):
        """Should check subset of controls."""
        adapter = TrivialCheckAdapter()

        results = adapter.check_batch(
            control_ids=["TEST-DOC-01", "TEST-LIC-01"],
            owner="",
            repo="test",
            local_path=str(minimal_repo),
            config={},
        )

        assert len(results) == 2
        assert all(r.status == CheckStatus.PASS for r in results)

    def test_batch_mixed_results(self, minimal_repo: Path):
        """Should return mixed results for partial compliance."""
        adapter = TrivialCheckAdapter()

        results = adapter.check_batch(
            control_ids=["TEST-DOC-01", "TEST-DOC-02"],  # README exists, CHANGELOG doesn't
            owner="",
            repo="test",
            local_path=str(minimal_repo),
            config={},
        )

        results_dict = {r.control_id: r for r in results}
        assert results_dict["TEST-DOC-01"].status == CheckStatus.PASS
        assert results_dict["TEST-DOC-02"].status == CheckStatus.FAIL


class TestRemediation:
    """Tests for remediation adapter."""

    def test_remediate_readme_dry_run(self, temp_repo: Path):
        """Should show what would be created in dry run."""
        adapter = TrivialRemediationAdapter()
        result = adapter.remediate(
            control_id="TEST-DOC-01",
            owner="",
            repo="test-repo",
            local_path=str(temp_repo),
            config={},
            dry_run=True,
        )

        assert result.success is True
        assert "Would create" in result.message
        assert not (temp_repo / "README.md").exists()

    def test_remediate_readme_actual(self, temp_repo: Path):
        """Should create README when not dry run."""
        adapter = TrivialRemediationAdapter()
        result = adapter.remediate(
            control_id="TEST-DOC-01",
            owner="",
            repo="test-repo",
            local_path=str(temp_repo),
            config={},
            dry_run=False,
        )

        assert result.success is True
        assert "Created" in result.message
        assert (temp_repo / "README.md").exists()
        assert "test-repo" in (temp_repo / "README.md").read_text()

    def test_remediate_gitignore(self, temp_repo: Path):
        """Should create .gitignore with security patterns."""
        adapter = TrivialRemediationAdapter()
        result = adapter.remediate(
            control_id="TEST-IGN-01",
            owner="",
            repo="test",
            local_path=str(temp_repo),
            config={},
            dry_run=False,
        )

        assert result.success is True
        gitignore = (temp_repo / ".gitignore").read_text()
        assert ".env" in gitignore
        assert "*.key" in gitignore

    def test_remediate_unknown_control(self, temp_repo: Path):
        """Should fail for unsupported control."""
        adapter = TrivialRemediationAdapter()
        result = adapter.remediate(
            control_id="TEST-SEC-01",  # Not remediable
            owner="",
            repo="test",
            local_path=str(temp_repo),
            config={},
            dry_run=True,
        )

        assert result.success is False
        assert "No remediation available" in result.message


class TestUserConfigIntegration:
    """Tests for user config override integration."""

    def test_load_user_config(self, temp_repo: Path, user_config_content: str):
        """Should load user config from .baseline.toml."""
        (temp_repo / ".baseline.toml").write_text(user_config_content)

        user_config = load_user_config(temp_repo)

        assert user_config is not None
        assert user_config.extends == "testchecks"
        assert "TEST-QA-01" in user_config.controls
        assert "TEST-QA-02" in user_config.controls

    def test_effective_config_excludes_controls(self, temp_repo: Path, user_config_content: str):
        """Effective config should exclude n/a controls."""
        (temp_repo / ".baseline.toml").write_text(user_config_content)

        effective = load_effective_config(get_framework_path(), temp_repo)

        excluded = effective.get_excluded_controls()
        assert "TEST-QA-01" in excluded
        assert "TEST-QA-02" in excluded
        assert excluded["TEST-QA-01"] == "TODOs are acceptable"

    def test_effective_config_applicable_controls(self, temp_repo: Path, user_config_content: str):
        """Effective config should have correct applicable controls."""
        (temp_repo / ".baseline.toml").write_text(user_config_content)

        effective = load_effective_config(get_framework_path(), temp_repo)

        # 12 total - 2 excluded = 10 applicable
        applicable = [c for c in effective.controls.values() if c.is_applicable()]
        assert len(applicable) == 10

        # Excluded controls should not be applicable
        assert not effective.controls["TEST-QA-01"].is_applicable()
        assert not effective.controls["TEST-QA-02"].is_applicable()

        # Other controls should be applicable
        assert effective.controls["TEST-DOC-01"].is_applicable()
        assert effective.controls["TEST-SEC-01"].is_applicable()

    def test_effective_config_without_user_config(self, temp_repo: Path):
        """Effective config should work without user config."""
        effective = load_effective_config(get_framework_path(), temp_repo)

        # All 12 controls should be applicable
        applicable = [c for c in effective.controls.values() if c.is_applicable()]
        assert len(applicable) == 12


class TestEndToEnd:
    """End-to-end tests combining multiple components."""

    def test_full_audit_flow(self, complete_repo: Path, user_config_content: str):
        """Should run full audit with user config."""
        # Add user config
        (complete_repo / ".baseline.toml").write_text(user_config_content)

        # Load effective config
        effective = load_effective_config(get_framework_path(), complete_repo)

        # Get applicable controls
        applicable_ids = [
            cid for cid, ctrl in effective.controls.items()
            if ctrl.is_applicable()
        ]

        # Run checks
        adapter = TrivialCheckAdapter()
        results = adapter.check_batch(
            control_ids=applicable_ids,
            owner="",
            repo="test",
            local_path=str(complete_repo),
            config={},
        )

        # All applicable controls should pass
        for result in results:
            assert result.status == CheckStatus.PASS, f"{result.control_id}: {result.message}"

    def test_audit_violations_with_exclusions(self, repo_with_violations: Path, user_config_content: str):
        """Should pass when violations are excluded."""
        # Add user config that excludes the violated controls
        (repo_with_violations / ".baseline.toml").write_text(user_config_content)

        effective = load_effective_config(get_framework_path(), repo_with_violations)

        # These should be excluded
        assert not effective.controls["TEST-QA-01"].is_applicable()
        assert not effective.controls["TEST-QA-02"].is_applicable()

        # But TEST-SEC-01 is not excluded, should still fail
        adapter = TrivialCheckAdapter()
        result = adapter.check(
            control_id="TEST-SEC-01",
            owner="",
            repo="test",
            local_path=str(repo_with_violations),
            config={},
        )
        assert result.status == CheckStatus.FAIL
