# Contract: MCP tools `run_next_action` / `submit_action_result`

**Feature**: 025-rfc0001-stage1
**Date**: 2026-08-05

MCP tool surface Stage 1 adds. Wraps the `darnit.core.action_plan` ActionPlan protocol (contract `action-plan-protocol.md`). Client-owned state per Q1 clarification: every call takes and returns the full `HarnessState`.

---

## Tool: `run_next_action`

**Signature** (JSON schema-shaped):

```python
async def run_next_action(state: dict) -> dict | None:
    """
    Args:
        state: JSON-shaped HarnessState (as produced by state.model_dump(mode="json"))

    Returns:
        JSON-shaped ActionPlan, or None if the loop is terminal.
    """
```

**Behavior**:
- Validates `state` against `HarnessState`. If invalid, returns an MCP error whose message names the offending field.
- Calls `next_action(HarnessState.model_validate(state))`.
- Returns the result as `ActionPlan.model_dump(mode="json")` or None.

## Tool: `submit_action_result`

**Signature**:

```python
async def submit_action_result(state: dict, step_id: str, result: dict) -> dict:
    """
    Args:
        state: JSON-shaped HarnessState
        step_id: The id of the step being submitted (must match the current expected step)
        result: The step's output; validated against the step's declared result_schema

    Returns:
        JSON-shaped new HarnessState.
    """
```

**Behavior**:
- Validates `state` against `HarnessState`. Same error surface as `run_next_action`.
- Calls `submit_result(HarnessState.model_validate(state), step_id, result)`.
- On `OutOfOrderSubmission`: returns MCP error with fields `expected_step_id` and `submitted_step_id`.
- On `ResultSchemaMismatch`: returns MCP error with fields `step_id`, `offending_fields`, and `message`.
- On success: returns the new state as `.model_dump(mode="json")`.

## Contract items

- **M1**: The server is stateless with respect to per-run state (Q1 clarification). No session id, no persistent per-client store. Two concurrent clients driving two audits do not share state; a single client driving one audit MUST round-trip the state on every call.
- **M2**: Both tools MUST validate `state` structurally at the boundary. A malformed state produces a named error, never a crash.
- **M3**: The MCP error surface for `OutOfOrderSubmission` and `ResultSchemaMismatch` MUST carry the same fields as the direct-call typed errors. FR-012 requires a test proving this equivalence.
- **M4**: The tools MUST be discoverable via `list_tools`. Names and descriptions follow the existing MCP tool-registration conventions in `packages/darnit/src/darnit/server/factory.py`.
- **M5**: The tools MUST NOT invoke the LLM directly. LLM invocation is the caller's responsibility (per contract A9). This keeps the MCP surface predictable and lets agents inject their own LLM stack when appropriate.
- **M6**: The tools MUST NOT print to stdout/stderr. All output is via the MCP return value.
- **M7**: JSON round-tripping: the JSON produced by `run_next_action` MUST round-trip through `HarnessState.model_validate_json` on the next call. Tests assert this end-to-end (state emitted -> serialized -> submitted back -> equal).

## Non-contract items (explicitly NOT pinned)

- MCP transport (stdio vs SSE vs HTTP). Whatever the server currently supports is fine.
- Authentication. The MCP server has no auth surface in Stage 1; this is a Stage 3 concern.
- Rate limiting. Not applicable to a client-owned-state design.
- Session lifetime. There are no sessions.

## Contract-update procedure

Same as `action-plan-protocol.md`: update the file in the same PR as the code change, update the corresponding test, note in PR description.
