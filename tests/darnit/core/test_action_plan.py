"""Tests for the ActionPlan protocol (feature 025 Slice B).

Covers spec.md US2 acceptance scenarios, FR-006 through FR-010, and
contract items A1-A10 from
``specs/025-rfc0001-stage1/contracts/action-plan-protocol.md``.
"""

from __future__ import annotations

import copy

import pytest

from darnit.core.action_plan import (
    ActionPlan,
    FeedbackQuestionModel,
    HarnessState,
    next_action,
    submit_result,
)
from darnit.core.errors import OutOfOrderSubmission, ResultSchemaMismatch


class TestNextAction:
    """A1, A9, A10: pure function; no mutation, no side effects."""

    def test_terminal_when_error_is_set(self) -> None:
        state = HarnessState(local_path="/tmp", error="something broke")
        assert next_action(state) is None

    def test_first_call_returns_audit_step(self) -> None:
        state = HarnessState(local_path="/tmp")
        plan = next_action(state)
        assert plan is not None
        assert plan.step.integration == "audit"
        assert plan.step.authority == "dispositive"
        assert plan.expected_result_kind == "pipeline_phase"

    def test_returns_collect_context_when_warn_and_unanswered(self) -> None:
        state = HarnessState(
            local_path="/tmp",
            audit_results=[{"id": "A", "status": "WARN", "details": "", "level": 1}],
            feedback_questions=[
                FeedbackQuestionModel(
                    control_id="A",
                    context_key="k",
                    question="?",
                    answered=False,
                ),
            ],
        )
        plan = next_action(state)
        assert plan is not None
        assert plan.step.integration == "collect_context"
        assert plan.expected_result_kind == "user_input"

    def test_returns_remediate_when_only_fail(self) -> None:
        state = HarnessState(
            local_path="/tmp",
            audit_results=[{"id": "A", "status": "FAIL", "details": "", "level": 1}],
        )
        plan = next_action(state)
        assert plan is not None
        assert plan.step.integration == "remediate"

    def test_returns_terminal_when_all_pass(self) -> None:
        state = HarnessState(
            local_path="/tmp",
            audit_results=[{"id": "A", "status": "PASS", "details": "", "level": 1}],
        )
        assert next_action(state) is None

    def test_next_action_pure_no_mutation(self) -> None:
        """Contract A1: next_action does not mutate state."""
        state = HarnessState(
            local_path="/tmp",
            audit_results=[{"id": "A", "status": "WARN", "details": "", "level": 1}],
            feedback_questions=[
                FeedbackQuestionModel(
                    control_id="A",
                    context_key="k",
                    question="?",
                    answered=False,
                ),
            ],
        )
        snapshot = copy.deepcopy(state)
        _ = next_action(state)
        assert state == snapshot

    def test_terminates_when_position_hits_ceiling(self) -> None:
        state = HarnessState(local_path="/tmp", current_position=10)
        assert next_action(state) is None


class TestSubmitResult:
    """A2, A3, A4, A5, A7: pure state transition; typed errors on violations."""

    def test_out_of_order_raises(self) -> None:
        """Contract A3, FR-008."""
        state = HarnessState(local_path="/tmp")  # first step will be audit-0
        snapshot = copy.deepcopy(state)
        with pytest.raises(OutOfOrderSubmission) as excinfo:
            submit_result(state, "wrong-id", {"audit_results": []})
        assert excinfo.value.expected_step_id == "audit-0"
        assert excinfo.value.submitted_step_id == "wrong-id"
        # State MUST NOT be modified on error.
        assert state == snapshot

    def test_out_of_order_when_terminal_raises(self) -> None:
        state = HarnessState(local_path="/tmp", error="terminal")
        with pytest.raises(OutOfOrderSubmission):
            submit_result(state, "audit-0", {})

    def test_audit_result_advances_position_and_populates(self) -> None:
        state = HarnessState(local_path="/tmp")
        new_state = submit_result(
            state,
            "audit-0",
            {
                "audit_results": [
                    {"id": "A", "status": "PASS", "details": "", "level": 1},
                ],
                "owner": "test-owner",
                "repo": "test-repo",
            },
        )
        assert new_state.current_position == 1
        assert len(new_state.audit_results) == 1
        assert new_state.owner == "test-owner"
        # State snapshot unchanged.
        assert state.current_position == 0
        assert new_state is not state

    def test_collect_context_merges_answers_and_clears_audit_results(self) -> None:
        state = HarnessState(
            local_path="/tmp",
            audit_results=[{"id": "A", "status": "WARN", "details": "", "level": 1}],
            feedback_questions=[
                FeedbackQuestionModel(
                    control_id="A",
                    context_key="k",
                    question="?",
                    answered=False,
                ),
            ],
        )
        new_state = submit_result(
            state,
            "collect_context-0",
            {"answers": {"k": "yes"}},
        )
        assert new_state.context_values == {"k": "yes"}
        assert new_state.feedback_questions[0].answered is True
        assert new_state.feedback_questions[0].answer == "yes"
        # Audit results cleared to signal re-audit.
        assert new_state.audit_results == []

    def test_schema_mismatch_raises(self) -> None:
        """Contract A4, FR-009: declared result_schema is enforced.

        Stage 1 pipeline steps do not declare result_schema by default, so
        we test the validator helper directly. Stage 2 per-handler steps
        will exercise the full submit_result path with a declared schema.
        """
        from darnit.core.action_plan import _validate_result_against_schema

        schema = {"required": ["outcome", "reasoning"]}
        with pytest.raises(ResultSchemaMismatch) as excinfo:
            _validate_result_against_schema("some-step", {"outcome": "yes"}, schema)
        assert "reasoning" in excinfo.value.offending_fields

    def test_evidence_item_recorded_on_each_submission(self) -> None:
        """Contract A5: every successful submission appends an EvidenceItem."""
        state = HarnessState(local_path="/tmp")
        new_state = submit_result(
            state,
            "audit-0",
            {"audit_results": [], "outcome": "no_controls", "reasoning": "empty"},
        )
        assert "__pipeline__" in new_state.evidence
        items = new_state.evidence["__pipeline__"]
        assert len(items) == 1
        assert items[0].step_id == "audit-0"
        assert items[0].authority == "dispositive"
        assert items[0].outcome == "no_controls"


class TestJsonRoundTrip:
    """Contract A7: HarnessState round-trips through JSON losslessly."""

    def test_empty_state_round_trips(self) -> None:
        state = HarnessState(local_path="/tmp")
        restored = HarnessState.model_validate_json(state.model_dump_json())
        assert restored == state

    def test_populated_state_round_trips(self) -> None:
        state = HarnessState(
            local_path="/tmp",
            owner="acme",
            repo="thing",
            audit_results=[
                {"id": "A", "status": "PASS", "details": "ok", "level": 1},
                {"id": "B", "status": "FAIL", "details": "bad", "level": 2},
            ],
            feedback_questions=[
                FeedbackQuestionModel(
                    control_id="A",
                    context_key="k",
                    question="?",
                    answered=True,
                    answer="yes",
                ),
            ],
            context_values={"k": "yes"},
            current_position=3,
        )
        restored = HarnessState.model_validate_json(state.model_dump_json())
        assert restored == state


class TestActionPlanShape:
    """Contract A8: ActionPlan round-trips through JSON."""

    def test_action_plan_json_round_trip(self) -> None:
        state = HarnessState(local_path="/tmp")
        plan = next_action(state)
        assert plan is not None
        restored = ActionPlan.model_validate_json(plan.model_dump_json())
        assert restored == plan


class TestAuditStateCompat:
    """Round-trip AuditState <-> HarnessState preserves observable state."""

    def test_from_audit_state_preserves_fields(self) -> None:
        from darnit.agent.state import AuditState, FeedbackQuestion

        audit_state = AuditState(
            local_path="/tmp",
            owner="acme",
            repo="thing",
            audit_results=[
                {"id": "A", "status": "PASS", "details": "ok", "level": 1},
            ],
            feedback_questions=[
                FeedbackQuestion(
                    control_id="A",
                    context_key="k",
                    question="?",
                    answered=True,
                    answer="yes",
                ),
            ],
        )
        h = HarnessState.from_audit_state(audit_state)
        assert h.owner == "acme"
        assert h.repo == "thing"
        assert h.audit_results[0]["id"] == "A"
        assert h.feedback_questions[0].control_id == "A"
        assert h.feedback_questions[0].answered is True

    def test_to_audit_state_preserves_fields(self) -> None:
        h = HarnessState(
            local_path="/tmp",
            owner="acme",
            audit_results=[{"id": "A", "status": "PASS", "details": "", "level": 1}],
        )
        a = h.to_audit_state()
        assert a.local_path == "/tmp"
        assert a.owner == "acme"
        assert len(a.audit_results) == 1
