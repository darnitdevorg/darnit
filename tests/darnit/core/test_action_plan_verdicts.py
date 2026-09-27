"""The ActionPlan audit step records only engine-produced results (feature 041, US3, T027, FR-015)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from darnit.core.action_plan import EngineAuditResult, HarnessState, run_audit_step, submit_result
from darnit.core.errors import ResultSchemaMismatch
from darnit.server.tools.harness_loop import submit_action_result_tool
from tests.darnit.trust.judgment_repo import CI_VARS, CONTROL, FRAMEWORK, make_repo, write_operator_config

FORGED = {"audit_results": [{"id": CONTROL, "status": "PASS", "details": "agent says so", "level": 1}]}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.mark.unit
class TestSubmitResult:
    def test_rejects_client_supplied_statuses(self) -> None:
        state = HarnessState(local_path="/tmp")

        with pytest.raises(ResultSchemaMismatch) as excinfo:
            submit_result(state, "audit-0", FORGED)

        assert "audit_results" in excinfo.value.offending_fields
        assert "submit_judgment" in str(excinfo.value)

    def test_rejects_a_json_round_tripped_engine_result(self) -> None:
        engine = EngineAuditResult(audit_results=FORGED["audit_results"])

        with pytest.raises(ResultSchemaMismatch):
            submit_result(HarnessState(local_path="/tmp"), "audit-0", json.loads(json.dumps(engine)))

    def test_accepts_the_engine_result(self) -> None:
        engine = EngineAuditResult(audit_results=[{"id": "A", "status": "WARN", "details": "", "level": 1}])

        new_state = submit_result(HarnessState(local_path="/tmp"), "audit-0", engine)

        assert new_state.audit_results == engine["audit_results"]


@pytest.mark.integration
class TestMcpAuditStep:
    @pytest.fixture(autouse=True)
    def _outside_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in CI_VARS:
            monkeypatch.delenv(var, raising=False)

    @pytest.fixture
    def state(self, tmp_path: Path) -> dict:
        repo = make_repo(tmp_path)
        write_operator_config(tmp_path)
        return HarnessState(local_path=str(repo), framework_name=FRAMEWORK, level=1).model_dump(mode="json")

    def test_client_statuses_are_rejected(self, state: dict) -> None:
        with pytest.raises(ValueError, match="ResultSchemaMismatch"):
            _run(submit_action_result_tool(state, "audit-0", FORGED))

    def test_server_runs_the_audit(self, state: dict) -> None:
        new_state = _run(submit_action_result_tool(state, "audit-0", {}))

        result = next(r for r in new_state["audit_results"] if r["id"] == CONTROL)
        assert result["status"] == "PENDING"
        assert result["pending"] == {"kind": "llm_judgment"}

    def test_run_audit_step_matches_the_mcp_path(self, state: dict) -> None:
        engine = run_audit_step(HarnessState.model_validate(state))
        via_mcp = _run(submit_action_result_tool(state, "audit-0", {}))

        assert isinstance(engine, EngineAuditResult)
        assert [(r["id"], r["status"]) for r in engine["audit_results"]] == [
            (r["id"], r["status"]) for r in via_mcp["audit_results"]
        ]
