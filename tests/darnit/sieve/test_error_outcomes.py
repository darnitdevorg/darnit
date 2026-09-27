"""Broken measurements are ERROR, never FAIL (feature 041 US2, FR-007).

Covers the handlers (``exec`` with a missing binary, ``mcp`` with a missing
required server) and the orchestrator rule: an ERROR step is recorded, later
steps still run, a later conclusive step wins, and a control no later step
concludes ends ERROR with the first cause.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from darnit.config.framework_schema import HandlerInvocation, McpServerConfig
from darnit.core.models import ExecutionContext
from darnit.sieve.builtin_handlers import exec_handler, mcp_handler
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)
from darnit.sieve.mcp_pool import McpPool, McpServerHandshakeFailed, McpServerUnusable
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator


class TestExecMissingBinary:
    def test_missing_binary_is_error_missing_tool(self, tmp_path) -> None:
        ctx = HandlerContext(local_path=str(tmp_path), control_id="EX-01")
        result = exec_handler({"command": ["definitely-not-a-real-binary-041"]}, ctx)
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "missing_tool"
        assert "definitely-not-a-real-binary-041" in result.message

    def test_control_with_missing_binary_ends_error_not_fail(self, tmp_path) -> None:
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="exec", command=["definitely-not-a-real-binary-041"], fail_exit_codes=[1]),
            HandlerInvocation(handler="manual", steps=["Run the tool by hand"]),
        )
        assert result.status == "ERROR"
        assert result.error == {"class": "missing_tool", "cause": "Command not found: definitely-not-a-real-binary-041"}


class TestMcpRequiredServerMissing:
    def _ctx(self, tmp_path, server_config: McpServerConfig, pool) -> HandlerContext:
        return HandlerContext(
            local_path=str(tmp_path),
            control_id="MCP-01",
            execution_context=ExecutionContext(
                owner="octo",
                repo="hello",
                local_path=str(tmp_path),
                mcp_servers={"srv": server_config},
            ),
            mcp_pool=pool,
        )

    def test_required_server_binary_missing_is_error(self, tmp_path) -> None:
        server_config = McpServerConfig(command=["definitely-not-a-real-mcp-041"], optional=False)
        pool = McpPool(servers={"srv": server_config})
        try:
            result = mcp_handler({"server": "srv", "tool": "t", "args": {}}, self._ctx(tmp_path, server_config, pool))
        finally:
            pool.teardown_all()
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "missing_tool"

    def test_optional_server_binary_missing_stays_inconclusive(self, tmp_path) -> None:
        server_config = McpServerConfig(command=["definitely-not-a-real-mcp-041"], optional=True)
        pool = McpPool(servers={"srv": server_config})
        try:
            result = mcp_handler({"server": "srv", "tool": "t", "args": {}}, self._ctx(tmp_path, server_config, pool))
        finally:
            pool.teardown_all()
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.error_class == "missing_tool"

    @pytest.mark.parametrize("exc", [McpServerHandshakeFailed, McpServerUnusable])
    def test_required_server_unusable_is_error(self, tmp_path, exc) -> None:
        server_config = McpServerConfig(command=["srv"], optional=False)
        pool = MagicMock()
        pool.call_tool.side_effect = exc("simulated")
        pool._sessions = {}
        result = mcp_handler({"server": "srv", "tool": "t", "args": {}}, self._ctx(tmp_path, server_config, pool))
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "network"

    def test_unconfigured_server_is_error(self, tmp_path) -> None:
        pool = McpPool(servers={})
        ctx = HandlerContext(local_path=str(tmp_path), control_id="MCP-01", mcp_pool=pool)
        try:
            result = mcp_handler({"server": "nope", "tool": "t", "args": {}}, ctx)
        finally:
            pool.teardown_all()
        assert result.status == HandlerResultStatus.ERROR


# ---------------------------------------------------------------------------
# Orchestrator: an ERROR step never concludes the control
# ---------------------------------------------------------------------------


def _verify(tmp_path, *invocations: HandlerInvocation, stop_on_llm: bool = True):
    spec = ControlSpec(
        control_id="ER-01",
        level=1,
        domain="ER",
        name="Errors",
        description="Errors",
        metadata={"handler_invocations": list(invocations)},
    )
    ctx = CheckContext(owner="o", repo="r", local_path=str(tmp_path), default_branch="main", control_id="ER-01")
    return SieveOrchestrator(stop_on_llm=stop_on_llm).verify(spec, ctx)


def _register(name: str, status: HandlerResultStatus, message: str, error_class=None, ceiling=("pass", "fail")):
    calls = {"n": 0}

    def fn(config, context):
        calls["n"] += 1
        return HandlerResult(status=status, message=message, error_class=error_class)

    get_sieve_handler_registry().register(name, "deterministic", fn, ceiling=set(ceiling))
    return calls


class TestErrorContinuation:
    def test_error_then_nothing_concludes_ends_error_with_first_cause(self, tmp_path) -> None:
        _register("er_auth_041", HandlerResultStatus.ERROR, "HTTP 403 reading settings", "auth")
        _register("er_rate_041", HandlerResultStatus.ERROR, "HTTP 429", "rate_limit")
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="er_auth_041"),
            HandlerInvocation(handler="er_rate_041"),
            HandlerInvocation(handler="manual", steps=["Check by hand"]),
        )
        assert result.status == "ERROR"
        assert result.error == {"class": "auth", "cause": "HTTP 403 reading settings"}
        assert result.error_class == "auth"
        assert result.resolving_pass_index == 0
        assert result.concluded_by == "er_auth_041"
        assert [a.result.outcome.value for a in result.pass_history] == ["error", "error", "inconclusive"]
        assert result.to_legacy_dict()["error"] == result.error

    def test_later_conclusive_step_wins_and_error_stays_in_history(self, tmp_path) -> None:
        later = _register("er_fail_041", HandlerResultStatus.FAIL, "setting disabled")
        _register("er_first_041", HandlerResultStatus.ERROR, "timed out", "timeout")
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="er_first_041"),
            HandlerInvocation(handler="er_fail_041"),
        )
        assert later["n"] == 1
        assert result.status == "FAIL"
        assert result.concluded_by == "er_fail_041"
        assert result.error is None
        assert result.pass_history[0].result.outcome.value == "error"
        assert result.pass_history[0].result.message == "timed out"

    def test_error_not_concluded_as_fail_by_evidence_only_step(self, tmp_path) -> None:
        _register("er_net_041", HandlerResultStatus.ERROR, "unreachable", "unavailable")
        _register("er_fail_evidence_041", HandlerResultStatus.FAIL, "weak signal", ceiling=())
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="er_net_041"),
            HandlerInvocation(handler="er_fail_evidence_041"),
        )
        assert result.status == "ERROR"
        assert result.error["class"] == "unavailable"

    def test_error_on_last_step_ends_error(self, tmp_path) -> None:
        _register("er_last_041", HandlerResultStatus.ERROR, "boom")
        result = _verify(
            tmp_path, HandlerInvocation(handler="manual", steps=["x"]), HandlerInvocation(handler="er_last_041")
        )
        assert result.status == "ERROR"
        assert result.error == {"class": "evaluation", "cause": "boom"}

    def test_error_takes_precedence_over_llm_consultation(self, tmp_path) -> None:
        (tmp_path / "README.md").write_text("docs\n")
        _register("er_pre_llm_041", HandlerResultStatus.ERROR, "HTTP 401", "auth")
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="er_pre_llm_041"),
            HandlerInvocation(handler="llm_eval", prompt="Is this documented?", files_to_include=["README.md"]),
            HandlerInvocation(handler="manual", steps=["x"]),
        )
        assert result.status == "ERROR"
        assert result.pending is None
        assert result.error["class"] == "auth"

    def test_without_error_llm_consultation_still_pends(self, tmp_path) -> None:
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="llm_eval", prompt="Is this documented?"),
            HandlerInvocation(handler="manual", steps=["x"]),
        )
        assert result.status == "PENDING"
        assert result.pending == {"kind": "llm_judgment"}

    def test_crashing_handler_is_error_and_later_steps_run(self, tmp_path) -> None:
        def boom(config, context):
            raise RuntimeError("bug")

        get_sieve_handler_registry().register("er_crash_041", "deterministic", boom, ceiling={"pass", "fail"})
        later = _register("er_after_crash_041", HandlerResultStatus.INCONCLUSIVE, "nothing")
        result = _verify(
            tmp_path, HandlerInvocation(handler="er_crash_041"), HandlerInvocation(handler="er_after_crash_041")
        )
        assert later["n"] == 1
        assert result.status == "ERROR"
        assert result.error["class"] == "crashed"
