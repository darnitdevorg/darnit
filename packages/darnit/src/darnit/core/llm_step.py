"""``LLMStep`` Protocol and default Pydantic AI implementation.

RFC-0001 Stage 1. See specs/025-rfc0001-stage1/research.md section R6.

The Protocol makes the LLM SDK swappable at code time; the default
``PydanticAILLMStep`` implementation uses ``pydantic-ai-slim[anthropic]``
(a required runtime dependency, per Q3 clarification). Tests inject
``MockLLMStep`` to avoid live API calls.

Slice A: Protocol + Mock only. ``PydanticAILLMStep.evaluate`` raises
``NotImplementedError`` until Slice D (T047) wires the real Agent call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel


class ConsultationRequest(BaseModel):
    """Input to an ``LLMStep``. See data-model.md section 8."""

    control_id: str
    prompt: str
    files_to_include: list[Path] = []
    max_tokens: int = 4096
    response_schema: dict[str, Any] | None = None


class LLMJudgment(BaseModel):
    """Output of an ``LLMStep``. See data-model.md section 8.

    Note ``confidence`` is a float in ``[0.0, 1.0]`` but is NEVER a
    decision input at Check phase (Constitution II + RFC-0001). It exists
    only for evidence provenance and Collect-phase presentation filtering.
    """

    outcome: Literal["yes", "no", "inconclusive"]
    confidence: float
    reasoning: str
    raw_response: dict[str, Any] = {}


@runtime_checkable
class LLMStep(Protocol):
    """Contract for invoking an LLM with structured output and validation.

    Any implementation satisfying this Protocol (Pydantic AI default,
    LangChain, hand-roll, mock-for-tests) can be injected into the
    strategy runner. The runner code MUST NOT import a specific LLM SDK;
    the coupling belongs behind this seam.
    """

    async def evaluate(self, request: ConsultationRequest) -> LLMJudgment: ...


class PydanticAILLMStep:
    """Default ``LLMStep`` implementation using ``pydantic-ai-slim[anthropic]``.

    Constructs a ``pydantic_ai.Agent`` on demand (first ``evaluate()`` call)
    and caches it per-instance. Requires ``ANTHROPIC_API_KEY`` in the
    environment at call time; construction does NOT require the key so
    tests and CI can instantiate freely without credentials.

    Feature 025 T047. The Protocol makes this SDK swappable at code time
    (one file); this class is the shipping default, not a mandatory type.
    """

    def __init__(self, model: str = "anthropic:claude-sonnet-4-6") -> None:
        self.model = model
        self._agent: Any = None  # lazily constructed on first evaluate()

    def _build_agent(self) -> Any:
        """Lazily construct the pydantic_ai.Agent. Raises a clear error if
        the LLM SDK's env credentials are missing."""
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "PydanticAILLMStep.evaluate requires ANTHROPIC_API_KEY in the "
                "environment. Inject a MockLLMStep in tests, or set the env var "
                "for interactive use."
            )
        from pydantic_ai import Agent

        return Agent(
            model=self.model,
            output_type=LLMJudgment,
            system_prompt=(
                "You are a compliance-audit assistant. Return a JSON judgment "
                "matching the LLMJudgment schema. Outcomes: 'yes' (evidence "
                "supports the claim), 'no' (evidence contradicts it), "
                "'inconclusive' (insufficient evidence). Include reasoning "
                "citing the specific evidence you saw. Confidence is your "
                "self-reported certainty (0.0-1.0); do NOT inflate it."
            ),
        )

    async def evaluate(self, request: ConsultationRequest) -> LLMJudgment:
        if self._agent is None:
            self._agent = self._build_agent()

        # Assemble the user prompt from the request. Include file contents
        # if provided; cap each at 10K chars to bound context usage.
        parts: list[str] = [f"Control: {request.control_id}", "", request.prompt]
        for path in request.files_to_include[:5]:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")[:10000]
                parts.extend(["", f"--- {path.name} ---", content])
            except OSError:
                continue
        user_prompt = "\n".join(parts)

        result = await self._agent.run(user_prompt)
        # pydantic_ai returns a RunResult whose `.output` is the structured
        # output cast to LLMJudgment.
        return result.output  # type: ignore[no-any-return]


class MockLLMStep:
    """Test helper: returns a caller-configured ``LLMJudgment`` on every call.

    Placed alongside ``LLMStep`` (rather than in a test-only module) so
    consuming tests import it via ``from darnit.core.llm_step import MockLLMStep``.
    Fine to have in production code -- this is a first-class fake, not a
    hidden test hook.
    """

    def __init__(self, judgment: LLMJudgment) -> None:
        self._judgment = judgment
        self.calls: list[ConsultationRequest] = []

    async def evaluate(self, request: ConsultationRequest) -> LLMJudgment:
        self.calls.append(request)
        return self._judgment
