"""End-to-end tests for HarnessRun (feature 026 T021-T023 + T026-T029b).

Covers SC-001, SC-002 (partial: check via CLI test T038), SC-004, SC-006,
SC-008, plus US1 acceptance scenarios.

Uses MockLLMStep injected via the harness_run_factory fixture so no live
API calls are made.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from darnit.core.llm_step import ConsultationRequest, LLMJudgment, LLMStep, MockLLMStep
from darnit.harness.answer_sources import AnswerResolver
from darnit.harness.driver import HarnessRun, HarnessSetupError, _redact_secrets


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# SC-001 / US1 acceptance #1: end-to-end LLM dispatched, no PENDING_LLM
# ---------------------------------------------------------------------------


class TestEndToEndDispatch:
    def test_end_to_end_llm_dispatched(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
    ) -> None:
        """SC-001 + SC-004: harness runs to completion; no result ends up
        PENDING_LLM in the final report.

        Prior to PR #365 fix this test also asserted >=1 LLM dispatch via
        STAGE1-REF-SECURITY-01's llm_extract step. That ordering
        (llm_extract first) made the control unable to ever PASS -- see
        openssf-baseline.toml comment on STAGE1-REF-SECURITY-01. The
        reorder puts dispositive file_exists first; llm_extract is now
        unreachable on this fixture, so we no longer assert LLM dispatch
        via this control. Whether LLM dispatch continues past a
        suggestive result is tracked as a follow-up.
        """
        run = harness_run_factory(str(minimal_llm_repo_tree))
        report = _run(run.run())

        # Every control resolved -- none left PENDING_LLM.
        pending_llm = [c for c in report.controls if c.get("status") == "PENDING_LLM"]
        assert not pending_llm, f"Found unresolved PENDING_LLM results: {[c['id'] for c in pending_llm]}"

        # Provider is always set to the mock/configured model even when
        # zero calls were made.
        assert report.llm_calls["provider"] == "anthropic:claude-sonnet-5"

    def test_llm_suggestive_cannot_conclude_pass(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
    ) -> None:
        """SC-008: even a MockLLMStep returning yes/high-confidence cannot
        cause the LLM-related control to conclude PASS. The dispositive
        file_exists step (missing SECURITY.md) FAILs the reference control."""
        run = harness_run_factory(str(minimal_llm_repo_tree))
        report = _run(run.run())

        ref_control = next(
            (c for c in report.controls if c.get("id") == "STAGE1-REF-SECURITY-01"),
            None,
        )
        assert ref_control is not None, "STAGE1-REF-SECURITY-01 not in results"
        assert ref_control["status"] != "PASS", f"LLM-suggested PASS leaked through: got {ref_control['status']}"

    def test_report_every_result_has_authority(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
    ) -> None:
        """SC-006 + contract RF-1: every result in the report has authority."""
        run = harness_run_factory(str(minimal_llm_repo_tree))
        report = _run(run.run())

        allowed = {"dispositive", "suggestive", "asserted"}
        for control in report.controls:
            # Some legacy results may not carry authority (feature 025
            # NotRequired). Any control that has authority MUST use the
            # Literal domain; missing authority is not a hard failure per
            # the NotRequired policy.
            if "authority" in control:
                assert control["authority"] in allowed, f"{control['id']}: unknown authority {control['authority']!r}"


# ---------------------------------------------------------------------------
# Progress-line format (T023)
# ---------------------------------------------------------------------------


class TestProgressLines:
    def test_progress_lines_use_n_over_m_counter(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Contract CLI-12 + FR-009a: progress lines use [N/M] format via
        stdlib logging on ``darnit.harness`` logger."""
        caplog.set_level(logging.INFO, logger="darnit.harness")
        run = harness_run_factory(str(minimal_llm_repo_tree))
        _run(run.run())

        # Assert at least one message matches the [N/M] pattern.
        progress_pattern = re.compile(r"\[\d+/\d+\]")
        matches = [r for r in caplog.records if r.name == "darnit.harness" and progress_pattern.search(r.getMessage())]
        assert len(matches) >= 1, (
            f"No progress lines with [N/M] found. All darnit.harness records: "
            f"{[r.getMessage() for r in caplog.records if r.name == 'darnit.harness']}"
        )


# ---------------------------------------------------------------------------
# US2: answer-source composition + precedence
# ---------------------------------------------------------------------------


class TestAnswerComposition:
    def test_build_default_resolver_composes_project_yaml_only(
        self,
        minimal_llm_repo_tree: Path,
    ) -> None:
        """T024: factory produces a resolver with ProjectYamlAnswerSource
        when no --answers path is provided."""
        resolver = HarnessRun.build_default_resolver(
            local_path=str(minimal_llm_repo_tree),
            answers_path=None,
        )
        assert resolver.sources_used() == ["project_yaml"]

    def test_build_default_resolver_adds_file_source_when_path_given(
        self,
        minimal_llm_repo_tree: Path,
        tmp_path: Path,
    ) -> None:
        answers = tmp_path / "answers.yaml"
        answers.write_text("security_contact: sec@example.com\n")
        resolver = HarnessRun.build_default_resolver(
            local_path=str(minimal_llm_repo_tree),
            answers_path=str(answers),
        )
        sources = resolver.sources_used()
        assert sources[0] == "project_yaml"
        assert sources[1].startswith("--answers ")

    def test_answers_file_overrides_project_yaml(
        self,
        minimal_llm_repo_tree: Path,
        tmp_path: Path,
    ) -> None:
        """AS-6 in the composed default resolver: --answers wins.

        Seed .project/project.yaml with one value; pass --answers with a
        different value; assert the --answers value is what resolve() returns.
        """
        # Seed project.yaml with a security contact.
        proj_yaml = minimal_llm_repo_tree / ".project" / "project.yaml"
        proj_yaml.write_text(
            "name: minimal-llm-repo\nsecurity:\n  contact: from_project@example.com\n",
        )

        answers = tmp_path / "answers.yaml"
        answers.write_text("security_contact: from_answers@example.com\n")

        resolver = HarnessRun.build_default_resolver(
            local_path=str(minimal_llm_repo_tree),
            answers_path=str(answers),
        )
        value, source = resolver.resolve("security_contact")
        assert value == "from_answers@example.com"
        assert source is not None and source.startswith("--answers ")


# ---------------------------------------------------------------------------
# US2 (T029b): no re-audit-after-Collect in MVP
# ---------------------------------------------------------------------------


class TestNoReauditAfterCollect:
    def test_answered_question_does_not_change_control_status_in_mvp(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
    ) -> None:
        """Data-model.md COLLECT_UNANSWERED policy: applying an answer to a
        pending question does NOT re-audit and does NOT change a control's
        pre-Collect status. Enforced so a future 'auto-reaudit' change is
        a deliberate contract update.

        We simulate by attaching a fake feedback_questions list to one
        result after the initial audit, then re-running _collect_unanswered.
        This is a driver-internal invariant test; the full pipeline
        doesn't emit feedback_questions through the sieve's CheckResult
        path in MVP, so we test the driver's collect function directly.
        """
        run = harness_run_factory(str(minimal_llm_repo_tree))
        resolver = AnswerResolver()
        from tests.darnit.harness.test_answer_sources import MockAnswerSource

        resolver.add(MockAnswerSource("mock", {"security_contact": "sec@example.com"}))
        run.answer_resolver = resolver

        fake_results = [
            {
                "id": "STAGE1-REF-SECURITY-01",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "STAGE1-REF-SECURITY-01",
                        "context_key": "security_contact",
                        "question": "Who is the security contact?",
                        "answered": False,
                    },
                ],
            },
        ]

        updated, pending, ctx_values = run._collect_unanswered(fake_results)

        # (a) status unchanged
        assert updated[0]["status"] == "FAIL"
        # (b) answer captured on the question + in context_values
        assert updated[0]["feedback_questions"][0]["answered"] is True
        assert updated[0]["feedback_questions"][0]["answer"] == "sec@example.com"
        assert ctx_values["security_contact"] == "sec@example.com"
        # (c) the attached question's context_key is no longer pending.
        # PR #365 review fix: `_collect_unanswered` also enumerates the
        # framework's own pending [context.*] keys, so `pending` is
        # generally NOT empty on a real fixture -- assert instead that the
        # question we answered isn't in it.
        assert "security_contact" not in {e.context_key for e in pending}


# ---------------------------------------------------------------------------
# Setup errors
# ---------------------------------------------------------------------------


class TestSetupErrors:
    def test_missing_api_key_raises_setup_error(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FR-002 + SC-002: no API key -> HarnessSetupError before audit runs."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        run = harness_run_factory(str(minimal_llm_repo_tree))
        with pytest.raises(HarnessSetupError) as excinfo:
            _run(run.run())
        assert "ANTHROPIC_API_KEY" in str(excinfo.value)

    def test_missing_repo_path_raises_setup_error(
        self,
        tmp_path: Path,
        mock_llm_step: MockLLMStep,
    ) -> None:
        """CLI-1: missing repo path surfaces as HarnessSetupError."""
        run = HarnessRun(
            local_path=str(tmp_path / "does-not-exist"),
            llm_step=mock_llm_step,
        )
        with pytest.raises(HarnessSetupError):
            _run(run.run())


class TestSecretRedaction:
    """RF-4 / CLI-14: credentials MUST NOT appear in logs or the report,
    including via third-party exception messages.
    """

    @pytest.mark.parametrize(
        ("raw", "must_not_contain"),
        [
            ("Bad key: sk-ant-api03-AbCd_EF-Gh1234567", "sk-ant-api03-AbCd_EF-Gh1234567"),
            ("Request failed. Authorization: Bearer sk-live-xyz", "sk-live-xyz"),
            ("HTTP 401 x-api-key: my-secret-token-42", "my-secret-token-42"),
            ("URL: https://api.example.com/v1?api_key=hunter2&x=1", "hunter2"),
        ],
    )
    def test_redact_secrets_scrubs_common_credential_shapes(
        self, raw: str, must_not_contain: str,
    ) -> None:
        redacted = _redact_secrets(raw)
        assert must_not_contain not in redacted, f"leaked substring in: {redacted!r}"
        assert "REDACTED" in redacted

    def test_leaked_exception_message_does_not_reach_report(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """M1 regression: a third-party LLM exception carrying an API key
        must not surface in the report's `reasoning` field or in log lines.
        """
        secret = "sk-ant-api03-LEAKED-TOKEN-9zZ"

        class LeakyLLMStep:
            """LLMStep that raises with a credential-bearing message."""

            async def evaluate(self, request: ConsultationRequest) -> LLMJudgment:
                raise RuntimeError(f"HTTP 401 while calling model with {secret}")

        assert isinstance(LeakyLLMStep(), LLMStep)

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.llm_step = LeakyLLMStep()

        import logging as _logging
        caplog.set_level(_logging.INFO, logger="darnit.harness")

        report = _run(run.run())
        report_json = report.to_json()

        assert secret not in report_json, "secret leaked into JSON report"
        assert secret not in report.to_markdown(), "secret leaked into markdown"
        for record in caplog.records:
            assert secret not in record.getMessage(), (
                f"secret leaked into log record: {record.getMessage()!r}"
            )
