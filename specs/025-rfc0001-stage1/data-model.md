# Data Model: RFC-0001 Stage 1

**Feature**: 025-rfc0001-stage1
**Date**: 2026-08-05

Types, validation rules, and state transitions introduced by Stage 1. Existing types (`CheckResult`, `HandlerResult`, `AuditState`) are annotated with the fields Stage 1 adds or renames.

---

## New types

### 1. `Authority` (Literal)

**Location**: `packages/darnit/src/darnit/core/authority.py` (new).

**Definition**:

```python
from typing import Literal

Authority = Literal["dispositive", "suggestive", "asserted"]
```

**Semantics**:
- `dispositive` -- the step's output settles the question. Only a dispositive result may conclude a control PASS or FAIL. Examples: `file_exists`, `gh_api`, `exec` with known-safe command shape.
- `suggestive` -- the step's output is a candidate. It attaches as evidence and never concludes anything. Examples: `llm_eval`, `git_history_infer`.
- `asserted` -- a human confirmed the value. Concludes a control; recorded and reported distinctly from a dispositive PASS. Cannot be claimed by code alone; the only writer is feature 018's `save_context_values` (or its equivalent after the extension).

**Validation rules**:
- FR-002: every `HandlerResult` MUST carry an `authority` value from this domain. Handlers that omit or return an unknown value fail registration at load time.
- Spec edge case: a step whose declared authority is `"asserted"` MUST correspond to a `handler = "manual"` step or a step that reads from confirmed context. A declared-authority mismatch is a schema violation caught by the loader.

### 2. `HandlerResult.authority`

**Location**: `packages/darnit/src/darnit/sieve/handler_registry.py` (modification).

**Change**: The existing `HandlerResult` dataclass gets an `authority: Authority` field. Default is not permitted (FR-001: "no default; a schema violation at load time is preferable to an ambiguous default at run time"). Existing built-in handlers get their authority set at their definition site.

**Migration for existing handlers**:

| Handler | Authority | Rationale |
|---------|-----------|-----------|
| `file_exists` | `dispositive` | Observes filesystem ground truth. |
| `exec` (with structured output) | `dispositive` | Runs a tool that reports fact. |
| `regex` (over file contents) | `dispositive` | Observes actual content. |
| `api_call` | `dispositive` | External API is authoritative for its scope. |
| `llm_eval` | `suggestive` | LLM output is a proposal, per Constitution II + RFC. |
| `manual` | annotated as `manual` kind; effective authority resolves to `asserted` if a human confirms | Human-only. |
| `file_create` | dispositive (result); but it is a Remediate step, not Check | Reports what was created. |
| `project_update` | asserted (writes confirmed values); Collect step | Writes to `.project/` after confirmation. |

### 3. `CheckResult.authority`

**Location**: `packages/darnit/src/darnit/sieve/models.py` (modification to existing TypedDict from feature 022).

**Change**: The `CheckResult` TypedDict gets an `authority: NotRequired[Authority]` field. Marked `NotRequired` for back-compat with pre-Stage-1 serialized results that lack the field.

**Safety invariant (FR-001)**: The runner MUST treat any authority-less result as if `authority = "suggestive"` for disposition purposes. Concretely, `resolve_step_result` (see "Check-phase execution rule") maps a `CheckResult` with `.get("authority")` unset to a suggestive disposition (`ATTACH_EVIDENCE_AND_CONTINUE` or `TERMINATE_INCONCLUSIVE`), NEVER `CONCLUDE_PASS`/`CONCLUDE_FAIL`. This preserves the safety property ("no PASS without explicit authority") without breaking legacy serialization. A test MUST assert this: a synthetic `CheckResult({"id": "X", "status": "PASS"})` (no authority key) cannot cause `CONCLUDE_PASS`.

### 4. `ActionPlan`

**Location**: `packages/darnit/src/darnit/core/action_plan.py` (new).

**Definition**:

```python
from pydantic import BaseModel
from typing import Literal, Any

class StrategyStep(BaseModel):
    """One entry in a control's strategy list."""
    id: str                              # stable id used by submit_result correlation
    integration: str                     # handler name (short form; resolved through registry)
    params: dict[str, Any] = {}          # handler-specific parameters
    authority: Authority                 # declared authority; validated at load time
    result_schema: dict[str, Any] | None # optional JSONSchema for submitted results

class ActionPlan(BaseModel):
    """A single step surfaced to a caller (agent, CLI, or driver)."""
    step: StrategyStep
    control_id: str
    position: int                        # 0-indexed position in the strategy list
    total_steps: int                     # total steps in the list; for progress display
    expected_result_kind: Literal["handler_result", "user_input", "confirmation"]
```

**Semantics**:
- Emitted by `next_action(state)` -- one at a time.
- Serializable end-to-end (Pydantic `.model_dump()` / `.model_validate_json()`).
- `expected_result_kind = "user_input"` for `manual` steps; `"confirmation"` for Collect steps that need a human yes/no on a proposed value; `"handler_result"` for automated handlers.

### 5. `HarnessState`

**Location**: `packages/darnit/src/darnit/core/action_plan.py` (new; adapts today's `AuditState` from `packages/darnit/src/darnit/agent/state.py`).

**Two evidence stores; relationship pinned**:

- `audit_results: list[CheckResult]` -- ONE entry per control. Each entry's `authority` field is the authority of the step that CONCLUDED the control (`dispositive` PASS/FAIL, `asserted`, or ERROR terminal). Consumers wanting a control's final verdict + conclusion authority read from here. Attestation reads from here (contract T2).
- `evidence: dict[str, list[EvidenceItem]]` -- ordered per-step LOG for every control that had at least one step run. Includes all attempted steps: suggestive attachments that did not conclude, the step that eventually did conclude, and any post-conclusion steps that would have run under a different rule (though the current rule stops the list on conclusion). Consumers wanting audit trail / provenance / debug-why-inconclusive read from here.

Rule of thumb: `audit_results[i].authority` is the SINGLE authority reported for the control's PASS/FAIL/inconclusive verdict; `evidence[control_id]` is the ordered history of what was tried and what each step returned. The two are consistent (the concluding step's EvidenceItem authority matches `audit_results[i].authority`) but not redundant -- one is the verdict view, the other is the history view.

**Definition** (skeleton):

```python
class HarnessState(BaseModel):
    """Serializable, client-owned state carried through the ActionPlan loop."""
    # Identity + scope
    local_path: str
    owner: str | None = None
    repo: str | None = None
    framework_name: str | None = None
    level: int = 3

    # Progress
    current_position: int = 0
    audit_results: list[CheckResult] = []
    context_values: dict[str, str] = {}
    feedback_questions: list[FeedbackQuestion] = []

    # Accumulated evidence with authority breakdown (Stage 1 addition)
    evidence: dict[str, list[EvidenceItem]] = {}

    # Terminal state
    error: str | None = None

    model_config = ConfigDict(extra="forbid")
```

**Validation rules**:
- All fields JSON-serializable; no `Path`, `File`, subprocess handle, or callable may live on the model.
- `model_dump(mode="json")` produces the MCP wire format (R3).
- `model_validate_json(...)` accepts a snapshot from a client (round-trippable).

**Backward compatibility**:
- `darnit.agent.state.AuditState` becomes a re-export of `HarnessState` for the transition. Existing imports do not break.
- Legacy fields on `AuditState` that no longer make sense on `HarnessState` (if any) get marked deprecated in the transition; complete removal is Stage 2 territory.

### 6. `EvidenceItem`

**Location**: `packages/darnit/src/darnit/core/action_plan.py` (new).

**Definition**:

```python
class EvidenceItem(BaseModel):
    step_id: str                # references the StrategyStep that produced this
    authority: Authority        # copied from the step at emission time
    outcome: str                # handler-specific ("yes", "no", "pass", "matched", ...)
    reasoning: str = ""         # human-readable; may be from an LLM
    raw: dict[str, Any] = {}    # full handler output, for auditing + attestation provenance
```

**Semantics**:
- Every step that produces output records an `EvidenceItem` on the state.
- Suggestive evidence accumulates without concluding.
- Dispositive evidence that concludes a control still records here for provenance in the attestation.

### 7. Typed errors

**Location**: `packages/darnit/src/darnit/core/errors.py` (new or extended).

```python
class OutOfOrderSubmission(Exception):
    """Raised by submit_result when caller submits for a step other than the expected next one."""
    def __init__(self, expected_step_id: str, submitted_step_id: str):
        self.expected_step_id = expected_step_id
        self.submitted_step_id = submitted_step_id
        super().__init__(
            f"Expected result for step {expected_step_id!r}, got {submitted_step_id!r}"
        )

class ResultSchemaMismatch(Exception):
    """Raised by submit_result when the submitted result violates the step's declared schema."""
    def __init__(self, step_id: str, offending_fields: list[str], message: str):
        self.step_id = step_id
        self.offending_fields = offending_fields
        super().__init__(f"Step {step_id!r}: {message}")

class AuthorityViolation(Exception):
    """Raised at load time when a control's strategy list declares an impossible
    authority (e.g., a python handler claiming 'asserted', or a step whose
    kind='manual' but authority != 'asserted')."""
```

### 8. `LLMStep` Protocol + `PydanticAILLMStep`

**Location**: `packages/darnit/src/darnit/core/llm_step.py` (new). See research.md R6 for the concrete shape.

---

## Modified types

### `HandlerResult` (existing)

- Adds required `authority: Authority` field.
- Migration: every built-in handler declaration in `sieve/builtin_handlers.py` sets its authority when constructing `HandlerResult(...)`. TOML-level overrides at the step level MAY tighten but MUST NOT loosen (a handler that defaults to `dispositive` may be marked `suggestive` in a specific control's strategy list; the reverse is a schema violation).

### `CheckResult` (existing, from feature 022)

- Adds `authority: NotRequired[Authority]` field.
- Rationale for NotRequired: back-compat with pre-Stage-1 serialized results. Absent authority is not a valid conclusion input; the runner rejects results without authority at Slice A completion.

### `AuditState` -> `HarnessState`

- Rename with re-export for compat (see #5 above).
- Adds `evidence: dict[str, list[EvidenceItem]]` field.
- Adds `current_position: int` for ActionPlan positioning.

---

## Non-entities (things this feature does NOT introduce)

- No new database schema (filesystem-only project, unchanged).
- No new attestation predicate URL (per Q2: additive within v1).
- No new HandlerResult status value (six-status Literal from feature 022 is unchanged).
- No new user-facing CLI flags on `darnit run` (the CLI shell is unchanged; only its internals refactor).
- No new MCP transport, security model, or auth surface.
- No new `.project/` schema (feature 018 handles persistence).

---

## State transitions

### `next_action(state) -> ActionPlan | None`

- If `state.error is not None`: return None (terminal).
- If `state.current_position >= len(current_control.steps)` and no controls remain: return None.
- If the current step's kind is `manual` and no confirmation exists: return `ActionPlan(step=..., expected_result_kind="user_input")`.
- If the current step is a Collect confirmation on a `suggestive` value: return `ActionPlan(step=..., expected_result_kind="confirmation")`.
- Otherwise: return `ActionPlan(step=..., expected_result_kind="handler_result")`.
- Pure function; does not mutate `state`.

### `submit_result(state, step_id, result) -> HarnessState`

- If `step_id` != expected next step id: raise `OutOfOrderSubmission(expected, submitted)`. No state change.
- If `result` fails validation against the step's `result_schema`: raise `ResultSchemaMismatch(step_id, fields, message)`. No state change.
- Otherwise: build the new state:
  - Append an `EvidenceItem(step_id=step_id, authority=step.authority, ...)` to `state.evidence[control_id]`.
  - Advance `current_position` past the step.
  - Apply the Check-phase execution rule (FR-003): if authority is `dispositive`/`asserted` and outcome is terminal (PASS/FAIL), close the control; if `suggestive`, keep going; if ERROR, terminate the control's list.
  - **If the resolved step has `authority = "asserted"` AND declares a `context_key`**: set `state.context_values[context_key] = result["value"]` (or equivalent field per the step's `result_schema`). This is the in-memory half of the confirmation persistence.
  - Return the new state.
- Pure function; returns a new state, does not mutate the input.

### Persistence hook (out of `submit_result`; called by the wrapping driver)

`submit_result` is deliberately pure and does not touch the filesystem (contract A9). Confirmation persistence to `.project/` -- required by US4 acceptance #2 and feature 018's `save_context_values` -- happens in the driver that WRAPS `submit_result`, not inside it. Specifically:

- **CLI driver** (`drive_action_plan` in `cmd_run`): after `submit_result` returns a new state whose `context_values` gained keys via an `asserted` submission, the driver calls `save_context_values(local_path=state.local_path, values={<new keys only>})`. The write is best-effort; on failure the in-memory state still holds the values.
- **MCP driver** (`submit_action_result` tool wrapper): same behavior. The MCP wrapper looks at the delta between the input state's `context_values` and the output state's `context_values`; any newly added keys get persisted.

This keeps `submit_result` mechanically testable as a pure state transition while ensuring durability at the driver boundary. Tests for the driver wrappers assert the persistence side-effect; tests for `submit_result` itself only assert the in-memory `context_values` change.

### Check-phase execution rule (spec FR-003)

Encoded as a single function `resolve_step_result(step, result, state) -> StepDisposition` where `StepDisposition` is one of:

```python
class StepDisposition(str, Enum):
    CONCLUDE_PASS = "conclude_pass"
    CONCLUDE_FAIL = "conclude_fail"
    ATTACH_EVIDENCE_AND_CONTINUE = "attach_and_continue"
    TERMINATE_INCONCLUSIVE = "terminate_inconclusive"
    TERMINATE_ERROR = "terminate_error"
```

The rule:
- `authority in {"dispositive", "asserted"}` and outcome is PASS -> CONCLUDE_PASS.
- `authority in {"dispositive", "asserted"}` and outcome is FAIL -> CONCLUDE_FAIL.
- outcome is ERROR -> TERMINATE_ERROR (regardless of authority).
- `authority == "suggestive"` -> ATTACH_EVIDENCE_AND_CONTINUE.
- If list exhausted with only suggestive results: TERMINATE_INCONCLUSIVE.
- If step is `manual` and no confirmation yet: return the plan to caller (do not resolve).

This is the safety invariant. SC-001 and SC-008 test it directly.
