"""Tests for the resolution_trail contract (feature 027 T013).

Covers SC-009 (three-outcome trail), contract RT-1..RT-14 from
contracts/resolution-trail-schema.md, and redaction/truncation semantics.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from darnit.harness.driver import HarnessRun
from darnit.harness.question_resolvers import (
    Answer,
    ResolutionTrailEntry,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestRT1EveryPendingHasTrail:
    def test_pending_entry_has_resolution_trail_field(self) -> None:
        from darnit.harness.report import PendingFeedbackEntry

        entry = PendingFeedbackEntry(
            control_id="X", context_key="k", question="q?",
        )
        # Default: empty list, never absent
        assert entry.resolution_trail == []


class TestRT6ToRT9CrossFieldInvariants:
    def test_answered_last_when_present(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_skipping_resolver: object,
        mock_answering_resolver: object,
    ) -> None:
        """RT-9: if any entry has outcome='answered', it is the LAST entry."""
        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [mock_skipping_resolver, mock_answering_resolver]

        results = [
            {
                "id": "CTRL",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "CTRL",
                        "context_key": "k",
                        "question": "q?",
                        "answered": False,
                    },
                ],
            },
        ]
        _updated, _pending, answered, _ctx = _run(run._collect_unanswered(results))

        trail = answered[0].resolution_trail
        answered_indices = [
            i for i, e in enumerate(trail) if e.outcome == "answered"
        ]
        assert len(answered_indices) == 1
        assert answered_indices[0] == len(trail) - 1


class TestSC009ThreeOutcomeTrail:
    def test_errored_then_skipped_then_answered(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_erroring_resolver: Callable[..., object],
        mock_skipping_resolver: object,
        mock_answering_resolver: object,
    ) -> None:
        """SC-009: three resolvers (errored, skipped, answered) produce
        exactly that three-entry trail in that order."""
        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [
            mock_erroring_resolver(exception_message="fixture boom"),
            mock_skipping_resolver,
            mock_answering_resolver,
        ]

        results = [
            {
                "id": "CTRL",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "CTRL",
                        "context_key": "k",
                        "question": "q?",
                        "answered": False,
                    },
                ],
            },
        ]
        _updated, _pending, answered, _ctx = _run(run._collect_unanswered(results))

        trail = answered[0].resolution_trail
        assert len(trail) == 3
        outcomes = [e.outcome for e in trail]
        assert outcomes == ["errored", "skipped", "answered"]

        names = [e.resolver_name for e in trail]
        assert names == ["mock_erroring", "mock_skipping", "mock_answering"]


class TestRT10RedactionOfErrorSummary:
    def test_credential_material_scrubbed_from_error_summary(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_answering_resolver: object,
    ) -> None:
        """RT-10 + RT-11: sk-ant-* substrings in exception messages are
        redacted before landing in trail entries."""
        secret = "sk-ant-fake-KEY-1234567890"

        class _LeakingErrorResolver:
            name = "leaking"

            async def resolve(self, question: object) -> Answer | None:
                raise RuntimeError(f"http 401 with token {secret}")

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [_LeakingErrorResolver(), mock_answering_resolver]

        results = [
            {
                "id": "CTRL",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "CTRL",
                        "context_key": "k",
                        "question": "q?",
                        "answered": False,
                    },
                ],
            },
        ]
        _updated, _pending, answered, _ctx = _run(run._collect_unanswered(results))

        trail = answered[0].resolution_trail
        assert len(trail) == 2
        errored = trail[0]
        assert errored.outcome == "errored"
        assert errored.error_summary is not None
        assert secret not in errored.error_summary
        assert "REDACTED" in errored.error_summary
        assert len(errored.error_summary) <= 200


class TestRT2EmptyTrailWhenAnswerSourceCoversQuestion:
    """RT-1 clarification: a question resolved by AnswerSource NEVER reaches
    the resolver chain, so its resolution_trail (on AnsweredFeedbackEntry)
    is empty. Answered by an ANSWER SOURCE, not a resolver."""

    def test_answer_source_answered_question_has_empty_trail(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
        mock_answering_resolver: object,
    ) -> None:
        from darnit.harness.answer_sources import AnswerResolver
        from tests.darnit.harness.test_answer_sources import MockAnswerSource

        resolver = AnswerResolver()
        resolver.add(MockAnswerSource("mock_source", {"k": "from-source"}))

        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.answer_resolver = resolver
        # Resolvers configured but should NOT be invoked -- source answers first.
        run.question_resolvers = [mock_answering_resolver]

        results = [
            {
                "id": "CTRL",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "CTRL",
                        "context_key": "k",
                        "question": "q?",
                        "answered": False,
                    },
                ],
            },
        ]
        _updated, _pending, answered, ctx = _run(run._collect_unanswered(results))

        assert ctx["k"] == "from-source"
        assert len(answered) == 1
        assert answered[0].origin == "mock_source"
        assert answered[0].resolution_trail == []


class TestReconstructibilityViaJSON:
    """M3 / SC-006: an external consumer reading the report JSON can
    reconstruct the resolver chain from `resolution_trail` alone."""

    def test_external_json_consumer_can_reconstruct_chain(self) -> None:
        from darnit.harness.report import AnsweredFeedbackEntry, HarnessReport, HarnessSummary

        entry = AnsweredFeedbackEntry(
            control_id="CTRL-01",
            context_key="k",
            question="q?",
            answer="v",
            origin="slack_dm",
            resolution_trail=[
                ResolutionTrailEntry(
                    resolver_name="gh_issue_comment",
                    outcome="errored",
                    error_summary="HTTP 404",
                ),
                ResolutionTrailEntry(
                    resolver_name="interactive_terminal", outcome="skipped",
                ),
                ResolutionTrailEntry(
                    resolver_name="slack_dm", outcome="answered",
                ),
            ],
        )
        report = HarnessReport(
            target={"local_path": "/tmp"},
            summary=HarnessSummary(
                total=0, **{"pass": 0}, fail=0, warn=0, n_a=0, error=0,
            ),
            controls=[],
            pending_feedback=[],
            answer_sources_used=[],
            llm_calls={"total": 0, "provider": "mock"},
            resolvers_used=["gh_issue_comment", "interactive_terminal", "slack_dm"],
            answered_feedback=[entry],
        )

        # Serialize and parse WITHOUT using the Pydantic model (external
        # consumer simulation).
        payload = json.loads(report.to_json())
        af = payload["answered_feedback"][0]

        reconstructed = [
            (e["resolver_name"], e["outcome"])
            for e in af["resolution_trail"]
        ]
        assert reconstructed == [
            ("gh_issue_comment", "errored"),
            ("interactive_terminal", "skipped"),
            ("slack_dm", "answered"),
        ]
        # Every trail entry has the origin recoverable from `resolver_name`.
        assert af["origin"] == "slack_dm"
        assert af["authority"] == "asserted"
