"""MCP tools for the RFC-0001 Stage 1 ActionPlan loop.

Feature 025, Slice C. Exposes ``run_next_action`` and ``submit_action_result``
as framework-independent MCP tools so a coding agent can walk the
Check/Collect/Remediate loop the same way ``cmd_run`` does internally.

Per Q1 clarification (client-owned MCP state), both tools take a serialized
``HarnessState`` on every call and return the new state; the server retains
no per-run state.

Context answers a coding agent submits to a ``collect_context`` step are
kept in the returned state's ``context_values`` for this run only, as
``asserted`` answers. They are never persisted and never recorded as
confirmations (feature 042, FR-002): a person confirms values with
``confirm_project_data``.

See:
- specs/025-rfc0001-stage1/contracts/mcp-tools.md
- specs/025-rfc0001-stage1/data-model.md "Persistence hook"
"""

from __future__ import annotations

import asyncio
from typing import Any

from darnit.core.action_plan import HarnessState, next_action, run_audit_step, submit_result
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

    For the ``audit`` step the server runs the audit itself and records
    only the engine's results (feature 041); ``result`` must be empty. Model
    judgments for PENDING controls go through ``submit_judgment``.

    Args:
        state: JSON-shaped ``HarnessState``.
        step_id: The id of the step being submitted (must match the current
            expected step id from the last ``run_next_action_tool`` call).
        result: The step's output payload; ``{}`` for the audit step.

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

    expected = next_action(validated_state)
    if expected is not None and expected.step.id == step_id and expected.step.integration == "audit":
        if result:
            raise ValueError(
                f"ResultSchemaMismatch: step={step_id!r}, offending_fields={sorted(result)}, message=the audit "
                "step takes no client payload; the server runs the audit and records only its own results. "
                "Submit model judgments with submit_judgment."
            )
        result = await asyncio.to_thread(run_audit_step, validated_state)

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

    return new_state.model_dump(mode="json")


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
            "return the new state. For the audit step pass result={}: the "
            "server runs the audit and records only its own results; submit "
            "model judgments with submit_judgment. Raises OutOfOrderSubmission when step_id "
            "doesn't match the expected next step, and ResultSchemaMismatch "
            "when the result violates a declared result_schema. Context answers "
            "are used for this run only; nothing is written to the repository."
        ),
    )
    logger.debug("Registered harness-loop MCP tools (run_next_action, submit_action_result)")
