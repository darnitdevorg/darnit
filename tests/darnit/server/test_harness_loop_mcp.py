"""MCP tests for the RFC-0001 Stage 1 harness-loop tools.

Feature 025 Slice C. Covers T037-T042b, contracts M1-M7 from
``specs/025-rfc0001-stage1/contracts/mcp-tools.md``, and SC-003.

Testing strategy: the tool functions are plain ``async def`` -- calling
them directly is the in-process client. FastMCP tool-registration is
verified separately via a real server instance (T042).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest

from darnit.core.action_plan import (
    FeedbackQuestionModel,
    HarnessState,
    next_action,
    submit_result,
)
from darnit.server.tools.harness_loop import (
    register_harness_loop_tools,
    run_next_action_tool,
    submit_action_result_tool,
)


def _run(coro):
    """Small sync wrapper for async tool functions.

    Uses a fresh event loop per call so this test file composes with other
    test files that also spin their own loops (feature 025 vs feature 026).
    """
    return asyncio.new_event_loop().run_until_complete(coro)


def _copy_minimal_repo(tmp_path: Path) -> Path:
    """Mirror feature-024's copy helper; needed by the equivalence test."""
    import shutil

    src = Path(__file__).resolve().parent.parent / "cli" / "fixtures" / "minimal_repo"
    dest = tmp_path / "minimal_repo"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    subprocess.run(
        ["git", "init", "--initial-branch=main", "-q"],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "init",
        ],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/fake-owner/fake-repo.git"],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    return dest


# ===========================================================================
# T037: MCP walks the loop to termination
# ===========================================================================


@pytest.mark.slow
def test_mcp_walks_loop_to_termination(tmp_path: Path) -> None:
    """Contract M1, M7: client-owned state round-trips through the MCP tools."""
    from darnit.agent.graph import audit, remediate

    fixture = _copy_minimal_repo(tmp_path)
    state_dict: dict[str, Any] = HarnessState(local_path=str(fixture)).model_dump(mode="json")

    for _ in range(20):  # safety bound; loop should terminate well before
        plan_dict = _run(run_next_action_tool(state_dict))
        if plan_dict is None:
            break

        # Execute the step via the same helpers cmd_run uses.
        integration = plan_dict["step"]["integration"]
        step_id = plan_dict["step"]["id"]
        harness_state = HarnessState.model_validate(state_dict)

        if integration == "audit":
            audit_state = harness_state.to_audit_state()
            audit_state = audit(audit_state)
            result = {
                "audit_results": audit_state.audit_results,
                "feedback_questions": [
                    {
                        "control_id": q.control_id,
                        "context_key": q.context_key,
                        "question": q.question,
                        "answer": q.answer,
                        "answered": q.answered,
                    }
                    for q in audit_state.feedback_questions
                ],
                "owner": audit_state.owner,
                "repo": audit_state.repo,
                "default_branch": audit_state.default_branch,
                "error": audit_state.error,
            }
        elif integration == "collect_context":
            result = {"answers": {}}
        elif integration == "remediate":
            audit_state = harness_state.to_audit_state()
            audit_state = remediate(audit_state, dry_run=True)
            result = {"remediation_results": audit_state.remediation_results}
        else:
            pytest.fail(f"Unexpected integration: {integration}")

        state_dict = _run(submit_action_result_tool(state_dict, step_id, result))

        if integration == "collect_context":
            break  # noninteractive breaks

    # Terminal reached; state MUST still validate as HarnessState.
    final = HarnessState.model_validate(state_dict)
    assert final.error is None
    assert len(final.audit_results) > 0


# ===========================================================================
# T038: three-way equality (direct == CLI == MCP)
# ===========================================================================


@pytest.mark.slow
def test_mcp_equals_direct_equals_cli(tmp_path: Path) -> None:
    """SC-003: MCP-driven audit produces the same results as direct-Python
    and CLI paths on the same fixture. Contract M7: no JSON round-trip loss.
    """
    from darnit.agent.feedback import get_feedback_handler
    from darnit.agent.graph import audit, collect_context, remediate, route
    from darnit.agent.state import AuditState

    fixture = _copy_minimal_repo(tmp_path)

    # Path 1: direct-Python (next_action/submit_result loop)
    direct_state = HarnessState(local_path=str(fixture))
    while True:
        plan = next_action(direct_state)
        if plan is None:
            break
        integration = plan.step.integration
        if integration == "audit":
            a = direct_state.to_audit_state()
            a = audit(a)
            direct_state = submit_result(
                direct_state,
                plan.step.id,
                {
                    "audit_results": a.audit_results,
                    "feedback_questions": [
                        {
                            "control_id": q.control_id,
                            "context_key": q.context_key,
                            "question": q.question,
                            "answer": q.answer,
                            "answered": q.answered,
                        }
                        for q in a.feedback_questions
                    ],
                    "owner": a.owner,
                    "repo": a.repo,
                    "default_branch": a.default_branch,
                    "error": a.error,
                },
            )
        elif integration == "collect_context":
            direct_state = submit_result(direct_state, plan.step.id, {"answers": {}})
            break
        elif integration == "remediate":
            a = direct_state.to_audit_state()
            a = remediate(a, dry_run=True)
            direct_state = submit_result(
                direct_state,
                plan.step.id,
                {"remediation_results": a.remediation_results},
            )
            break

    # Path 2: cmd_run-style CLI loop
    cli_state = AuditState(local_path=str(fixture))
    fb = get_feedback_handler("noninteractive")
    cli_state = audit(cli_state)
    for _ in range(10):
        if cli_state.error:
            break
        step = route(cli_state)
        if step == "collect_context":
            answers = {
                q.context_key: (fb.ask(q.control_id, q.question) or "")
                for q in cli_state.feedback_questions
                if not q.answered
            }
            answers = {k: v for k, v in answers.items() if v}
            if not answers:
                break
            cli_state = collect_context(cli_state, answers)
            cli_state = audit(cli_state)
        elif step == "remediate":
            cli_state = remediate(cli_state, dry_run=False)
            break
        else:
            break

    # Path 3: MCP tools driving through JSON round-trips at every step
    mcp_state_dict: dict[str, Any] = HarnessState(local_path=str(fixture)).model_dump(mode="json")
    for _ in range(20):
        plan_dict = _run(run_next_action_tool(mcp_state_dict))
        if plan_dict is None:
            break
        integration = plan_dict["step"]["integration"]
        step_id = plan_dict["step"]["id"]
        h = HarnessState.model_validate(mcp_state_dict)
        if integration == "audit":
            a = h.to_audit_state()
            a = audit(a)
            result = {
                "audit_results": a.audit_results,
                "feedback_questions": [
                    {
                        "control_id": q.control_id,
                        "context_key": q.context_key,
                        "question": q.question,
                        "answer": q.answer,
                        "answered": q.answered,
                    }
                    for q in a.feedback_questions
                ],
                "owner": a.owner,
                "repo": a.repo,
                "default_branch": a.default_branch,
                "error": a.error,
            }
        elif integration == "collect_context":
            result = {"answers": {}}
        elif integration == "remediate":
            a = h.to_audit_state()
            a = remediate(a, dry_run=True)
            result = {"remediation_results": a.remediation_results}
        else:
            pytest.fail(f"Unexpected integration: {integration}")
        mcp_state_dict = _run(submit_action_result_tool(mcp_state_dict, step_id, result))
        if integration == "collect_context":
            break

    mcp_state = HarnessState.model_validate(mcp_state_dict)

    def _key(results):
        return sorted((r.get("id", ""), r.get("status", "")) for r in results)

    direct_key = _key(direct_state.audit_results)
    cli_key = _key(cli_state.audit_results)
    mcp_key = _key(mcp_state.audit_results)

    assert direct_key == cli_key == mcp_key, (
        f"Three-way equality failed:\n  direct: {direct_key}\n  cli:    {cli_key}\n  mcp:    {mcp_key}"
    )


# ===========================================================================
# T039: out-of-order structured error
# ===========================================================================


class TestOutOfOrderMcpError:
    """FR-012 + Contract M3: OutOfOrderSubmission surfaces as MCP error
    carrying expected + submitted step ids."""

    def test_out_of_order_raises_value_error_with_structured_message(self) -> None:
        state = HarnessState(local_path="/tmp").model_dump(mode="json")
        with pytest.raises(ValueError) as excinfo:
            _run(submit_action_result_tool(state, "wrong-step-id", {}))
        msg = str(excinfo.value)
        assert "OutOfOrderSubmission" in msg
        assert "audit-0" in msg  # expected
        assert "wrong-step-id" in msg  # submitted


# ===========================================================================
# T040: schema mismatch structured error
# ===========================================================================


class TestSchemaMismatchMcpError:
    """FR-012 + Contract M3: ResultSchemaMismatch surfaces as MCP error."""

    def test_invalid_state_raises_named_error(self) -> None:
        # Bad state shape (extra unknown field violates extra="forbid").
        state = HarnessState(local_path="/tmp").model_dump(mode="json")
        state["nonexistent_field"] = "surprise"
        with pytest.raises(ValueError) as excinfo:
            _run(run_next_action_tool(state))
        assert "Invalid HarnessState" in str(excinfo.value)


# ===========================================================================
# T041: JSON round-trip
# ===========================================================================


class TestMcpStateRoundtrip:
    """Contract M7: state emitted by run_next_action_tool round-trips
    losslessly when submitted back to submit_action_result_tool."""

    def test_state_survives_serialization(self) -> None:
        # Build a populated state, dump/load, verify equality.
        s = HarnessState(
            local_path="/tmp",
            owner="acme",
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
        dumped = s.model_dump(mode="json")
        restored = HarnessState.model_validate(dumped)
        assert restored == s

    def test_state_survives_mcp_tool_dispatch(self) -> None:
        """Full round-trip: dict in -> tool -> dict out -> HarnessState."""
        s = HarnessState(local_path="/tmp")
        state_dict = s.model_dump(mode="json")
        plan_dict = _run(run_next_action_tool(state_dict))
        assert plan_dict is not None
        # State dict was not mutated by the tool.
        assert state_dict == s.model_dump(mode="json")


# ===========================================================================
# T042: discoverable via list_tools
# ===========================================================================


class TestToolDiscovery:
    """Contract M4: both tools discoverable through list_tools."""

    def test_tools_registered_on_fastmcp_server(self) -> None:
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("test-harness")
        register_harness_loop_tools(server)

        # FastMCP has an internal tool manager we can inspect. The exact
        # accessor depends on the FastMCP version, so we try both known paths.
        tool_names = _list_registered_tool_names(server)
        assert "run_next_action" in tool_names
        assert "submit_action_result" in tool_names

    def test_tool_descriptions_present(self) -> None:
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("test-harness-2")
        register_harness_loop_tools(server)
        # Grab the tool objects and verify non-empty descriptions.
        descs = _get_registered_tool_descriptions(server)
        assert descs.get("run_next_action")
        assert descs.get("submit_action_result")


def _list_registered_tool_names(server) -> set[str]:
    """Best-effort tool-name enumeration across FastMCP internal shapes."""
    # FastMCP >= 1.x exposes tools via server._tool_manager._tools
    tm = getattr(server, "_tool_manager", None)
    if tm is not None:
        tools = getattr(tm, "_tools", {})
        return set(tools.keys())
    # Fallback: iterate over attributes and hope for the best.
    return set()


def _get_registered_tool_descriptions(server) -> dict[str, str]:
    tm = getattr(server, "_tool_manager", None)
    if tm is None:
        return {}
    tools = getattr(tm, "_tools", {})
    result: dict[str, str] = {}
    for name, tool in tools.items():
        result[name] = getattr(tool, "description", "") or ""
    return result


# ===========================================================================
# T042b: MCP-side persistence hook
# ===========================================================================


@pytest.mark.slow
def test_mcp_asserted_submission_persists_to_project_yaml(tmp_path: Path) -> None:
    """Persistence hook: an asserted submission via MCP writes to .project/.

    Simulates a scenario where a Collect step's asserted result adds a
    context value. The MCP wrapper's ``_persist_new_asserted_values`` hook
    must call save_context_values on the new key, causing the change to
    land in ``.project/project.yaml``.
    """
    # Build a fixture with a .project/project.yaml the save routine can write to.
    (tmp_path / ".project").mkdir()
    (tmp_path / ".project" / "project.yaml").write_text("name: test-repo\n")

    # Start state with an unanswered feedback question so next_action returns
    # a collect_context step.
    state = HarnessState(
        local_path=str(tmp_path),
        audit_results=[{"id": "A", "status": "WARN", "details": "", "level": 1}],
        feedback_questions=[
            FeedbackQuestionModel(
                control_id="A",
                context_key="security_contact",
                question="Who is the security contact?",
                answered=False,
            ),
        ],
    )
    state_dict = state.model_dump(mode="json")

    # Confirm what the next action is.
    plan_dict = _run(run_next_action_tool(state_dict))
    assert plan_dict is not None
    assert plan_dict["step"]["integration"] == "collect_context"
    step_id = plan_dict["step"]["id"]

    # Submit an asserted answer.
    _run(
        submit_action_result_tool(
            state_dict,
            step_id,
            {"answers": {"security_contact": "sec@example.com"}},
        )
    )

    # .project/project.yaml MUST now contain the confirmed value.
    # save_context_values (feature 018) applies its schema mapping when
    # persisting, so "security_contact" flattens into the nested
    # `security: { contact: ... }` structure of .project/project.yaml.
    # The invariant we care about here is that the VALUE landed on disk;
    # the exact YAML key placement is feature 018's contract.
    yaml_content = (tmp_path / ".project" / "project.yaml").read_text()
    assert "sec@example.com" in yaml_content, (
        f"Persistence hook did not write the confirmed value to disk.\nYAML content:\n{yaml_content}"
    )
