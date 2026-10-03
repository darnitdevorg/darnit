"""``remediate_audit_findings`` checks the repository before any git step and threads one run id (feature 043, T038).

framework-design.md 15.7 "Refused states": when ``branch_name``,
``auto_commit`` or ``create_pr`` is requested, the repository state is
checked before any remediation is applied, and an unsafe state stops the
call with nothing changed (FR-013, US2 scenario 3). The run id of the apply
is the one the branch, commit and PR steps use.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path

import pytest

from darnit.config import context_storage
from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
    RemediationConfig,
)
from darnit.core import audit_cache
from darnit.remediation import manifest
from darnit.server.tools import git_operations
from darnit_baseline import tools
from darnit_baseline.remediation import orchestrator
from tests.conftest_helpers import assert_unchanged, snapshot
from tests.darnit.server import conftest as git_fixtures
from tests.darnit.server.conftest import REMEDIATION_BRANCH, git

r_dirty = git_fixtures.r_dirty
r_detached = git_fixtures.r_detached
r_merging = git_fixtures.r_merging
r_foreign_branch = git_fixtures.r_foreign_branch
bare_remote = git_fixtures.bare_remote

OWNER, REPO = "example-org", "example"
IDENTITY = f"github.com/{OWNER}/{REPO}"
CONTROL = "OSPS-VM-02.01"
FRAMEWORK = FrameworkConfig(
    metadata=FrameworkMetadata(name="openssf-baseline", display_name="Test", version="1.0"),
    controls={
        CONTROL: ControlConfig(
            name="SecurityPolicy",
            description="Security policy",
            level=1,
            passes=[HandlerInvocation(handler="file_exists", files=["SECURITY.md"], existence=True)],
            remediation=RemediationConfig(
                handlers=[HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Security\n")]
            ),
        )
    },
)


@pytest.fixture(autouse=True)
def synthetic_framework(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_get_framework_config", lambda: FRAMEWORK)
    monkeypatch.setattr(audit_cache, "read_audit_cache", lambda *_a, **_k: {"results": [{"id": CONTROL, "status": "FAIL"}]})
    monkeypatch.setattr(context_storage, "get_pending_context", lambda **_k: [])


@pytest.fixture(autouse=True)
def gh_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_gh(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return subprocess.CompletedProcess(["gh", *args], 0, stdout="https://example.invalid/pull/1\n", stderr="")

    monkeypatch.setattr(git_operations, "_gh", fake_gh)
    return calls


def _git_state(repo: Path) -> dict[str, str]:
    return {
        "head": git(repo, "rev-parse", "HEAD").stdout,
        "symbolic": git(repo, "symbolic-ref", "-q", "HEAD", check=False).stdout,
        "refs": git(repo, "for-each-ref", "--format=%(refname) %(objectname)").stdout,
        "status": git(repo, "status", "--porcelain", "--untracked-files=all").stdout,
        "stash": git(repo, "stash", "list").stdout,
        "index": git(repo, "ls-files", "--stage").stdout,
    }


def _remediate(repo: Path, **kwargs) -> str:
    return tools.remediate_audit_findings(local_path=str(repo), owner=OWNER, repo=REPO, **kwargs)


def _run_block(output: str) -> dict:
    blocks = re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)
    assert blocks, output
    return json.loads(blocks[-1])


@pytest.mark.integration
@pytest.mark.parametrize("fixture", ["r_detached", "r_merging", "r_foreign_branch"])
def test_unsafe_state_stops_before_any_remediation(fixture: str, request: pytest.FixtureRequest) -> None:
    repo = request.getfixturevalue(fixture).path
    before, state = snapshot(repo), _git_state(repo)

    output = _remediate(repo, dry_run=False, branch_name=REMEDIATION_BRANCH, auto_commit=True, create_pr=True)

    assert "Nothing was changed" in output, output
    assert not (repo / "SECURITY.md").exists()
    assert_unchanged(repo, before)
    assert _git_state(repo) == state
    assert manifest.load_run(IDENTITY) is None


@pytest.mark.integration
@pytest.mark.parametrize("local_branch", [True, False], ids=["local_branch", "main_with_unpushed_commit"])
def test_pull_request_from_history_not_on_the_base_is_refused_before_any_change(
    request: pytest.FixtureRequest, gh_calls: list[list[str]], local_branch: bool
) -> None:
    """framework-design 15.7, scenario "Pull request from history that is not on the base"."""
    dirty = request.getfixturevalue("r_dirty")
    request.getfixturevalue("bare_remote").attach(dirty.path)
    if local_branch:
        git(dirty.path, "checkout", "-q", "-b", "dev")
    (dirty.path / "LOCAL.md").write_text("Local work, not pushed.\n", encoding="utf-8")
    git(dirty.path, "add", "--", "LOCAL.md")
    git(dirty.path, "commit", "-q", "-m", "local work", "--", "LOCAL.md")
    before, state = snapshot(dirty.path), _git_state(dirty.path)

    output = _remediate(dirty.path, dry_run=False, branch_name=REMEDIATION_BRANCH, auto_commit=True, create_pr=True)

    assert output.startswith("Error: cannot run the requested git steps"), output
    assert "origin/main" in output and "Nothing was changed" in output, output
    assert not (dirty.path / "SECURITY.md").exists()
    assert_unchanged(dirty.path, before)
    assert _git_state(dirty.path) == state
    assert manifest.load_run(IDENTITY) is None
    assert gh_calls == []


@pytest.mark.integration
def test_pull_request_from_the_default_branch_itself_is_refused_before_any_change(
    request: pytest.FixtureRequest, gh_calls: list[list[str]]
) -> None:
    """origin/HEAD is develop and develop is checked out: the PR head would be its own base."""
    dirty = request.getfixturevalue("r_dirty")
    git(dirty.path, "branch", "-m", "main", "develop")
    request.getfixturevalue("bare_remote").attach(dirty.path, push="develop")
    git(dirty.path, "remote", "set-head", "origin", "develop")
    before, state = snapshot(dirty.path), _git_state(dirty.path)

    output = _remediate(dirty.path, dry_run=False, auto_commit=True, create_pr=True)

    assert output.startswith("Error: cannot run the requested git steps"), output
    assert "'develop'" in output and "Nothing was changed" in output, output
    assert not (dirty.path / "SECURITY.md").exists()
    assert_unchanged(dirty.path, before)
    assert _git_state(dirty.path) == state
    assert manifest.load_run(IDENTITY) is None
    assert gh_calls == []


@pytest.mark.integration
def test_pull_request_targets_the_base_recorded_with_the_branch(
    request: pytest.FixtureRequest, gh_calls: list[list[str]]
) -> None:
    dirty = request.getfixturevalue("r_dirty")
    request.getfixturevalue("bare_remote").attach(dirty.path)
    run_id = manifest.new_run_id()
    branch = git_operations.create_remediation_branch_impl(
        branch_name=REMEDIATION_BRANCH, local_path=str(dirty.path), run_id=run_id, owner=OWNER, repo=REPO
    )
    assert branch.startswith("Created and switched"), branch
    run = manifest.load_run(IDENTITY, run_id)
    assert (run.base, run.base_commit) == ("origin/main", git(dirty.path, "rev-parse", "origin/main").stdout.strip())
    git(dirty.path, "branch", "-q", "other", "main")
    git(dirty.path, "push", "-q", "origin", "other:refs/heads/other")
    git(dirty.path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/other")
    orchestrator.run_remediation(
        local_path=str(dirty.path), owner=OWNER, repo=REPO, dry_run=False, run_id=run_id
    )
    commit = git_operations.commit_remediation_changes_impl(
        local_path=str(dirty.path), run_id=run_id, owner=OWNER, repo=REPO
    )
    assert commit.startswith("Changes committed successfully"), commit

    pr = git_operations.create_remediation_pr_impl(local_path=str(dirty.path), run_id=run_id, owner=OWNER, repo=REPO)

    assert pr.startswith("Pull request created successfully"), pr
    [create] = gh_calls
    assert create[create.index("--base") + 1] == "main"


@pytest.mark.integration
def test_commit_alone_is_refused_on_a_detached_head(request: pytest.FixtureRequest) -> None:
    repo = request.getfixturevalue("r_detached").path
    before = snapshot(repo)

    output = _remediate(repo, dry_run=False, auto_commit=True)

    assert "detached" in output and "Nothing was changed" in output, output
    assert_unchanged(repo, before)


@pytest.mark.integration
def test_switching_to_an_existing_branch_with_a_dirty_tree_is_refused(request: pytest.FixtureRequest) -> None:
    dirty = request.getfixturevalue("r_dirty")
    git(dirty.path, "branch", REMEDIATION_BRANCH)
    before, state = snapshot(dirty.path), _git_state(dirty.path)

    output = _remediate(dirty.path, dry_run=False, branch_name=REMEDIATION_BRANCH)

    assert "clean working tree" in output and "Nothing was changed" in output, output
    assert_unchanged(dirty.path, before)
    assert _git_state(dirty.path) == state


@pytest.mark.integration
def test_one_run_id_threads_branch_apply_commit_and_pr(
    request: pytest.FixtureRequest, gh_calls: list[list[str]]
) -> None:
    dirty = request.getfixturevalue("r_dirty")
    request.getfixturevalue("bare_remote").attach(dirty.path)

    output = _remediate(dirty.path, dry_run=False, branch_name=REMEDIATION_BRANCH, auto_commit=True, create_pr=True)

    run_id = _run_block(output)["run_id"]
    run = manifest.load_run(IDENTITY, run_id, checkout=dirty.path)
    assert run is not None, output
    assert [f.path for f in run.files] == ["SECURITY.md"]
    assert run.branch == REMEDIATION_BRANCH
    assert run.commit == git(dirty.path, "rev-parse", "HEAD").stdout.strip()
    committed = git(dirty.path, "diff-tree", "-r", "--no-commit-id", "--name-only", "HEAD").stdout.split()
    assert committed == ["SECURITY.md"]
    assert f"Darnit-Remediation-Run: {run_id}" in git(dirty.path, "log", "-1", "--format=%B").stdout
    assert git(dirty.path, "stash", "list").stdout == dirty.stash_list
    assert dirty.env.exists() and dirty.modified.read_text(encoding="utf-8") == dirty.modified_content
    assert [c[:2] for c in gh_calls] == [["pr", "create"]]


@pytest.mark.integration
def test_preview_takes_no_git_step(request: pytest.FixtureRequest) -> None:
    repo = request.getfixturevalue("r_detached").path
    before, state = snapshot(repo), _git_state(repo)

    output = _remediate(repo, branch_name=REMEDIATION_BRANCH, auto_commit=True)

    assert _run_block(output)["mode"] == "preview"
    assert_unchanged(repo, before)
    assert _git_state(repo) == state


@pytest.mark.unit
@pytest.mark.parametrize(
    "tool", [tools.create_remediation_branch, tools.commit_remediation_changes, tools.create_remediation_pr]
)
def test_git_tools_take_run_id(tool) -> None:
    params = inspect.signature(tool).parameters

    assert params["run_id"].default is None
    assert "add_all" not in params
