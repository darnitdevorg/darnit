"""Result model for feature 041 (data-model.md "Result").

Statuses are PASS, FAIL, WARN, N/A, ERROR, PENDING. PENDING replaces
PENDING_LLM and always carries ``pending.kind``; ERROR always carries
``error {class, cause}``.
"""

from __future__ import annotations

import typing

import pytest

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.handler_registry import (
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)
from darnit.sieve.models import CheckStatus, ControlSpec, SieveResult
from darnit.sieve.orchestrator import SieveOrchestrator


def _spec(invocations: list[HandlerInvocation]) -> ControlSpec:
    return ControlSpec(
        control_id="RM-01",
        level=1,
        domain="RM",
        name="Result model",
        description="Result model",
        metadata={"handler_invocations": invocations},
    )


def _ctx(tmp_path):
    from darnit.sieve.models import CheckContext

    return CheckContext(
        owner="o",
        repo="r",
        local_path=str(tmp_path),
        default_branch="main",
        control_id="RM-01",
    )


class TestStatuses:
    def test_status_vocabulary(self) -> None:
        assert set(typing.get_args(CheckStatus)) == {"PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING"}

    def test_pending_llm_is_not_a_status(self) -> None:
        with pytest.raises(ValueError):
            SieveResult(control_id="X", status="PENDING_LLM", message="m", level=1)  # type: ignore[arg-type]


class TestErrorCarriesCause:
    def test_error_without_block_gets_class_and_cause(self) -> None:
        result = SieveResult(control_id="X", status="ERROR", message="gh exploded", level=1, error_class="auth")
        assert result.error == {"class": "auth", "cause": "gh exploded"}
        assert result.to_legacy_dict()["error"] == {"class": "auth", "cause": "gh exploded"}

    def test_error_without_error_class_is_evaluation(self) -> None:
        result = SieveResult(control_id="X", status="ERROR", message="boom", level=1)
        assert result.error == {"class": "evaluation", "cause": "boom"}

    def test_explicit_error_block_kept(self) -> None:
        result = SieveResult(
            control_id="X",
            status="ERROR",
            message="m",
            level=1,
            error={"class": "missing_tool", "cause": "gh not installed"},
        )
        assert result.error == {"class": "missing_tool", "cause": "gh not installed"}

    def test_error_block_requires_class_and_cause(self) -> None:
        with pytest.raises(ValueError):
            SieveResult(control_id="X", status="ERROR", message="m", level=1, error={"class": "auth"})

    def test_orchestrator_error_carries_cause(self, tmp_path) -> None:
        registry = get_sieve_handler_registry()

        def broken(config, context):
            raise RuntimeError("kaput")

        registry.register("rm_broken", "deterministic", broken, ceiling={"pass", "fail"})
        result = SieveOrchestrator().verify(_spec([HandlerInvocation(handler="rm_broken")]), _ctx(tmp_path))
        assert result.status == "ERROR"
        assert result.error["class"] == "crashed"
        assert "kaput" in result.error["cause"]
        assert result.concluded_by == "rm_broken"


class TestPendingCarriesKind:
    def test_pending_requires_kind(self) -> None:
        with pytest.raises(ValueError):
            SieveResult(control_id="X", status="PENDING", message="m", level=1)

    def test_pending_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValueError):
            SieveResult(control_id="X", status="PENDING", message="m", level=1, pending={"kind": "vibes"})

    def test_confirmation_kind_requires_candidate(self) -> None:
        with pytest.raises(ValueError):
            SieveResult(control_id="X", status="PENDING", message="m", level=1, pending={"kind": "confirmation"})

    def test_pending_serializes_kind(self) -> None:
        result = SieveResult(control_id="X", status="PENDING", message="m", level=1, pending={"kind": "llm_judgment"})
        assert result.to_legacy_dict()["pending"] == {"kind": "llm_judgment"}

    def test_llm_step_produces_pending_not_pending_llm(self, tmp_path) -> None:
        (tmp_path / "README.md").write_text("hello\n")
        spec = _spec([HandlerInvocation(handler="llm_eval", prompt="Is it good?", files_to_include=["README.md"])])
        result = SieveOrchestrator(stop_on_llm=True).verify(spec, _ctx(tmp_path))
        assert result.status == "PENDING"
        assert result.pending == {"kind": "llm_judgment"}
        assert "llm_consultation" in result.evidence
        legacy = result.to_legacy_dict()
        assert legacy["status"] == "PENDING"
        assert legacy["pending"] == {"kind": "llm_judgment"}


class TestConcludedBy:
    def test_conclusion_records_step_handler(self, tmp_path) -> None:
        registry = get_sieve_handler_registry()

        def fails(config, context):
            return HandlerResult(status=HandlerResultStatus.FAIL, message="no")

        registry.register("rm_fails", "deterministic", fails, ceiling={"pass", "fail"})
        result = SieveOrchestrator().verify(_spec([HandlerInvocation(handler="rm_fails")]), _ctx(tmp_path))
        assert result.status == "FAIL"
        assert result.concluded_by == "rm_fails"
        assert result.authority == "dispositive"
        assert result.to_legacy_dict()["concluded_by"] == "rm_fails"

    def test_nothing_concluded_is_none(self, tmp_path) -> None:
        spec = _spec([HandlerInvocation(handler="manual", steps=["look"])])
        result = SieveOrchestrator().verify(spec, _ctx(tmp_path))
        assert result.status == "WARN"
        assert result.concluded_by == "none"
        assert result.authority == "suggestive"
