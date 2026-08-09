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

        # Feature 027: _collect_unanswered is now async and returns a 4-tuple
        # (results, pending_feedback, answered_feedback, context_values).
        updated, pending, answered, ctx_values = _run(
            run._collect_unanswered(fake_results),
        )

        # (a) status unchanged (feature 026 invariant preserved)
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
        # (d) feature 027: answer captured in answered_feedback with origin
        answered_for_security_contact = [
            a for a in answered if a.context_key == "security_contact"
        ]
        assert len(answered_for_security_contact) == 1
        entry = answered_for_security_contact[0]
        assert entry.control_id == "STAGE1-REF-SECURITY-01"
        assert entry.answer == "sec@example.com"
        assert entry.origin == "mock"
        assert entry.authority == "asserted"


# ---------------------------------------------------------------------------
# Feature 027: QuestionResolver chain tests (T014)
# ---------------------------------------------------------------------------


class TestQuestionResolverChain:
    """Cover SC-003, SC-007, SC-008, FR-006a, FR-011, FR-013 at the driver layer."""

    def _make_fake_results(self, context_keys: list[str]) -> list[dict]:
        """Build fake result dicts each with one pending feedback question."""
        return [
            {
                "id": f"CTRL-{i:02d}",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": f"CTRL-{i:02d}",
                        "context_key": key,
                        "question": f"Question for {key}?",
                        "answered": False,
                    },
                ],
            }
            for i, key in enumerate(context_keys)
        ]

    def test_answering_resolver_resolves_question_with_asserted_authority(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_answering_resolver: object,
    ) -> None:
        """SC-003 end-to-end: answered question carries authority='asserted' in the report."""
        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [mock_answering_resolver]

        results = self._make_fake_results(["security_contact"])
        _updated, pending, answered, ctx = _run(run._collect_unanswered(results))

        assert pending == []
        assert len(answered) == 1
        assert answered[0].authority == "asserted"
        assert answered[0].origin == "mock_answering"
        assert ctx["security_contact"] == "mock-answer"
        assert len(answered[0].resolution_trail) == 1
        assert answered[0].resolution_trail[0].outcome == "answered"

    def test_skipping_then_answering_produces_two_trail_entries(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_skipping_resolver: object,
        mock_answering_resolver: object,
    ) -> None:
        """Trail ordering: skipping resolver appears BEFORE the answering one."""
        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [mock_skipping_resolver, mock_answering_resolver]

        results = self._make_fake_results(["security_contact"])
        _updated, pending, answered, _ctx = _run(run._collect_unanswered(results))

        assert pending == []
        assert len(answered) == 1
        trail = answered[0].resolution_trail
        assert len(trail) == 2
        assert trail[0].resolver_name == "mock_skipping"
        assert trail[0].outcome == "skipped"
        assert trail[1].resolver_name == "mock_answering"
        assert trail[1].outcome == "answered"

    def test_erroring_resolver_isolated_from_answering(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_erroring_resolver: Callable[..., object],
        mock_answering_resolver: object,
    ) -> None:
        """SC-007: errored resolver does not stop chain; second resolver answers."""
        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [
            mock_erroring_resolver(exception_message="mock error x"),
            mock_answering_resolver,
        ]

        results = self._make_fake_results(["security_contact"])
        _updated, pending, answered, _ctx = _run(run._collect_unanswered(results))

        assert pending == []
        assert len(answered) == 1
        trail = answered[0].resolution_trail
        assert len(trail) == 2
        assert trail[0].outcome == "errored"
        assert trail[0].error_summary is not None
        assert "mock error x" in trail[0].error_summary
        assert trail[1].outcome == "answered"

    def test_resolvers_configured_but_no_pending_questions(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_answering_resolver: object,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When there are 0 pending questions, no bookend lines are emitted."""
        import logging

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [mock_answering_resolver]

        caplog.set_level(logging.INFO, logger="darnit.harness")
        results: list[dict] = []  # no results = no questions
        _updated, pending, answered, _ctx = _run(run._collect_unanswered(results))

        assert pending == []
        assert answered == []
        collection_lines = [
            r.getMessage() for r in caplog.records
            if "interactive collection" in r.getMessage()
        ]
        assert collection_lines == []

    def test_bookend_lines_appear_exactly_once_each(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_answering_resolver: object,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """SC-008: exactly two bookend lines per interactive collection phase."""
        import logging
        import re

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [mock_answering_resolver]

        caplog.set_level(logging.INFO, logger="darnit.harness")
        results = self._make_fake_results(["k1", "k2", "k3"])
        _run(run._collect_unanswered(results))

        starting = [
            r.getMessage() for r in caplog.records
            if "starting interactive collection" in r.getMessage()
        ]
        finished = [
            r.getMessage() for r in caplog.records
            if "finished interactive collection" in r.getMessage()
        ]
        assert len(starting) == 1, f"expected 1 starting bookend, got {starting}"
        assert len(finished) == 1, f"expected 1 finished bookend, got {finished}"
        assert "3 pending" in starting[0]

        # No per-control [N/M] progress lines from feature 026 during collect
        progress_pattern = re.compile(r"\[\d+/\d+\]")
        between = [
            r.getMessage() for r in caplog.records
            if progress_pattern.search(r.getMessage())
        ]
        assert between == []

    def test_programmatic_empty_answer_collapsed_to_skip(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
    ) -> None:
        """FR-006a / M1: Answer('') and Answer('   ') collapse to skip at the driver."""
        from darnit.harness.question_resolvers import Answer

        class _EmptyReturningResolver:
            name = "empty_returning"

            async def resolve(self, question: object) -> Answer | None:
                return Answer(value="   ", origin="empty_returning")

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [_EmptyReturningResolver()]

        results = self._make_fake_results(["k1"])
        _updated, pending, answered, _ctx = _run(run._collect_unanswered(results))

        assert answered == []
        assert len(pending) == 1
        assert len(pending[0].resolution_trail) == 1
        assert pending[0].resolution_trail[0].outcome == "skipped"

    def test_answer_values_never_appear_in_log_records(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """FR-013 / M2: resolver-supplied values must not leak to any log line."""
        import logging

        from darnit.harness.question_resolvers import Answer

        distinct_value = "DISTINCTIVE-VALUE-XYZ-123-NEVER-IN-LOGS"

        class _DistinctiveResolver:
            name = "distinctive"

            async def resolve(self, question: object) -> Answer | None:
                return Answer(value=distinct_value, origin="distinctive")

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [_DistinctiveResolver()]

        caplog.set_level(logging.DEBUG, logger="darnit.harness")
        results = self._make_fake_results(["k1"])
        _run(run._collect_unanswered(results))

        for record in caplog.records:
            assert distinct_value not in record.getMessage(), (
                f"leaked value into log: {record.getMessage()!r}"
            )

    def test_per_resolver_timeout_records_errored_entry(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_answering_resolver: object,
    ) -> None:
        """FR-011: a slow resolver hits the timeout, gets 'errored' outcome,
        and the driver moves on to the next resolver."""
        import asyncio as _asyncio

        from darnit.harness.question_resolvers import Answer

        class _SlowResolver:
            name = "slow"

            async def resolve(self, question: object) -> Answer | None:
                await _asyncio.sleep(0.5)
                return Answer(value="never-returned", origin="slow")

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [_SlowResolver(), mock_answering_resolver]
        run.per_resolver_timeout_s = 0.05

        results = self._make_fake_results(["k1"])
        _updated, pending, answered, _ctx = _run(run._collect_unanswered(results))

        assert pending == []
        assert len(answered) == 1
        trail = answered[0].resolution_trail
        assert len(trail) == 2
        assert trail[0].resolver_name == "slow"
        assert trail[0].outcome == "errored"
        assert trail[0].error_summary is not None
        assert "timed out" in trail[0].error_summary
        assert trail[1].outcome == "answered"


# ---------------------------------------------------------------------------
# US3: composition of --answers file with resolver chain (T023)
# ---------------------------------------------------------------------------


class TestComposition:
    def test_answer_source_wins_before_resolver_chain(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_answering_resolver: object,
    ) -> None:
        """QR-19: AnswerSource pass runs BEFORE QuestionResolver chain.
        A question answered by an AnswerSource never reaches the resolvers."""
        from darnit.harness.answer_sources import AnswerResolver
        from tests.darnit.harness.test_answer_sources import MockAnswerSource

        answer_resolver = AnswerResolver()
        answer_resolver.add(
            MockAnswerSource(
                "project_yaml", {"security_contact": "from_project@example.com"},
            ),
        )
        answer_resolver.add(
            MockAnswerSource(
                "answers_file", {"code_of_conduct_url": "from_answers.md"},
            ),
        )

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.answer_resolver = answer_resolver
        run.question_resolvers = [mock_answering_resolver]

        # Three questions: two covered by AnswerSource, one uncovered.
        results = [
            {
                "id": "CTRL-01",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "CTRL-01",
                        "context_key": "security_contact",
                        "question": "sec?",
                        "answered": False,
                    },
                ],
            },
            {
                "id": "CTRL-02",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "CTRL-02",
                        "context_key": "code_of_conduct_url",
                        "question": "coc?",
                        "answered": False,
                    },
                ],
            },
            {
                "id": "CTRL-03",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "CTRL-03",
                        "context_key": "release_process",
                        "question": "release?",
                        "answered": False,
                    },
                ],
            },
        ]
        _updated, pending, answered, ctx = _run(run._collect_unanswered(results))

        # All three answered
        assert pending == []
        assert len(answered) == 3
        # Distinct origins per question
        by_key = {e.context_key: e for e in answered}
        assert by_key["security_contact"].origin == "project_yaml"
        assert by_key["code_of_conduct_url"].origin == "answers_file"
        assert by_key["release_process"].origin == "mock_answering"

        # Resolver chain was ONLY offered the uncovered question -- verified
        # by the trail (empty for AnswerSource-answered, populated for the
        # resolver-answered one).
        assert by_key["security_contact"].resolution_trail == []
        assert by_key["code_of_conduct_url"].resolution_trail == []
        assert len(by_key["release_process"].resolution_trail) == 1
        assert by_key["release_process"].resolution_trail[0].outcome == "answered"


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
