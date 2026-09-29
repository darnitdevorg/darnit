"""ActionPlan answers submitted over MCP are used in-run only (feature 042, FR-002, research R12)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from darnit.core.action_plan import FeedbackQuestionModel, HarnessState
from darnit.server.tools.harness_loop import run_next_action_tool, submit_action_result_tool
from darnit.trust.confirmations import load_confirmations, load_context_bases

from .conftest import assert_unchanged, snapshot, write_operator_config


def _collect_state(local_path: Path) -> dict:
    return HarnessState(
        local_path=str(local_path),
        owner="example-org",
        repo="project",
        audit_results=[{"id": "A", "status": "WARN", "details": "", "level": 1}],
        feedback_questions=[
            FeedbackQuestionModel(
                control_id="A",
                context_key="security_contact",
                question="Who is the security contact?",
                answered=False,
            ),
        ],
    ).model_dump(mode="json")


@pytest.mark.unit
@pytest.mark.parametrize("with_project_dir", [False, True])
def test_collect_context_submission_writes_nothing(tmp_path: Path, with_project_dir: bool) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    if with_project_dir:
        (repo / ".project").mkdir()
        (repo / ".project" / "project.yaml").write_text("name: test-repo\n", encoding="utf-8")
    write_operator_config(tmp_path / "operator.toml", trusted=["github.com/example-org/project"])
    before = snapshot(repo)
    state = _collect_state(repo)
    plan = asyncio.run(run_next_action_tool(state))
    assert plan["step"]["integration"] == "collect_context"

    new_state = asyncio.run(
        submit_action_result_tool(state, plan["step"]["id"], {"answers": {"security_contact": "sec@example.net"}})
    )

    assert new_state["context_values"] == {"security_contact": "sec@example.net"}
    assert_unchanged(repo, before)
    assert load_confirmations() == []
    assert load_context_bases() == []


@pytest.mark.unit
def test_tool_description_does_not_promise_persistence() -> None:
    from darnit.server.tools import harness_loop

    assert not hasattr(harness_loop, "_persist_new_asserted_values")


def _cli_state(repo: Path, target: str | None):
    from darnit.agent.state import AuditState, FeedbackQuestion

    state = AuditState(local_path=str(repo), target=target, framework_name="openssf-baseline")
    state.feedback_questions = [
        FeedbackQuestion(control_id="A", context_key="governance_model", question="Governance model?")
    ]
    return state


@pytest.mark.unit
def test_cli_answers_typed_by_a_person_are_confirmations(tmp_path: Path) -> None:
    import yaml

    from darnit.agent.graph import collect_context
    from darnit.config.operator.schema import OperatorConfig

    repo = tmp_path / "repo"
    repo.mkdir()
    target = "github.com/example-org/project"
    operator = OperatorConfig.model_validate({"schema_version": 1, "trust": {"repos": [target]}})

    state = collect_context(_cli_state(repo, target), {"governance_model": "bdfl"}, operator=operator)

    assert state.context_values == {"governance_model": "bdfl"}
    data = yaml.safe_load((repo / ".project" / "darnit.yaml").read_text(encoding="utf-8"))
    assert data["context"] == {"governance_model": "bdfl"}
    assert data["confirmations"]["governance_model"]["basis"] == {
        "value": "bdfl",
        "origin": {"kind": "answer", "method": "darnit run"},
    }
    assert not (repo / ".project" / "project.yaml").exists()


@pytest.mark.unit
def test_cli_answers_without_a_named_repository_stay_in_run(tmp_path: Path) -> None:
    from darnit.agent.graph import collect_context
    from darnit.config.operator.schema import OperatorConfig

    repo = tmp_path / "repo"
    repo.mkdir()
    before = snapshot(repo)

    state = collect_context(
        _cli_state(repo, None),
        {"governance_model": "bdfl"},
        operator=OperatorConfig.model_validate({"schema_version": 1}),
    )

    assert state.context_values == {"governance_model": "bdfl"}
    assert_unchanged(repo, before)
    assert load_confirmations() == []
