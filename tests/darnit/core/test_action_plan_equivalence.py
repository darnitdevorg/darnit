"""SC-002 equivalence tests: ActionPlan driving == cmd_run output.

Feature 025 T031. Drives the ActionPlan protocol against the feature-024
fixture through a manual next_action / submit_result loop; asserts the
final observable state (audit_results by control id + status) matches what
`darnit run` produces on the same fixture.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from darnit.agent.state import AuditState
from darnit.core.action_plan import HarnessState, next_action, submit_result


def _copy_minimal_repo(tmp_path: Path) -> Path:
    """Mirror the feature-024 conftest helper without cross-package import."""
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


def _drive_action_plan(state: HarnessState) -> HarnessState:
    """Walk next_action / submit_result executing steps via the same
    audit/collect_context/remediate helpers cmd_run calls internally.
    """
    from darnit.agent.graph import audit, remediate

    while True:
        plan = next_action(state)
        if plan is None:
            break

        integration = plan.step.integration
        if integration == "audit":
            audit_state = state.to_audit_state()
            audit_state = audit(audit_state)
            state = submit_result(
                state,
                plan.step.id,
                {
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
                },
            )

        elif integration == "collect_context":
            # Noninteractive: no answers -- mirrors cmd_run's noninteractive
            # feedback handler behavior.
            answers: dict[str, str] = {}
            state = submit_result(state, plan.step.id, {"answers": answers})
            if not answers:
                # Match cmd_run's "break if nothing answered" behavior.
                break

        elif integration == "remediate":
            audit_state = state.to_audit_state()
            audit_state = remediate(audit_state, dry_run=True)
            state = submit_result(
                state,
                plan.step.id,
                {"remediation_results": audit_state.remediation_results},
            )
            break

    return state


def _run_cmd_run(fixture_path: Path) -> AuditState:
    """Execute cmd_run's exact loop in-process and return the final state."""
    from darnit.agent.feedback import get_feedback_handler
    from darnit.agent.graph import audit, collect_context, remediate, route
    from darnit.agent.state import AuditState

    state = AuditState(local_path=str(fixture_path))
    feedback = get_feedback_handler("noninteractive")
    state = audit(state)
    for _ in range(10):  # MAX_AGENT_ITERATIONS
        if state.error:
            break
        step = route(state)
        if step == "collect_context":
            answers = {
                q.context_key: (feedback.ask(q.control_id, q.question) or "")
                for q in state.feedback_questions
                if not q.answered
            }
            answers = {k: v for k, v in answers.items() if v}
            if not answers:
                break
            state = collect_context(state, answers)
            state = audit(state)
        elif step == "remediate":
            state = remediate(state, dry_run=False)
            break
        else:
            break
    return state


def _results_key(results: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Extract the equality-contract shape: sorted [(control_id, status)]."""
    return sorted((r.get("id", ""), r.get("status", "")) for r in results)


def _feedback_key(questions: list[Any]) -> set[tuple[str, str]]:
    """Feedback question equality: set of (control_id, context_key)."""
    return {(q.control_id, q.context_key) for q in questions}


@pytest.mark.slow
def test_action_plan_equals_cmd_run(tmp_path: Path) -> None:
    """SC-002 + US2 acceptance #1: two paths produce the same final state.

    Drives the same fixture two ways -- (1) via next_action / submit_result
    in a Python loop, (2) via cmd_run's internal loop -- and asserts the
    audit_results (by control_id + status) and feedback_questions (by set
    of (control_id, context_key)) are equal.
    """
    fixture = _copy_minimal_repo(tmp_path)

    # Path 1: ActionPlan protocol driving
    initial_ap = HarnessState(local_path=str(fixture))
    final_ap = _drive_action_plan(initial_ap)

    # Path 2: cmd_run's internal loop
    final_cli = _run_cmd_run(fixture)

    ap_key = _results_key(final_ap.audit_results)
    cli_key = _results_key(final_cli.audit_results)
    assert ap_key == cli_key, (
        f"ActionPlan and cmd_run paths produced different result sets:\n  ActionPlan: {ap_key}\n  cmd_run:    {cli_key}"
    )

    ap_fb = _feedback_key(final_ap.feedback_questions)
    cli_fb = _feedback_key(final_cli.feedback_questions)
    assert ap_fb == cli_fb
