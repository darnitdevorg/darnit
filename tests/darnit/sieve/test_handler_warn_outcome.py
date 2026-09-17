"""Conclusive WARN handler outcome (feature 037, FR-016 / FR-017).

Covers contracts/handler-warn-outcome.md obligations T-1 through T-8.

Before this feature a handler could only report PASS, FAIL, INCONCLUSIVE, or
ERROR. A handler that had read the evidence and found it insufficient had to
return INCONCLUSIVE, which sends the pipeline onward and eventually produces a
WARN whose message is the fixed string "Could not automatically verify -
manual verification required". The operator then reads, about a file the tool
successfully parsed, that the tool could not verify it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.handler_registry import (
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)
from darnit.sieve.models import CheckContext, ControlSpec, PassOutcome
from darnit.sieve.orchestrator import (
    SieveOrchestrator,
    StepDisposition,
    _apply_cel_expr,
    resolve_step_result,
)

WARN_MESSAGE = "read the file; direct deps pinned, transitive deps float"
FALLTHROUGH_MESSAGE = "Could not automatically verify - manual verification required"


def _control(control_id: str, invocations: list[HandlerInvocation]) -> ControlSpec:
    return ControlSpec(
        control_id=control_id,
        level=1,
        domain="TEST",
        name="Test",
        description="Test",
        metadata={"handler_invocations": invocations},
    )


def _ctx() -> CheckContext:
    return CheckContext(
        owner="test",
        repo="repo",
        local_path="/tmp",
        default_branch="main",
        control_id="test",
    )


def _register(name: str, authority: str, **result_kwargs) -> None:
    def handler(config, context):
        return HandlerResult(
            status=HandlerResultStatus.WARN,
            message=WARN_MESSAGE,
            **result_kwargs,
        )

    get_sieve_handler_registry().register(name, "deterministic", handler, default_authority=authority)


class TestDispositionRule:
    """Contract C-2. The WARN row of the table is the PASS/FAIL row."""

    @pytest.mark.unit
    @pytest.mark.parametrize("authority", ["dispositive", "asserted"])
    def test_terminal_authority_concludes_warn(self, authority: str) -> None:
        assert resolve_step_result(HandlerResultStatus.WARN, authority, False) is (StepDisposition.CONCLUDE_WARN)

    @pytest.mark.unit
    @pytest.mark.parametrize("authority", ["suggestive", None])
    def test_non_terminal_authority_continues(self, authority) -> None:
        """An LLM must not be able to halt verification with a WARN any more
        than it can manufacture a PASS."""
        assert resolve_step_result(HandlerResultStatus.WARN, authority, False) is (
            StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE
        )

    @pytest.mark.unit
    def test_non_terminal_warn_on_last_step_is_inconclusive(self) -> None:
        assert resolve_step_result(HandlerResultStatus.WARN, "suggestive", True) is (
            StepDisposition.TERMINATE_INCONCLUSIVE
        )

    @pytest.mark.unit
    def test_inconclusive_behaviour_is_unchanged(self) -> None:
        """Principle V: INCONCLUSIVE still continues. WARN did not displace it."""
        assert (
            resolve_step_result(HandlerResultStatus.INCONCLUSIVE, "dispositive", False)
            is StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE
        )


class TestEndToEnd:
    @pytest.mark.unit
    def test_dispositive_warn_concludes_with_its_own_message(self) -> None:
        """Contract T-1. The whole point of the feature."""
        _register("warn_dispositive", "dispositive", confidence=0.8)
        result = SieveOrchestrator().verify(
            _control("WARN-01", [HandlerInvocation(handler="warn_dispositive")]), _ctx()
        )
        assert result.status == "WARN"
        assert result.message == WARN_MESSAGE
        assert result.message != FALLTHROUGH_MESSAGE

    @pytest.mark.unit
    def test_suggestive_warn_does_not_conclude(self) -> None:
        """Contract T-2: a later dispositive step still decides."""
        _register("warn_suggestive", "suggestive", evidence={"seen": "yes"})

        def passes(config, context):
            return HandlerResult(status=HandlerResultStatus.PASS, message="file exists", confidence=1.0)

        get_sieve_handler_registry().register(
            "pass_after_warn", "deterministic", passes, default_authority="dispositive"
        )
        result = SieveOrchestrator().verify(
            _control(
                "WARN-02",
                [
                    HandlerInvocation(handler="warn_suggestive"),
                    HandlerInvocation(handler="pass_after_warn"),
                ],
            ),
            _ctx(),
        )
        assert result.status == "PASS"
        assert result.evidence.get("seen") == "yes", "evidence must survive"

    @pytest.mark.unit
    def test_suggestive_warn_as_last_step_terminates_inconclusive(self) -> None:
        """Contract T-3."""
        _register("warn_suggestive_only", "suggestive")
        result = SieveOrchestrator().verify(
            _control("WARN-03", [HandlerInvocation(handler="warn_suggestive_only")]),
            _ctx(),
        )
        assert result.status == "WARN"
        assert result.message == FALLTHROUGH_MESSAGE

    @pytest.mark.unit
    def test_warn_carries_result_fields(self) -> None:
        """Contract T-4."""
        _register("warn_fields", "dispositive", confidence=0.8, evidence={"k": "v"})
        result = SieveOrchestrator().verify(_control("WARN-04", [HandlerInvocation(handler="warn_fields")]), _ctx())
        assert result.confidence == 0.8
        assert result.evidence.get("k") == "v"
        assert result.resolving_pass_handler == "warn_fields"
        assert result.resolving_pass_index == 0
        assert result.authority == "dispositive"

    @pytest.mark.unit
    def test_warn_preserves_error_class(self) -> None:
        """Contract T-5.

        Unlike CONCLUDE_PASS -- where HandlerResult forbids the pairing --
        nothing forbids WARN with an error_class, so it must be threaded
        rather than reasoned away.
        """
        _register("warn_error_class", "dispositive", error_class="network")
        result = SieveOrchestrator().verify(
            _control("WARN-05", [HandlerInvocation(handler="warn_error_class")]), _ctx()
        )
        assert result.error_class == "network"

    @pytest.mark.unit
    def test_pass_history_records_warn_not_inconclusive(self) -> None:
        """Contract T-7.

        pass_history is the audit trail a reviewer reads to check a verdict.
        Recording a pass that concluded WARN as INCONCLUSIVE would contradict
        the control's own status.
        """
        _register("warn_history", "dispositive", confidence=0.8)
        result = SieveOrchestrator().verify(_control("WARN-06", [HandlerInvocation(handler="warn_history")]), _ctx())
        outcomes = [attempt.result.outcome for attempt in result.pass_history]
        assert PassOutcome.WARN in outcomes
        assert PassOutcome.INCONCLUSIVE not in outcomes


class TestCelPostStep:
    """Contract T-6 / C-6.

    Features 026 and 036 both shipped bugs where new result vocabulary was
    dropped inside _apply_cel_expr. The correct implementation here is no code
    at all -- the existing guard returns early for anything but PASS/FAIL --
    which is exactly why it needs a test rather than a shrug.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize("config", [{}, {"expr": "1 == 1"}, {"expr": "1 == 2"}])
    def test_warn_passes_through_unchanged(self, config: dict) -> None:
        original = HandlerResult(status=HandlerResultStatus.WARN, message=WARN_MESSAGE, confidence=0.8)
        result = _apply_cel_expr(config, original)
        assert result.status is HandlerResultStatus.WARN
        assert result.message == WARN_MESSAGE


class TestDocumentationIsInSync:
    """T029: give the framework-design.md update a mechanical check.

    validate_sync.py cannot do this -- validate_pass_types_sync only greps a
    hardcoded list of seven handler NAMES against builtin_handlers.py, so it
    passes whether or not the WARN outcome is documented.
    """

    @pytest.mark.unit
    def test_framework_design_documents_the_warn_disposition(self) -> None:
        spec = (Path(__file__).resolve().parents[3] / "docs" / "architecture" / "framework-design.md").read_text(
            encoding="utf-8"
        )
        assert "CONCLUDE_WARN" in spec, (
            "framework-design.md must document the WARN disposition row "
            "(constitution Development Workflow item 3: spec first, then code)"
        )
        assert "`WARN`" in spec
