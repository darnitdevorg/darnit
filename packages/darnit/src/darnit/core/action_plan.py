"""ActionPlan protocol: public typed contract for driving the darnit pipeline.

RFC-0001 Stage 1 (feature 025), Slice B. See:
- specs/025-rfc0001-stage1/contracts/action-plan-protocol.md
- specs/025-rfc0001-stage1/data-model.md sections 4-6

The two functions ``next_action`` and ``submit_result`` are pure state
transitions. They are what ``cmd_run`` (CLI) and the MCP tools (Slice C)
walk to drive Check/Collect/Remediate. Step execution itself (running an
audit, prompting a human, performing remediation) happens in the CALLER;
these functions only advance state.

Stage 1 uses a COARSE-grained step model matching today's pipeline phases
(audit / collect_context / remediate). Stage 2 will refine to per-handler
steps; the protocol shape does not change.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from darnit.core.authority import Authority
from darnit.core.context_validation import validate_context_answer
from darnit.core.errors import OutOfOrderSubmission, ResultSchemaMismatch

# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class StrategyStep(BaseModel):
    """One entry in a control's or pipeline's strategy list.

    Stage 1 uses this at pipeline granularity (integration in {"audit",
    "collect_context", "remediate"}). Stage 2 refines to per-handler
    granularity without changing the shape.
    """

    id: str
    integration: str
    params: dict[str, Any] = {}
    authority: Authority = "dispositive"
    result_schema: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class ActionPlan(BaseModel):
    """A single step surfaced to a caller (CLI, MCP agent, or driver).

    Emitted by ``next_action(state)``. The caller inspects ``expected_result_kind``,
    executes the step (or prompts a human), and passes the result back via
    ``submit_result(state, step.id, result)``.
    """

    step: StrategyStep
    control_id: str = ""
    position: int
    total_steps: int = -1  # -1 = unknown (pipeline-level steps)
    expected_result_kind: Literal["handler_result", "user_input", "confirmation", "pipeline_phase"]

    model_config = ConfigDict(extra="forbid")


class EvidenceItem(BaseModel):
    """One entry in HarnessState.evidence: a record of a step's contribution.

    Suggestive results attach here without concluding the control; the
    ordered log preserves audit-trail provenance for later inspection.
    """

    step_id: str
    authority: Authority
    outcome: str
    reasoning: str = ""
    raw: dict[str, Any] = {}

    model_config = ConfigDict(extra="forbid")


class FeedbackQuestionModel(BaseModel):
    """Pydantic version of ``darnit.agent.state.FeedbackQuestion``.

    Present as its own type so HarnessState can be JSON-serialized round-trip.
    The dataclass ``FeedbackQuestion`` is preserved unchanged; converters at
    the HarnessState boundary translate between the two.
    """

    control_id: str
    context_key: str
    question: str
    answer: str | None = None
    answered: bool = False

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# HarnessState -- serializable, client-owned run state
# ---------------------------------------------------------------------------


class HarnessState(BaseModel):
    """Serializable, client-owned state carried through the ActionPlan loop.

    Mirrors ``darnit.agent.state.AuditState`` field-for-field and adds
    ``current_position`` (iteration counter) and ``evidence`` (per-control
    ordered log). The two representations round-trip via
    ``from_audit_state`` / ``to_audit_state``.

    JSON round-trip via ``.model_dump_json()`` / ``.model_validate_json()``
    is the durable form (also the MCP wire format for Slice C, per Q1).
    """

    # Identity + scope
    local_path: str
    owner: str | None = None
    repo: str | None = None
    default_branch: str = "main"
    framework_name: str | None = None
    level: int = 3

    # Progress
    current_position: int = 0
    # audit_results carries CheckResult-shaped dicts (feature 022's TypedDict).
    # Typed as list[dict] here rather than list[CheckResult] because Pydantic
    # strictly validates TypedDict field types at model-construction time,
    # which would reject legacy result dicts that omit optional keys.
    # The TypedDict remains the compile-time contract; runtime is dict.
    audit_results: list[dict[str, Any]] = []
    context_values: dict[str, Any] = {}
    feedback_questions: list[FeedbackQuestionModel] = []
    remediation_results: list[dict[str, Any]] = []

    # RFC-0001 Stage 1 addition: per-control ordered log of every step's
    # contribution, with the step's authority preserved for audit trail.
    evidence: dict[str, list[EvidenceItem]] = {}

    # Terminal state
    error: str | None = None

    model_config = ConfigDict(extra="forbid")

    # -----------------------------------------------------------------
    # Compat conversions with darnit.agent.state.AuditState
    # -----------------------------------------------------------------

    @classmethod
    def from_audit_state(cls, audit_state: Any) -> HarnessState:
        """Build a HarnessState from a dataclass AuditState.

        Kept as a classmethod (not a top-level converter) so a caller
        naturally imports HarnessState and calls the constructor style.
        """
        return cls(
            local_path=audit_state.local_path,
            owner=audit_state.owner,
            repo=audit_state.repo,
            default_branch=audit_state.default_branch,
            framework_name=audit_state.framework_name,
            level=audit_state.level,
            audit_results=list(audit_state.audit_results),
            context_values=dict(audit_state.context_values),
            feedback_questions=[
                FeedbackQuestionModel(
                    control_id=q.control_id,
                    context_key=q.context_key,
                    question=q.question,
                    answer=q.answer,
                    answered=q.answered,
                )
                for q in audit_state.feedback_questions
            ],
            remediation_results=list(audit_state.remediation_results),
            error=audit_state.error,
        )

    def to_audit_state(self) -> Any:
        """Return a dataclass AuditState with this HarnessState's field values.

        The `current_position` and `evidence` fields are dropped -- AuditState
        does not know about them. Round-trip is lossy in that direction; the
        HarnessState-only fields survive only within the ActionPlan loop.
        """
        from darnit.agent.state import AuditState, FeedbackQuestion

        return AuditState(
            local_path=self.local_path,
            owner=self.owner,
            repo=self.repo,
            default_branch=self.default_branch,
            framework_name=self.framework_name,
            level=self.level,
            audit_results=list(self.audit_results),
            feedback_questions=[
                FeedbackQuestion(
                    control_id=q.control_id,
                    context_key=q.context_key,
                    question=q.question,
                    answer=q.answer,
                    answered=q.answered,
                )
                for q in self.feedback_questions
            ],
            context_values=dict(self.context_values),
            remediation_results=list(self.remediation_results),
            error=self.error,
        )

    # -----------------------------------------------------------------
    # Small helpers mirrored from AuditState
    # -----------------------------------------------------------------

    def failing_control_ids(self) -> list[str]:
        return [r["id"] for r in self.audit_results if r.get("status") == "FAIL"]

    def warn_control_ids(self) -> list[str]:
        return [r["id"] for r in self.audit_results if r.get("status") == "WARN"]

    def has_unanswered_questions(self) -> bool:
        return any(not q.answered for q in self.feedback_questions)


# ---------------------------------------------------------------------------
# ActionPlan protocol -- pure state transitions
# ---------------------------------------------------------------------------

# Safety ceiling; matches the value in ``cmd_run`` (MAX_AGENT_ITERATIONS).
_MAX_ITERATIONS = 10


def _step_id_for(integration: str, position: int) -> str:
    """Deterministic step id: ``<integration>-<position>``."""
    return f"{integration}-{position}"


def next_action(state: HarnessState) -> ActionPlan | None:
    """Decide the next ActionPlan step, or None if terminal.

    Pure function; does not mutate ``state``. Mirrors ``darnit.agent.graph.route``
    but returns a typed ActionPlan the caller can inspect and execute.

    Termination conditions:
    - ``state.error`` is set (a prior step errored)
    - ``state.current_position`` has reached the safety ceiling (bounded loop)
    - No FAIL/WARN remains and no re-audit is pending
    """
    if state.error is not None:
        return None

    if state.current_position >= _MAX_ITERATIONS:
        return None

    # If audit_results is empty, we need to (re-)run the audit phase.
    if not state.audit_results:
        return ActionPlan(
            step=StrategyStep(
                id=_step_id_for("audit", state.current_position),
                integration="audit",
                authority="dispositive",
            ),
            control_id="",
            position=state.current_position,
            expected_result_kind="pipeline_phase",
        )

    has_warn = bool(state.warn_control_ids())
    has_fail = bool(state.failing_control_ids())

    # Collect_context prompts a human when WARN + unanswered questions exist.
    if has_warn and state.has_unanswered_questions():
        return ActionPlan(
            step=StrategyStep(
                id=_step_id_for("collect_context", state.current_position),
                integration="collect_context",
                authority="asserted",
            ),
            control_id="",
            position=state.current_position,
            expected_result_kind="user_input",
        )

    if has_fail:
        return ActionPlan(
            step=StrategyStep(
                id=_step_id_for("remediate", state.current_position),
                integration="remediate",
                authority="dispositive",
            ),
            control_id="",
            position=state.current_position,
            expected_result_kind="pipeline_phase",
        )

    # Nothing left to do.
    return None


def submit_result(
    state: HarnessState,
    step_id: str,
    result: dict[str, Any],
) -> HarnessState:
    """Apply the result of a step to the state and return the new state.

    Pure function: returns a new ``HarnessState``, does not mutate the input.

    Raises:
        OutOfOrderSubmission: if ``step_id`` does not match the currently
            expected step (as computed by ``next_action``).
        ResultSchemaMismatch: if ``result`` violates the step's declared
            ``result_schema``. Stage 1 uses coarse pipeline steps with no
            declared schema; this raises only when a step explicitly
            declares one and the payload fails validation.
    """
    expected = next_action(state)
    if expected is None:
        raise OutOfOrderSubmission(
            expected_step_id="<terminal>",
            submitted_step_id=step_id,
        )
    if expected.step.id != step_id:
        raise OutOfOrderSubmission(
            expected_step_id=expected.step.id,
            submitted_step_id=step_id,
        )

    # Optional schema validation (Stage 1 pipeline steps do not declare
    # result_schema; Stage 2 per-handler steps will).
    schema = expected.step.result_schema
    if schema is not None:
        _validate_result_against_schema(step_id, result, schema)

    # Deep-copy the state so the input remains untouched.
    new_state = state.model_copy(deep=True)

    integration = expected.step.integration
    if integration == "audit":
        # Result from an audit run: replaces audit_results + feedback_questions.
        new_state.audit_results = list(result.get("audit_results", []))
        new_state.feedback_questions = [_to_feedback_question_model(q) for q in result.get("feedback_questions", [])]
        new_state.error = result.get("error")
        # Also carry auto-detected owner/repo/default_branch back from prepare_audit.
        for k in ("owner", "repo", "default_branch"):
            if k in result and result[k] is not None:
                setattr(new_state, k, result[k])

    elif integration == "collect_context":
        # Result from collect_context: user answers to feedback questions.
        answers: dict[str, str] = result.get("answers", {})
        # PR #365 review fix: reject shell metacharacters / newlines / null
        # bytes before storing any answer. Answers eventually reach
        # RemediationExecutor._substitute_command; the legacy agent-graph
        # confirm_data flow guards this boundary and the new action-plan
        # collect_context branch must do the same.
        for key, value in answers.items():
            validate_context_answer(key, value)
        new_questions = []
        for q in new_state.feedback_questions:
            if q.context_key in answers:
                new_questions.append(q.model_copy(update={"answer": answers[q.context_key], "answered": True}))
            else:
                new_questions.append(q)
        new_state.feedback_questions = new_questions
        # Merge answers into context_values (in-memory half of the confirmation
        # persistence hook; the DRIVER writes to .project/ via save_context_values).
        new_state.context_values = {**new_state.context_values, **answers}
        # Clear audit_results to signal a re-audit is required.
        new_state.audit_results = []

    elif integration == "remediate":
        new_state.remediation_results = list(result.get("remediation_results", []))

    else:
        raise ResultSchemaMismatch(
            step_id=step_id,
            offending_fields=["integration"],
            message=f"unknown integration {integration!r} for Stage 1 pipeline step",
        )

    # Record the step in the evidence log for provenance.
    # PR #365 review fix: exclude the bulky per-integration payloads
    # (audit_results, feedback_questions, remediation_results) from the
    # raw log -- they already live on `new_state` and duplicating them
    # here made evidence grow O(steps * controls) per audit run.
    _bulky_result_keys = frozenset(
        {"outcome", "reasoning", "audit_results", "feedback_questions", "remediation_results"}
    )
    control_id = expected.control_id or "__pipeline__"
    ev_list = list(new_state.evidence.get(control_id, []))
    ev_list.append(
        EvidenceItem(
            step_id=step_id,
            authority=expected.step.authority,
            outcome=result.get("outcome", "completed"),
            reasoning=result.get("reasoning", ""),
            raw={k: v for k, v in result.items() if k not in _bulky_result_keys},
        )
    )
    new_state.evidence = {**new_state.evidence, control_id: ev_list}

    new_state.current_position = state.current_position + 1
    return new_state


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_feedback_question_model(q: Any) -> FeedbackQuestionModel:
    """Coerce either a FeedbackQuestion dataclass or dict to a Pydantic model."""
    if isinstance(q, FeedbackQuestionModel):
        return q
    if hasattr(q, "control_id") and hasattr(q, "context_key"):
        return FeedbackQuestionModel(
            control_id=q.control_id,
            context_key=q.context_key,
            question=q.question,
            answer=getattr(q, "answer", None),
            answered=getattr(q, "answered", False),
        )
    # Dict form
    return FeedbackQuestionModel(**q)


def _validate_result_against_schema(
    step_id: str,
    result: dict[str, Any],
    schema: dict[str, Any],
) -> None:
    """Minimal JSONSchema-style validation used by ``submit_result``.

    Stage 1 pipeline steps do not declare schemas. Stage 2 per-handler
    steps will; adding jsonschema as a dep at that point is fine, but
    Stage 1 stays lightweight by checking only ``required`` keys.
    """
    required_keys = schema.get("required", [])
    missing = [k for k in required_keys if k not in result]
    if missing:
        raise ResultSchemaMismatch(
            step_id=step_id,
            offending_fields=missing,
            message=f"missing required field(s): {', '.join(missing)}",
        )
