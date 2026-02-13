"""Tests for the sieve orchestrator."""

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.models import (
    CheckContext,
    ControlSpec,
    LLMConsultationResponse,
    PassOutcome,
)
from darnit.sieve.orchestrator import SieveOrchestrator


def _make_context() -> CheckContext:
    return CheckContext(
        owner="test-org",
        repo="test-repo",
        local_path="/tmp/test",
        default_branch="main",
        control_id="TEST-01",
    )


class TestVerifyWithLlmResponse:
    """Test verify_with_llm_response reads config from handler_invocations."""

    def test_confidence_threshold_from_llm_eval_handler(self):
        """confidence_threshold is read from the llm_eval handler invocation."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="llm_eval", confidence_threshold=0.9),
                ],
            },
        )

        # Confidence 0.85 is below 0.9 threshold → should WARN
        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.85,
            reasoning="Looks good",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "WARN"

    def test_default_confidence_threshold(self):
        """Default confidence_threshold of 0.8 when no llm_eval handler."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="manual", steps=["Check it"]),
                ],
            },
        )

        # Confidence 0.85 is above default 0.8 threshold → should PASS
        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.85,
            reasoning="Looks good",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "PASS"

    def test_verification_steps_from_manual_handler(self):
        """verification_steps are read from the manual handler invocation."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        expected_steps = ["Step 1", "Step 2", "Step 3"]
        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="llm_eval", confidence_threshold=0.95),
                    HandlerInvocation(handler="manual", steps=expected_steps),
                ],
            },
        )

        # Low confidence → falls through to manual → should use custom steps
        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.5,
            reasoning="Not sure",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "WARN"
        assert result.verification_steps == expected_steps

    def test_missing_handler_invocations_uses_defaults(self):
        """When no handler_invocations, uses default threshold and generic steps."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={},
        )

        # Low confidence → should WARN with generic steps
        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.5,
            reasoning="Not sure",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "WARN"
        assert result.verification_steps is not None
        assert "Review LLM analysis above" in result.verification_steps[0]

    def test_high_confidence_pass(self):
        """High confidence above threshold returns PASS."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="llm_eval", confidence_threshold=0.8),
                ],
            },
        )

        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.95,
            reasoning="Verified",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "PASS"
        assert result.confidence == 0.95

    def test_high_confidence_fail(self):
        """High confidence FAIL above threshold returns FAIL."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="llm_eval", confidence_threshold=0.8),
                ],
            },
        )

        response = LLMConsultationResponse(
            status=PassOutcome.FAIL,
            confidence=0.95,
            reasoning="Not compliant",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "FAIL"
