"""Tests for darnit.sieve.models."""

import pytest

from darnit.sieve.models import (
    CheckContext,
    ControlSpec,
    PassAttempt,
    PassOutcome,
    PassResult,
    SieveResult,
    VerificationPhase,
)


class TestEnums:
    """Tests for sieve model enums."""

    @pytest.mark.unit
    def test_verification_phase_values(self):
        """VerificationPhase exposes the expected stable values."""
        assert VerificationPhase.DETERMINISTIC.value == "deterministic"
        assert VerificationPhase.PATTERN.value == "pattern"
        assert VerificationPhase.LLM.value == "llm"
        assert VerificationPhase.MANUAL.value == "manual"

    @pytest.mark.unit
    def test_pass_outcome_values(self):
        """PassOutcome exposes the expected stable values."""
        assert PassOutcome.PASS.value == "pass"
        assert PassOutcome.FAIL.value == "fail"
        assert PassOutcome.INCONCLUSIVE.value == "inconclusive"
        assert PassOutcome.ERROR.value == "error"


class TestCheckContext:
    """Tests for CheckContext dataclass."""

    @pytest.mark.unit
    def test_construction_and_defaults(self):
        """CheckContext stores required fields and initializes defaults."""
        context = CheckContext(
            owner="kusari-oss",
            repo="darnit",
            local_path="/tmp/darnit",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        assert context.owner == "kusari-oss"
        assert context.repo == "darnit"
        assert context.local_path == "/tmp/darnit"
        assert context.default_branch == "main"
        assert context.control_id == "OSPS-AC-01.01"
        assert context.control_metadata == {}
        assert context.gathered_evidence == {}
        assert context.project_context == {}
        assert context.locator is None
        assert context.locator_config is None

    @pytest.mark.unit
    def test_optional_fields_are_preserved(self):
        """CheckContext preserves provided metadata and project context."""
        context = CheckContext(
            owner="kusari-oss",
            repo="darnit",
            local_path="/tmp/darnit",
            default_branch="main",
            control_id="OSPS-VM-02.01",
            control_metadata={"level": 2},
            gathered_evidence={"security_md": True},
            project_context={"project.security.policy_path": "SECURITY.md"},
        )

        assert context.control_metadata == {"level": 2}
        assert context.gathered_evidence == {"security_md": True}
        assert context.project_context == {"project.security.policy_path": "SECURITY.md"}


class TestPassResult:
    """Tests for PassResult and PassAttempt dataclasses."""

    @pytest.mark.unit
    def test_pass_result_construction(self):
        """PassResult stores required and optional fields."""
        result = PassResult(
            phase=VerificationPhase.PATTERN,
            outcome=PassOutcome.PASS,
            message="Found matching policy text",
            evidence={"matched_file": "SECURITY.md"},
            confidence=0.9,
            details={"regex": "security policy"},
        )

        assert result.phase == VerificationPhase.PATTERN
        assert result.outcome == PassOutcome.PASS
        assert result.message == "Found matching policy text"
        assert result.evidence == {"matched_file": "SECURITY.md"}
        assert result.confidence == 0.9
        assert result.details == {"regex": "security policy"}

    @pytest.mark.unit
    def test_pass_attempt_wraps_result(self):
        """PassAttempt keeps a result plus execution metadata."""
        result = PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="Required file missing",
        )
        attempt = PassAttempt(
            phase=VerificationPhase.DETERMINISTIC,
            checks_performed=["checked SECURITY.md existence"],
            result=result,
            duration_ms=14,
        )

        assert attempt.phase == VerificationPhase.DETERMINISTIC
        assert attempt.checks_performed == ["checked SECURITY.md existence"]
        assert attempt.result is result
        assert attempt.duration_ms == 14


class TestSieveResult:
    """Tests for SieveResult dataclass."""

    @pytest.mark.unit
    def test_defaults(self):
        """SieveResult optional fields default as expected."""
        result = SieveResult(
            control_id="OSPS-AC-01.01",
            status="PASS",
            message="Control satisfied",
            level=1,
        )

        assert result.conclusive_phase is None
        assert result.pass_history == []
        assert result.confidence is None
        assert result.evidence is None
        assert result.verification_steps is None
        assert result.source == "sieve"
        assert result.resolving_pass_index is None
        assert result.resolving_pass_handler is None

    @pytest.mark.unit
    def test_to_legacy_dict_minimal(self):
        """to_legacy_dict returns the required legacy fields."""
        result = SieveResult(
            control_id="OSPS-VM-02.01",
            status="FAIL",
            message="Security policy missing",
            level=2,
        )

        legacy = result.to_legacy_dict()

        assert legacy == {
            "id": "OSPS-VM-02.01",
            "status": "FAIL",
            "details": "Security policy missing",
            "level": 2,
        }

    @pytest.mark.unit
    def test_to_legacy_dict_includes_optional_fields(self):
        """to_legacy_dict includes extended metadata when present."""
        attempt = PassAttempt(
            phase=VerificationPhase.LLM,
            checks_performed=["asked LLM about SECURITY.md ownership"],
            result=PassResult(
                phase=VerificationPhase.LLM,
                outcome=PassOutcome.INCONCLUSIVE,
                message="Need manual follow-up",
                confidence=0.42,
            ),
            duration_ms=275,
        )
        result = SieveResult(
            control_id="OSPS-GV-01.01",
            status="WARN",
            message="Manual verification required",
            level=3,
            conclusive_phase=VerificationPhase.MANUAL,
            pass_history=[attempt],
            confidence=0.42,
            evidence={"policy_path": "SECURITY.md"},
            verification_steps=["Review ownership metadata"],
            resolving_pass_index=3,
            resolving_pass_handler="manual_review",
        )

        legacy = result.to_legacy_dict()

        assert legacy["sieve_phase"] == "manual"
        assert legacy["confidence"] == 0.42
        assert legacy["verification_steps"] == ["Review ownership metadata"]
        assert legacy["evidence"] == {"policy_path": "SECURITY.md"}
        assert legacy["resolving_pass_index"] == 3
        assert legacy["resolving_pass_handler"] == "manual_review"
        assert legacy["pass_history"] == [
            {
                "phase": "llm",
                "checks_performed": ["asked LLM about SECURITY.md ownership"],
                "result": {
                    "outcome": "inconclusive",
                    "message": "Need manual follow-up",
                    "confidence": 0.42,
                },
                "duration_ms": 275,
            }
        ]


class TestControlSpec:
    """Tests for ControlSpec dataclass."""

    @pytest.mark.unit
    def test_level_and_domain_are_copied_to_tags(self):
        """ControlSpec copies level and domain into tags for uniform filtering."""
        control = ControlSpec(
            control_id="OSPS-AC-01.01",
            level=1,
            domain="AC",
            name="Document access control",
            description="Access control policy exists",
            tags={"severity": "medium"},
        )

        assert control.tags == {
            "severity": "medium",
            "level": 1,
            "domain": "AC",
        }
