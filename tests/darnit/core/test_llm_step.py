"""Tests for darnit.core.llm_step (feature 025 T008).

Covers the Protocol shape, MockLLMStep behavior, and PydanticAILLMStep
construction (deferred evaluation).
"""

from __future__ import annotations

import asyncio

import pytest

from darnit.core.llm_step import (
    ConsultationRequest,
    LLMJudgment,
    LLMStep,
    MockLLMStep,
    PydanticAILLMStep,
)


def _run(coro):
    """Small sync wrapper for async test methods; avoids pytest-asyncio setup."""
    return asyncio.new_event_loop().run_until_complete(coro)


class TestMockLLMStep:
    def test_returns_configured_judgment(self) -> None:
        j = LLMJudgment(outcome="yes", confidence=0.9, reasoning="test")
        step = MockLLMStep(j)
        result = _run(step.evaluate(ConsultationRequest(control_id="X", prompt="?")))
        assert result == j

    def test_records_calls(self) -> None:
        step = MockLLMStep(LLMJudgment(outcome="no", confidence=0.5, reasoning=""))
        req = ConsultationRequest(control_id="CTRL", prompt="Q")
        _run(step.evaluate(req))
        assert len(step.calls) == 1
        assert step.calls[0].control_id == "CTRL"


class TestPydanticAILLMStep:
    def test_construction_does_not_require_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Remove any inherited API key; construction must still succeed.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        step = PydanticAILLMStep()
        assert step.model == "anthropic:claude-sonnet-5"

    def test_evaluate_raises_clear_error_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Slice D T047: PydanticAILLMStep.evaluate() constructs an Agent
        lazily; when ANTHROPIC_API_KEY is absent, it raises RuntimeError
        naming the missing env var. Test-friendly: no real LLM call."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        step = PydanticAILLMStep()
        with pytest.raises(RuntimeError) as excinfo:
            _run(step.evaluate(ConsultationRequest(control_id="X", prompt="Q")))
        assert "ANTHROPIC_API_KEY" in str(excinfo.value)

    def test_model_and_version_come_from_the_provider(self) -> None:
        """Feature 041 T029: the model cannot name itself; the step records what answered."""

        class _Response:
            model_name = "claude-sonnet-5-20260801"

        class _Result:
            output = LLMJudgment(
                outcome="yes", confidence=0.9, reasoning="r", cited_evidence=["quote"], model="spoofed"
            )
            response = _Response()

        class _Agent:
            async def run(self, prompt: str) -> _Result:
                return _Result()

        step = PydanticAILLMStep()
        step._agent = _Agent()

        judgment = _run(step.evaluate(ConsultationRequest(control_id="X", prompt="Q")))

        assert judgment.model == "anthropic:claude-sonnet-5"
        assert judgment.model_version == "claude-sonnet-5-20260801"
        assert judgment.cited_evidence == ["quote"]


class TestLLMStepProtocol:
    def test_mock_satisfies_protocol(self) -> None:
        step = MockLLMStep(LLMJudgment(outcome="yes", confidence=1.0, reasoning=""))
        # runtime_checkable Protocol confirms structural conformance.
        assert isinstance(step, LLMStep)

    def test_pydantic_ai_satisfies_protocol(self) -> None:
        step = PydanticAILLMStep()
        assert isinstance(step, LLMStep)

    def test_arbitrary_class_without_evaluate_does_not_satisfy(self) -> None:
        class NotAnLLMStep:
            pass

        assert not isinstance(NotAnLLMStep(), LLMStep)
