"""Tests for darnit.attestation.predicate module."""

from datetime import datetime

import pytest

from darnit.attestation.predicate import build_assessment_predicate


class TestBuildAssessmentPredicate:
    """Tests for build_assessment_predicate function."""

    @pytest.fixture
    def sample_results(self):
        """Create sample check results."""
        return [
            {"id": "OSPS-AC-01.01", "status": "PASS", "level": 1, "details": "OK"},
            {"id": "OSPS-AC-01.02", "status": "PASS", "level": 1, "details": "OK"},
            {"id": "OSPS-VM-02.01", "status": "FAIL", "level": 1, "details": "Missing SECURITY.md"},
            {"id": "OSPS-AC-02.01", "status": "PASS", "level": 2, "details": "OK"},
            {"id": "OSPS-AC-03.01", "status": "WARN", "level": 3, "details": "Warning"},
            {"id": "OSPS-QA-07.01", "status": "N/A", "level": 3, "details": "Not applicable"},
        ]

    @pytest.mark.unit
    def test_basic_predicate_structure(self, sample_results):
        """Test predicate has correct top-level structure."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123def456",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        assert "assessor" in predicate
        assert "timestamp" in predicate
        assert "baseline" in predicate
        assert "repository" in predicate
        assert "summary" in predicate
        assert "levels" in predicate
        assert "controls" in predicate

    @pytest.mark.unit
    def test_assessor_info(self, sample_results):
        """Test assessor information is correct."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        assert predicate["assessor"]["name"] == "openssf-baseline-mcp"
        assert predicate["assessor"]["version"] == "0.1.0"
        assert "uri" in predicate["assessor"]

    @pytest.mark.unit
    def test_baseline_info(self, sample_results):
        """Test baseline specification information."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        assert predicate["baseline"]["version"] == "2025.10.10"
        assert "specification" in predicate["baseline"]
        assert "baseline.openssf.org" in predicate["baseline"]["specification"]

    @pytest.mark.unit
    def test_repository_info(self, sample_results):
        """Test repository information is captured."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        assert predicate["repository"]["url"] == "https://github.com/testorg/testrepo"
        assert predicate["repository"]["commit"] == "abc123"
        assert predicate["repository"]["ref"] == "main"

    @pytest.mark.unit
    def test_repository_without_ref(self, sample_results):
        """Test repository info when ref is None."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref=None,
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        assert "ref" not in predicate["repository"]

    @pytest.mark.unit
    def test_summary_counts(self, sample_results):
        """Test summary counts are correct."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        summary = predicate["summary"]
        assert summary["level_assessed"] == 3
        assert summary["total_controls"] == 6
        assert summary["passed"] == 3  # 3 PASS
        assert summary["failed"] == 1  # 1 FAIL
        assert summary["warnings"] == 1  # 1 WARN
        assert summary["not_applicable"] == 1  # 1 N/A

    @pytest.mark.unit
    def test_level_compliance(self, sample_results):
        """Test level compliance calculation."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        levels = predicate["levels"]
        # Level 1 has 1 fail, so not compliant
        assert levels["1"]["compliant"] is False
        assert levels["1"]["failed"] == 1

    @pytest.mark.unit
    def test_controls_list(self, sample_results):
        """Test controls are properly formatted."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        controls = predicate["controls"]
        assert len(controls) == 6

        # Check first control
        ctrl = controls[0]
        assert "id" in ctrl
        assert "level" in ctrl
        assert "category" in ctrl
        assert "status" in ctrl
        assert "message" in ctrl
        assert "source" in ctrl

    @pytest.mark.unit
    def test_control_category_extraction(self, sample_results):
        """Test control category is extracted from ID."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        controls = predicate["controls"]
        # OSPS-AC-01.01 should have category "AC"
        ac_control = next(c for c in controls if c["id"] == "OSPS-AC-01.01")
        assert ac_control["category"] == "AC"

        # OSPS-VM-02.01 should have category "VM"
        vm_control = next(c for c in controls if c["id"] == "OSPS-VM-02.01")
        assert vm_control["category"] == "VM"

    @pytest.mark.unit
    def test_timestamp_is_valid_iso(self, sample_results):
        """Test timestamp is valid ISO format."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        # Should not raise
        timestamp = datetime.fromisoformat(predicate["timestamp"].replace("Z", "+00:00"))
        assert timestamp is not None

    @pytest.mark.unit
    def test_configuration_section(self, sample_results):
        """Test configuration section."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=3,
            results=sample_results,
            project_config=None,
            adapters_used=["builtin"]
        )

        config = predicate["configuration"]
        assert config["project_type"] == "software"
        assert config["adapters_used"] == ["builtin"]

    @pytest.mark.unit
    def test_control_with_evidence(self):
        """Test control with evidence is included."""
        results = [
            {
                "id": "OSPS-VM-02.01",
                "status": "PASS",
                "level": 1,
                "details": "Found",
                "evidence": {"file": "SECURITY.md"}
            }
        ]
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=1,
            results=results,
            project_config=None,
            adapters_used=["builtin"]
        )

        controls = predicate["controls"]
        assert len(controls) == 1
        assert controls[0]["evidence"] == {"file": "SECURITY.md"}

    @pytest.mark.unit
    def test_control_with_source(self):
        """Test control source is preserved."""
        results = [
            {
                "id": "OSPS-AC-01.01",
                "status": "PASS",
                "level": 1,
                "details": "OK",
                "source": "sieve"
            }
        ]
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=1,
            results=results,
            project_config=None,
            adapters_used=["sieve"]
        )

        controls = predicate["controls"]
        assert controls[0]["source"] == "sieve"

    @pytest.mark.unit
    def test_empty_results(self):
        """Test with empty results list."""
        predicate = build_assessment_predicate(
            owner="testorg",
            repo="testrepo",
            commit="abc123",
            ref="main",
            level=1,
            results=[],
            project_config=None,
            adapters_used=["builtin"]
        )

        assert predicate["summary"]["total_controls"] == 0
        assert predicate["summary"]["passed"] == 0
        assert predicate["controls"] == []
