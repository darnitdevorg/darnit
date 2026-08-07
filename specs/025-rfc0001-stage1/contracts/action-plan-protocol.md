# Contract: `darnit.core.action_plan` ActionPlan Protocol

**Feature**: 025-rfc0001-stage1
**Date**: 2026-08-05

Public typed contract that `darnit-core` exposes for driving the Check/Collect/Remediate loop. Consumed by `cmd_run` (CLI), the MCP tools (`run_next_action` / `submit_action_result`), and any future harness driver.

---

## Public API

```python
from darnit.core.action_plan import (
    ActionPlan,          # single-step surface
    HarnessState,        # serializable state
    StrategyStep,        # one entry in a control's strategy list
    EvidenceItem,        # accumulated evidence with authority
    next_action,         # (state) -> ActionPlan | None
    submit_result,       # (state, step_id, result) -> HarnessState
)
from darnit.core.errors import (
    OutOfOrderSubmission,
    ResultSchemaMismatch,
    AuthorityViolation,
)
```

## Contract items

- **A1**: `next_action(state: HarnessState) -> ActionPlan | None` is a pure function. It MUST NOT mutate `state`. On terminal state (all controls resolved, or `state.error is not None`), returns None.
- **A2**: `submit_result(state: HarnessState, step_id: str, result: dict) -> HarnessState` is a pure function. It returns a new `HarnessState`; it MUST NOT mutate the input.
- **A3**: `submit_result` raises `OutOfOrderSubmission(expected_step_id, submitted_step_id)` when `step_id` does not match the current expected step. No state transition occurs.
- **A4**: `submit_result` raises `ResultSchemaMismatch(step_id, offending_fields, message)` when `result` does not conform to the step's declared `result_schema`. No state transition occurs.
- **A5**: `submit_result` records an `EvidenceItem` with `authority` equal to the step's declared authority for every successful submission, regardless of outcome (PASS/FAIL/inconclusive/ERROR).
- **A6**: The Check-phase execution rule (spec FR-003) is applied inside `submit_result`. Suggestive results attach evidence and advance to the next step; dispositive/asserted results with terminal outcomes close the control; ERROR closes the control regardless of authority.
- **A7**: `HarnessState.model_dump(mode="json")` produces a schema-stable JSON representation. `HarnessState.model_validate_json(...)` round-trips the JSON back to a `HarnessState`. Round-trip equality (`state == HarnessState.model_validate_json(state.model_dump_json())`) MUST hold for any valid state.
- **A8**: `ActionPlan.model_dump(mode="json")` is JSON-serializable. Same round-trip property.
- **A9**: `next_action` and `submit_result` do NOT invoke the LLM, do NOT touch the filesystem, and do NOT open network sockets. They are pure state transitions. LLM invocation happens in a separate step-execution phase (in `cmd_run`, in the MCP tool wrapper, or in the caller code).
- **A10**: `next_action` is safe to call concurrently on independent states (different `HarnessState` instances). Concurrent calls on the same state instance produce the same result (immutable).

## Error surface

| Error | When | State transition |
|-------|------|------------------|
| `OutOfOrderSubmission` | `submit_result` called with wrong step_id | None |
| `ResultSchemaMismatch` | Submitted result fails schema validation | None |
| `AuthorityViolation` | Control load: a step declares an impossible authority (e.g., python handler claiming `asserted`) | Raised at load time; control not loaded |

## Non-contract items (explicitly NOT pinned by Stage 1)

- Iteration ordering of unresolved controls beyond "in the strategy list's declared order." Stage 2 may add parallelism or reordering; Stage 1 leaves this unspecified.
- Latency of `next_action` and `submit_result`. Both are pure Python; assumed sub-millisecond. If a future implementation makes either async or expensive, that is a contract change.
- Behavior when `HarnessState` is mutated externally between calls. Callers MUST NOT mutate; if they do, results are undefined.

## Contract-update procedure

Follows feature 024's pattern:
1. Update this file in the same PR as the code change.
2. Update the corresponding test assertion (`tests/darnit/core/test_action_plan.py`).
3. Note the change in the PR description as `Contract change:`.

Reviewers reject any PR whose test edits are not accompanied by a matching contract edit.
