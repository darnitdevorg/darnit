"""Commit and PR steps are gated on outcomes, and the pending-context guard fails closed (feature 043, US4).

framework-design.md 15.4: every downstream decision is derived from the
per-control outcomes, never from symbols or words in output text (FR-019);
if the check for unconfirmed project context cannot complete, remediation
does not run and the error is returned (FR-020).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.config import context_storage
from darnit.config.operator.schema import RemediationSettings
from darnit.remediation import git_state
from darnit.remediation.plan import ErrorInfo, FileChange, RemediationOutcome, RemediationRun
from darnit.server.tools import git_operations
from darnit_baseline import tools
from darnit_baseline.remediation import orchestrator

RUN_ID = "01K6H8Z3Q4R5S6T7V8W9X0Y1Z2"


def _run(*outcomes: RemediationOutcome) -> RemediationRun:
    return RemediationRun(
        run_id=RUN_ID,
        repository="github.com/o/r",
        mode="apply",
        policy=RemediationSettings(),
        operator_config_digest=None,
        outcomes=list(outcomes),
    )


CHANGED = RemediationOutcome(
    control_id="C-1",
    kind="changed_not_verified",
    file_changes=[FileChange(path="SECURITY.md", action="create", content="# Security\n")],
    error=ErrorInfo(error_class="network", cause="re-check lookup failed"),
)
UNCHANGED = RemediationOutcome(
    control_id="C-2",
    kind="unchanged",
    file_changes=[FileChange(path="SECURITY.md", action="none", reason="already_exists")],
    reason="already_exists",
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


@pytest.fixture
def git_steps(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        git_operations, "commit_remediation_changes_impl", lambda **kw: calls.append(("commit", kw)) or "Error"
    )
    monkeypatch.setattr(git_operations, "create_remediation_pr_impl", lambda **kw: calls.append(("pr", kw)) or "Error")
    return calls


@pytest.fixture
def no_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_storage, "get_pending_context", lambda **_k: [])
    monkeypatch.setattr(git_state, "check_repository_state", lambda *_a, **_k: None)


def _report(monkeypatch: pytest.MonkeyPatch, markdown: str, run: RemediationRun | None) -> list[dict]:
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return orchestrator.RemediationReport(markdown=markdown, run=run)

    monkeypatch.setattr(orchestrator, "run_remediation", fake)
    return calls


def _apply(repo: Path) -> str:
    return tools.remediate_audit_findings(
        local_path=str(repo), owner="o", repo="r", dry_run=False, auto_commit=True, create_pr=True
    )


@pytest.mark.unit
@pytest.mark.usefixtures("no_pending")
def test_changed_files_commit_and_open_a_pr_whatever_the_text_says(
    repo: Path, monkeypatch: pytest.MonkeyPatch, git_steps: list
) -> None:
    calls = _report(monkeypatch, "\u274c Error \u26a0\ufe0f failed", _run(CHANGED, UNCHANGED))

    _apply(repo)

    assert [name for name, _ in git_steps] == ["commit", "pr"]
    assert all(kw["run_id"] == calls[0]["run_id"] for _, kw in git_steps)


@pytest.mark.unit
@pytest.mark.usefixtures("no_pending")
def test_no_changed_files_takes_no_git_step_whatever_the_text_says(
    repo: Path, monkeypatch: pytest.MonkeyPatch, git_steps: list
) -> None:
    _report(monkeypatch, "\u2705 Applied (1 remediations)", _run(UNCHANGED))

    _apply(repo)

    assert git_steps == []


@pytest.mark.unit
@pytest.mark.usefixtures("no_pending")
def test_no_run_record_takes_no_git_step(repo: Path, monkeypatch: pytest.MonkeyPatch, git_steps: list) -> None:
    _report(monkeypatch, "Applied", None)

    _apply(repo)

    assert git_steps == []


@pytest.mark.unit
def test_pending_context_check_that_raises_stops_remediation(
    repo: Path, monkeypatch: pytest.MonkeyPatch, git_steps: list
) -> None:
    def broken(**_k):
        raise OSError("context store unreadable")

    monkeypatch.setattr(context_storage, "get_pending_context", broken)
    calls = _report(monkeypatch, "Applied", _run(CHANGED))

    output = _apply(repo)

    assert calls == [], "remediation did not run"
    assert git_steps == []
    assert "context store unreadable" in output
    assert output.startswith("Error")


@pytest.mark.unit
def test_pending_context_check_that_raises_stops_a_preview_too(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(**_k):
        raise ValueError("bad definitions")

    monkeypatch.setattr(context_storage, "get_pending_context", broken)
    calls = _report(monkeypatch, "Preview", None)

    output = tools.remediate_audit_findings(local_path=str(repo), owner="o", repo="r")

    assert calls == []
    assert "bad definitions" in output
