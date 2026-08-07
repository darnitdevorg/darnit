"""MCP tools for the RFC-0001 Stage 1 ActionPlan loop.

Feature 025, Slice C. Exposes ``run_next_action`` and ``submit_action_result``
as framework-independent MCP tools so a coding agent can walk the
Check/Collect/Remediate loop the same way ``cmd_run`` does internally.

Per Q1 clarification (client-owned MCP state), both tools take a serialized
``HarnessState`` on every call and return the new state; the server retains
no per-run state.

The persistence hook from data-model.md is applied here for the MCP driver:
after ``submit_action_result`` returns, if the returned state's
``context_values`` gained keys via an ``asserted`` submission, we call
``save_context_values`` on those new keys so an MCP-driven confirmation
persists to ``.project/`` the same way ``darnit run`` does.

See:
- specs/025-rfc0001-stage1/contracts/mcp-tools.md
- specs/025-rfc0001-stage1/data-model.md "Persistence hook"
"""

from __future__ import annotations

from typing import Any

from darnit.core.action_plan import HarnessState, next_action, submit_result
from darnit.core.errors import OutOfOrderSubmission, ResultSchemaMismatch
from darnit.core.logging import get_logger

logger = get_logger("server.tools.harness_loop")


# ---------------------------------------------------------------------------
# Tool: run_next_action
# ---------------------------------------------------------------------------


async def run_next_action_tool(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the next ActionPlan for the client to execute, or None if
    the loop is terminal.

    Args:
        state: JSON-shaped ``HarnessState`` (as produced by
            ``state.model_dump(mode="json")``).

    Returns:
        JSON-shaped ``ActionPlan``, or None on terminal state.

    Raises:
        ValueError: if ``state`` fails HarnessState validation (contract M2).
            The FastMCP layer surfaces this as an MCP protocol error whose
            message names the offending field.
    """
    try:
        validated_state = HarnessState.model_validate(state)
    except Exception as exc:
        # M2: structural validation error surfaces to the client.
        raise ValueError(f"Invalid HarnessState: {exc}") from exc

    plan = next_action(validated_state)
    if plan is None:
        return None
    return plan.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Tool: submit_action_result
# ---------------------------------------------------------------------------


async def submit_action_result_tool(
    state: dict[str, Any],
    step_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Apply the result of an executed step to the state and return the new state.

    Args:
        state: JSON-shaped ``HarnessState``.
        step_id: The id of the step being submitted (must match the current
            expected step id from the last ``run_next_action_tool`` call).
        result: The step's output payload.

    Returns:
        New JSON-shaped ``HarnessState``.

    Raises:
        ValueError: state validation failure (M2), out-of-order submission
            (M3 / A3), schema mismatch (M3 / A4). All three are surfaced as
            MCP protocol errors carrying structured detail.
    """
    try:
        validated_state = HarnessState.model_validate(state)
    except Exception as exc:
        raise ValueError(f"Invalid HarnessState: {exc}") from exc

    try:
        new_state = submit_result(validated_state, step_id, result)
    except OutOfOrderSubmission as exc:
        # M3: structured error with expected + submitted fields preserved.
        raise ValueError(
            f"OutOfOrderSubmission: expected={exc.expected_step_id!r}, submitted={exc.submitted_step_id!r}"
        ) from exc
    except ResultSchemaMismatch as exc:
        raise ValueError(
            f"ResultSchemaMismatch: step={exc.step_id!r}, offending_fields={exc.offending_fields}, message={exc}"
        ) from exc

    # Persistence hook (data-model.md "Persistence hook"): compare pre/post
    # context_values; persist newly-added keys to .project/ via
    # save_context_values (feature 018). Failure is logged but does not
    # fail the MCP call (in-memory state still holds the value).
    _persist_new_asserted_values(validated_state, new_state)

    return new_state.model_dump(mode="json")


def _persist_new_asserted_values(
    prev_state: HarnessState,
    new_state: HarnessState,
) -> None:
    """Write any newly-confirmed context values to ``.project/project.yaml``.

    Mirrors the CLI's ``graph.collect_context`` behavior at the MCP boundary.
    Non-fatal: the in-memory state carries the values regardless.
    """
    new_keys = {k: v for k, v in new_state.context_values.items() if k not in prev_state.context_values}
    if not new_keys:
        return
    try:
        from darnit.config.context_storage import save_context_values

        save_context_values(
            local_path=new_state.local_path,
            values=new_keys,
        )
        logger.info(
            "MCP persistence hook wrote %d context value(s) to %s: %s",
            len(new_keys),
            new_state.local_path,
            list(new_keys.keys()),
        )
    except Exception as exc:
        logger.warning(
            "MCP persistence hook failed to save context values (in-memory state still holds them): %s",
            exc,
        )


# ---------------------------------------------------------------------------
# Registration helper -- called from server/factory.py
# ---------------------------------------------------------------------------


def register_harness_loop_tools(server: Any) -> None:
    """Register the two harness-loop tools on a FastMCP server instance.

    Framework-independent: these tools live in ``darnit-core`` and take a
    serialized ``HarnessState``, so no per-framework binding is needed.
    """
    server.add_tool(
        run_next_action_tool,
        name="run_next_action",
        description=(
            "Return the next ActionPlan step for a HarnessState, or None if "
            "the audit/collect/remediate loop has terminated. Pure function; "
            "the server retains no per-run state (per Q1 clarification)."
        ),
    )
    server.add_tool(
        submit_action_result_tool,
        name="submit_action_result",
        description=(
            "Apply the result of an executed step to a HarnessState and "
            "return the new state. Raises OutOfOrderSubmission when step_id "
            "doesn't match the expected next step, and ResultSchemaMismatch "
            "when the result violates a declared result_schema. Persists "
            "newly-confirmed asserted values to .project/ as a side-effect."
        ),
    )
    logger.debug("Registered harness-loop MCP tools (run_next_action, submit_action_result)")
