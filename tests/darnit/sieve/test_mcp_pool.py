"""Lifecycle tests for the MCP pool through the sieve orchestrator.

Locks SC-002 (single spawn across N controls; single teardown).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from darnit.config.framework_schema import HandlerInvocation, McpServerConfig
from darnit.core.models import ExecutionContext
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator


def _read_counter(counter_file: Path) -> list[dict[str, Any]]:
    if not counter_file.exists():
        return []
    return [json.loads(line) for line in counter_file.read_text().splitlines() if line]


def _build_control(control_id: str) -> ControlSpec:
    invocation = HandlerInvocation(
        handler="mcp",
        server="mock",
        tool="get_score",
        args={},
        expr="result.score >= 7.0",
    )
    return ControlSpec(
        control_id=control_id,
        level=1,
        domain=None,
        name=f"Mock-{control_id}",
        description="",
        metadata={"handler_invocations": [invocation]},
    )


# ---------------------------------------------------------------------------
# T044: teardown on the success path (single spawn, single teardown)
# ---------------------------------------------------------------------------


def test_teardown_on_success_path(
    tmp_path, mock_mcp_server_command, mcp_counter_file
):
    os.environ["DARNIT_MOCK_MCP_COUNTER_FILE_SRC"] = str(mcp_counter_file)
    server_config = McpServerConfig(
        command=mock_mcp_server_command,
        env={"DARNIT_MOCK_MCP_COUNTER_FILE": "$DARNIT_MOCK_MCP_COUNTER_FILE_SRC"},
    )

    execution_context = ExecutionContext(
        owner="octo",
        repo="hello",
        local_path=str(tmp_path),
        mcp_servers={"mock": server_config},
    )
    controls = [_build_control("CTRL-01"), _build_control("CTRL-02")]

    def _factory(_cid: str) -> CheckContext:
        return CheckContext(
            owner="octo",
            repo="hello",
            local_path=str(tmp_path),
            default_branch="main",
            control_id=_cid,
            execution_context=execution_context,
        )

    orchestrator = SieveOrchestrator(stop_on_llm=False)
    results = [orchestrator.verify(spec, _factory(spec.control_id)) for spec in controls]
    for r in results:
        assert r.status == "PASS", f"{r.control_id}: {r.status} -- {r.message}"
    orchestrator.reset_caches()

    events = _read_counter(mcp_counter_file)
    spawn_events = [e for e in events if e.get("kind") == "spawn"]
    teardown_events = [e for e in events if e.get("kind") == "teardown"]
    assert len(spawn_events) == 1, (
        f"SC-002: expected exactly ONE spawn across {len(controls)} controls, "
        f"got {len(spawn_events)}"
    )
    assert len(teardown_events) == 1, (
        f"expected exactly ONE teardown after reset_caches, got {len(teardown_events)}"
    )
