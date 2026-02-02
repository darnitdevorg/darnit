"""Tests for darnit.sieve.models module."""

import pytest

from darnit.sieve.models import (
    CheckContext,
    PassAttempt,
    PassOutcome,
    PassResult,
    SieveResult,
    VerificationPhase,
)


class TestVerificationPhase:
    """Tests for VerificationPhase enum."""

    @pytest.mark.unit
    def test_phase_values(self):
        """Test all phase values are accessible."""
        assert VerificationPhase.DETERMINISTIC.value == "deterministic"
        assert VerificationPhase.PATTERN.value == "pattern"
        assert VerificationPhase.LLM.value == "llm"
        assert VerificationPhase.MANUAL.value == "manual"

    @pytest.mark.unit
    def test_phase_count(self):
        """Test we have exactly 4 phases."""
        assert len(VerificationPhase) == 4


class TestPassOutcome:
    """Tests for PassOutcome enum."""

    @pytest.mark.unit
    def test_outcome_values(self):
        """Test all outcome values are accessible."""
        assert PassOutcome.PASS.value == "pass"
        assert PassOutcome.FAIL.value == "fail"
        assert PassOutcome.INCONCLUSIVE.value == "inconclusive"
        assert PassOutcome.ERROR.value == "error"

    @pytest.mark.unit
    def test_outcome_count(self):
        """Test we have exactly 4 outcomes."""
        assert len(PassOutcome) == 4


class TestPassResult:
    """Tests for PassResult dataclass."""

    @pytest.mark.unit
    def test_pass_result(self):
        """Test creating a PASS result."""
        result = PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.PASS,
            message="File exists",
            confidence=1.0
        )
        assert result.outcome == PassOutcome.PASS
        assert result.confidence == 1.0
        assert result.phase == VerificationPhase.DETERMINISTIC

    @pytest.mark.unit
    def test_fail_result_with_evidence(self):
        """Test creating a FAIL result with evidence."""
        result = PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="File not found",
            confidence=1.0,
            evidence={"checked_paths": ["SECURITY.md", ".github/SECURITY.md"]}
        )
        assert result.outcome == PassOutcome.FAIL
        assert "checked_paths" in result.evidence

    @pytest.mark.unit
    def test_inconclusive_result(self):
        """Test creating an INCONCLUSIVE result."""
        result = PassResult(
            phase=VerificationPhase.PATTERN,
            outcome=PassOutcome.INCONCLUSIVE,
            message="Cannot determine",
            confidence=0.5
        )
        assert result.outcome == PassOutcome.INCONCLUSIVE
        assert result.confidence == 0.5


class TestPassAttempt:
    """Tests for PassAttempt dataclass."""

    @pytest.mark.unit
    def test_pass_attempt(self):
        """Test creating a PassAttempt."""
        attempt = PassAttempt(
            phase=VerificationPhase.DETERMINISTIC,
            checks_performed=["file_exists(SECURITY.md)"],
            result=PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="Found",
                confidence=1.0
            ),
            duration_ms=5
        )
        assert attempt.phase == VerificationPhase.DETERMINISTIC
        assert len(attempt.checks_performed) == 1
        assert attempt.duration_ms == 5


class TestSieveResult:
    """Tests for SieveResult dataclass."""

    @pytest.mark.unit
    def test_sieve_result_pass(self):
        """Test creating a PASS SieveResult."""
        result = SieveResult(
            control_id="OSPS-VM-02.01",
            status="PASS",
            message="Security policy found",
            level=1,
            conclusive_phase=VerificationPhase.DETERMINISTIC,
            pass_history=[],
            source="sieve"
        )
        assert result.status == "PASS"
        assert result.conclusive_phase == VerificationPhase.DETERMINISTIC
        assert result.source == "sieve"

    @pytest.mark.unit
    def test_sieve_result_with_history(self):
        """Test SieveResult with pass history."""
        attempt = PassAttempt(
            phase=VerificationPhase.DETERMINISTIC,
            checks_performed=["check1"],
            result=PassResult(
                phase=VerificationPhase.DETERMINISTIC,
                outcome=PassOutcome.PASS,
                message="OK",
                confidence=1.0
            ),
            duration_ms=10
        )
        result = SieveResult(
            control_id="OSPS-AC-01.01",
            status="PASS",
            message="OK",
            level=1,
            conclusive_phase=VerificationPhase.DETERMINISTIC,
            pass_history=[attempt],
            source="sieve"
        )
        assert len(result.pass_history) == 1
        assert result.pass_history[0].duration_ms == 10


class TestCheckContext:
    """Tests for CheckContext dataclass."""

    @pytest.mark.unit
    def test_basic_context(self):
        """Test creating a basic CheckContext."""
        ctx = CheckContext(
            owner="testorg",
            repo="testrepo",
            local_path="/path/to/repo",
            default_branch="main",
            control_id="OSPS-VM-02.01"
        )
        assert ctx.owner == "testorg"
        assert ctx.repo == "testrepo"
        assert ctx.default_branch == "main"
        assert ctx.control_id == "OSPS-VM-02.01"
        assert ctx.gathered_evidence == {}

    @pytest.mark.unit
    def test_context_with_evidence(self):
        """Test CheckContext with pre-gathered evidence."""
        ctx = CheckContext(
            owner="testorg",
            repo="testrepo",
            local_path="/path/to/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            gathered_evidence={"has_security_md": True}
        )
        assert ctx.gathered_evidence["has_security_md"] is True
