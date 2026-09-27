"""The harness uses the shared compliance rule and never turns a judgment into PASS (feature 041, US3, T028, T033)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from darnit.core.llm_step import ConsultationRequest, LLMJudgment, MockLLMStep
from darnit.harness.driver import HarnessRun
from darnit.harness.exit_codes import HarnessExitCode
from darnit.trust.confirmations import load_candidates
from tests.darnit.trust.judgment_repo import (
    CI_VARS,
    CONTROL,
    EXCERPT,
    FRAMEWORK,
    IDENTITY,
    TARGET,
    make_repo,
    write_operator_config,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _harness(repo: Path, judgment: LLMJudgment | None = None, llm_step=None, target: str | None = TARGET):
    return HarnessRun(
        local_path=str(repo),
        framework_name=FRAMEWORK,
        level=1,
        llm_step=llm_step or MockLLMStep(judgment),
        per_call_timeout_s=10,
        total_run_timeout_s=60,
        target=target,
    )


def _control(report) -> dict:
    return next(c for c in report.controls if c["id"] == CONTROL)


@pytest.fixture(autouse=True)
def _outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in CI_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = make_repo(tmp_path)
    write_operator_config(tmp_path)
    return path


@pytest.mark.integration
class TestHarnessJudgments:
    def test_positive_judgment_is_a_stored_candidate_and_non_compliant(self, repo: Path) -> None:
        judgment = LLMJudgment(outcome="yes", confidence=0.99, reasoning="purpose stated", cited_evidence=[EXCERPT])

        report = _run(_harness(repo, judgment).run())

        control = _control(report)
        assert control["status"] == "PENDING"
        assert control["pending"] == {"kind": "confirmation"}
        assert control["candidate"]["source"] == "harness"
        assert control["candidate"]["model"] == "anthropic:claude-sonnet-5"
        assert "llm_consultation" in control["evidence"]
        assert report.compliance == {1: False}
        assert report.exit_class == HarnessExitCode.AUDIT_FAILURES
        assert [c.control_id for c in load_candidates(IDENTITY)] == [CONTROL]
        assert json.loads(report.to_json())["compliance"] == {"1": False}
        assert "- Level 1: not compliant" in report.to_markdown()

    def test_candidate_is_not_stored_without_a_named_repository(self, repo: Path) -> None:
        judgment = LLMJudgment(outcome="yes", confidence=0.99, reasoning="purpose stated", cited_evidence=[EXCERPT])

        report = _run(_harness(repo, judgment, target=None).run())

        assert _control(report)["pending"] == {"kind": "confirmation"}
        assert load_candidates() == []

    def test_unverifiable_citation_stores_nothing(self, repo: Path) -> None:
        judgment = LLMJudgment(
            outcome="yes", confidence=0.99, reasoning="policy present", cited_evidence=["Email security@example.com"]
        )

        report = _run(_harness(repo, judgment).run())

        assert _control(report)["status"] == "WARN"
        assert load_candidates() == []

    def test_negative_judgment_is_a_suggestive_fail(self, repo: Path) -> None:
        judgment = LLMJudgment(outcome="no", confidence=0.9, reasoning="no purpose stated")

        control = _control(_run(_harness(repo, judgment).run()))

        assert control["status"] == "FAIL"
        assert control["authority"] == "suggestive"
        assert control["concluded_by"] == "llm_judgment"

    def test_model_service_failure_is_error(self, repo: Path) -> None:
        class FailingStep:
            async def evaluate(self, request: ConsultationRequest) -> LLMJudgment:
                raise ConnectionError("service unavailable")

        report = _run(_harness(repo, llm_step=FailingStep()).run())

        control = _control(report)
        assert control["status"] == "ERROR"
        assert control["error"]["class"] == "unavailable"
        assert report.exit_class == HarnessExitCode.AUDIT_FAILURES


@pytest.mark.unit
class TestReportCompliance:
    def _report(self, results: list[dict]):
        run = HarnessRun(local_path=".", llm_step=MockLLMStep(LLMJudgment(outcome="yes", confidence=1, reasoning="")))
        return run._assemble_report(results, "o", "r", [])

    def test_uses_calculate_compliance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import darnit.tools.audit as audit_module

        calls = []

        def spy(results, level=3):
            calls.append(level)
            return dict.fromkeys(range(1, level + 1), False)

        monkeypatch.setattr(audit_module, "calculate_compliance", spy)
        report = self._report([{"id": "A", "status": "PASS", "level": 1, "details": ""}])

        assert calls == [1]
        assert report.exit_class == HarnessExitCode.AUDIT_FAILURES

    def test_pass_candidate_is_non_compliant(self) -> None:
        report = self._report(
            [
                {"id": "A", "status": "PASS", "level": 1, "details": ""},
                {
                    "id": "B",
                    "status": "PENDING",
                    "level": 1,
                    "details": "",
                    "pending": {"kind": "confirmation"},
                    "candidate": {"verdict": "pass"},
                },
            ]
        )

        assert report.compliance == {1: False}
        assert report.exit_class == HarnessExitCode.AUDIT_FAILURES

    def test_all_pass_or_not_applicable_succeeds(self) -> None:
        report = self._report(
            [
                {"id": "A", "status": "PASS", "level": 1, "details": ""},
                {"id": "B", "status": "N/A", "level": 2, "details": ""},
            ]
        )

        assert report.exit_class == HarnessExitCode.SUCCESS
