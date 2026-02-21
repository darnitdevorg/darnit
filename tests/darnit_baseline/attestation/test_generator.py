"""Tests for darnit_baseline.attestation.generator module."""

import json
from pathlib import Path

import pytest

from darnit.core.models import AuditResult
from darnit_baseline.attestation.generator import (
    BASELINE_PREDICATE_TYPE,
    build_unsigned_statement,
    generate_attestation_from_results,
)


class TestBuildUnsignedStatement:
    """Tests for build_unsigned_statement function."""

    @pytest.fixture
    def sample_predicate(self):
        """Create a sample predicate."""
        return {
            "assessor": {"name": "test", "version": "0.1.0"},
            "summary": {"level_assessed": 1, "passed": 10, "failed": 0},
            "controls": []
        }

    @pytest.mark.unit
    def test_subject_format(self, sample_predicate):
        """Test subject is properly formatted."""
        statement = build_unsigned_statement(
            subject_name="git+https://github.com/test/repo",
            commit="abc123def456",
            predicate_type=BASELINE_PREDICATE_TYPE,
            predicate=sample_predicate
        )

        assert len(statement["subject"]) == 1
        subject = statement["subject"][0]
        assert subject["name"] == "git+https://github.com/test/repo"
        assert subject["digest"]["gitCommit"] == "abc123def456"

class TestGenerateAttestationFromResults:
    """Tests for generate_attestation_from_results function."""

    @pytest.fixture
    def sample_audit_result(self, temp_dir: Path):
        """Create a sample audit result."""
        return AuditResult(
            owner="testorg",
            repo="testrepo",
            local_path=str(temp_dir),
            level=1,
            default_branch="main",
            all_results=[
                {"id": "OSPS-AC-01.01", "status": "PASS", "level": 1, "details": "OK"},
                {"id": "OSPS-VM-02.01", "status": "PASS", "level": 1, "details": "Found"},
            ],
            summary={"passed": 2, "failed": 0, "warnings": 0},
            level_compliance={1: True},
            commit="abc123def456",
            ref="main"
        )

    @pytest.fixture
    def audit_result_no_commit(self, temp_dir: Path):
        """Create an audit result without commit info."""
        return AuditResult(
            owner="testorg",
            repo="testrepo",
            local_path=str(temp_dir),
            level=1,
            default_branch="main",
            all_results=[],
            summary={},
            level_compliance={},
            commit=None,
            ref=None
        )

    @pytest.mark.unit
    def test_no_commit_returns_error(self, audit_result_no_commit):
        """Test that missing commit returns error."""
        result = generate_attestation_from_results(
            audit_result=audit_result_no_commit,
            sign=False
        )

        parsed = json.loads(result)
        assert "error" in parsed
        assert "git commit" in parsed["error"].lower()

    @pytest.mark.unit
    def test_unsigned_attestation(self, sample_audit_result, temp_dir: Path):
        """Test generating unsigned attestation."""
        result = generate_attestation_from_results(
            audit_result=sample_audit_result,
            sign=False,
            output_path=str(temp_dir / "test.intoto.json")
        )

        # Should contain success message
        assert "Attestation saved" in result

        # File should exist
        assert (temp_dir / "test.intoto.json").exists()

        # Read and parse the file
        with open(temp_dir / "test.intoto.json") as f:
            attestation = json.load(f)

        assert attestation["_type"] == "https://in-toto.io/Statement/v1"
        assert attestation["predicateType"] == BASELINE_PREDICATE_TYPE

    @pytest.mark.unit
    def test_unsigned_attestation_subject(self, sample_audit_result, temp_dir: Path):
        """Test unsigned attestation has correct subject."""
        generate_attestation_from_results(
            audit_result=sample_audit_result,
            sign=False,
            output_path=str(temp_dir / "test.intoto.json")
        )

        with open(temp_dir / "test.intoto.json") as f:
            attestation = json.load(f)

        subject = attestation["subject"][0]
        assert subject["name"] == "git+https://github.com/testorg/testrepo"
        assert subject["digest"]["gitCommit"] == "abc123def456"

    @pytest.mark.unit
    def test_unsigned_attestation_predicate(self, sample_audit_result, temp_dir: Path):
        """Test unsigned attestation has correct predicate."""
        generate_attestation_from_results(
            audit_result=sample_audit_result,
            sign=False,
            output_path=str(temp_dir / "test.intoto.json")
        )

        with open(temp_dir / "test.intoto.json") as f:
            attestation = json.load(f)

        predicate = attestation["predicate"]
        assert "assessor" in predicate
        assert "baseline" in predicate
        assert "repository" in predicate
        assert "summary" in predicate
        assert "controls" in predicate

    @pytest.mark.unit
    def test_default_output_path(self, sample_audit_result, temp_dir: Path):
        """Test default output path is used."""
        generate_attestation_from_results(
            audit_result=sample_audit_result,
            sign=False
        )

        # Default filename
        expected_file = temp_dir / "testrepo-baseline-attestation.intoto.json"
        assert expected_file.exists()

    @pytest.mark.unit
    def test_output_dir_parameter(self, sample_audit_result, temp_dir: Path):
        """Test output_dir parameter creates file in specified directory."""
        output_dir = temp_dir / "output"
        output_dir.mkdir()

        generate_attestation_from_results(
            audit_result=sample_audit_result,
            sign=False,
            output_dir=str(output_dir)
        )

        expected_file = output_dir / "testrepo-baseline-attestation.intoto.json"
        assert expected_file.exists()

    @pytest.mark.unit
    def test_signed_without_dependencies(self, sample_audit_result, temp_dir: Path):
        """Test signing behavior when sigstore not available."""
        # Try to sign - should return unsigned with error if sigstore not available
        result = generate_attestation_from_results(
            audit_result=sample_audit_result,
            sign=True,
            output_path=str(temp_dir / "test.sigstore.json")
        )

        # Result should either be signed attestation or error with unsigned statement
        parsed = None
        if "error" in result.lower():
            # Extract JSON from the result
            lines = result.split("\n")
            json_start = None
            for i, line in enumerate(lines):
                if line.strip().startswith("{"):
                    json_start = i
                    break
            if json_start is not None:
                json_str = "\n".join(lines[json_start:])
                parsed = json.loads(json_str)
                assert "error" in parsed or "unsigned_statement" in parsed
        else:
            # Signing succeeded
            assert "Attestation saved" in result
