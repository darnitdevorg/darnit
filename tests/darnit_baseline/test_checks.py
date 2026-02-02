"""Tests for darnit_baseline checks module."""

from pathlib import Path

import pytest

from darnit_baseline.checks import (
    run_level1_checks,
    run_level2_checks,
    run_level3_checks,
)


class TestLevel1Checks:
    """Tests for Level 1 checks."""

    @pytest.mark.integration
    def test_run_level1_checks_returns_list(self, sample_project_files: Path):
        """Test run_level1_checks returns a list of results."""
        results = run_level1_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(sample_project_files),
            default_branch="main"
        )
        assert isinstance(results, list)
        assert len(results) > 0

    @pytest.mark.integration
    def test_level1_results_have_required_fields(self, sample_project_files: Path):
        """Test Level 1 results have required fields."""
        results = run_level1_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(sample_project_files),
            default_branch="main"
        )
        for result in results:
            assert "id" in result
            assert "status" in result
            assert "details" in result
            assert "level" in result

    @pytest.mark.integration
    def test_level1_results_have_valid_status(self, sample_project_files: Path):
        """Test Level 1 results have valid status values."""
        results = run_level1_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(sample_project_files),
            default_branch="main"
        )
        valid_statuses = {"PASS", "FAIL", "WARN", "N/A", "ERROR"}
        for result in results:
            assert result["status"] in valid_statuses

    @pytest.mark.integration
    def test_security_md_detected(self, sample_project_files: Path):
        """Test SECURITY.md is detected as passing."""
        results = run_level1_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(sample_project_files),
            default_branch="main"
        )
        # Find the security policy control
        vm_controls = [r for r in results if r["id"].startswith("OSPS-VM-")]
        # At least one should pass due to SECURITY.md
        assert any(r["status"] == "PASS" for r in vm_controls)


class TestLevel2Checks:
    """Tests for Level 2 checks."""

    @pytest.mark.integration
    def test_run_level2_checks_returns_list(self, sample_project_files: Path):
        """Test run_level2_checks returns a list of results."""
        results = run_level2_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(sample_project_files),
            default_branch="main"
        )
        assert isinstance(results, list)
        assert len(results) > 0

    @pytest.mark.integration
    def test_level2_results_are_level_2(self, sample_project_files: Path):
        """Test all Level 2 results have level=2."""
        results = run_level2_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(sample_project_files),
            default_branch="main"
        )
        for result in results:
            assert result["level"] == 2


class TestLevel3Checks:
    """Tests for Level 3 checks."""

    @pytest.mark.integration
    def test_run_level3_checks_returns_list(self, sample_project_files: Path):
        """Test run_level3_checks returns a list of results."""
        results = run_level3_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(sample_project_files),
            default_branch="main"
        )
        assert isinstance(results, list)
        assert len(results) > 0

    @pytest.mark.integration
    def test_level3_results_are_level_3(self, sample_project_files: Path):
        """Test all Level 3 results have level=3."""
        results = run_level3_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(sample_project_files),
            default_branch="main"
        )
        for result in results:
            assert result["level"] == 3


class TestCheckEdgeCases:
    """Tests for edge cases in checks."""

    @pytest.mark.integration
    def test_empty_repo(self, temp_git_repo: Path):
        """Test checks on minimal repo."""
        results = run_level1_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(temp_git_repo),
            default_branch="main"
        )
        # Should still return results, most will be FAIL
        assert isinstance(results, list)
        assert len(results) > 0

    @pytest.mark.integration
    def test_missing_files_detected(self, temp_git_repo: Path):
        """Test missing security files are detected as FAIL."""
        results = run_level1_checks(
            owner="testorg",
            repo="testrepo",
            local_path=str(temp_git_repo),
            default_branch="main"
        )
        # Find controls that require files (VM = Vulnerability Management)
        vm_controls = [r for r in results if r["id"].startswith("OSPS-VM-")]
        # Most should fail without SECURITY.md
        fail_count = sum(1 for r in vm_controls if r["status"] == "FAIL")
        assert fail_count > 0
