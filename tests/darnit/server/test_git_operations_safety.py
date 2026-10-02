"""Remediation commits contain only remediation's own changes (feature 043, US2, SC-003, quickstart V3).

On ``R-dirty`` (a modified tracked file, an untracked ``.env``, one stash),
remediation creates a branch, writes through the executor, commits, and
opens a pull request against a bare remote. ``gh`` is stubbed; nothing
contacts GitHub.
"""

from __future__ import annotations

import subprocess
from functools import partial
from pathlib import Path

import pytest

from darnit.config.framework_schema import HandlerInvocation, RemediationConfig
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationExecutor
from darnit.remediation.git_state import check_repository_state
from darnit.server.tools import git_operations

from .conftest import ENV_CONTENT, REMEDIATION_BRANCH, BareRemote, DirtyRepo, git

OWNER, REPO = "example-org", "example"
IDENTITY = f"github.com/{OWNER}/{REPO}"
create_branch = partial(git_operations.create_remediation_branch_impl, owner=OWNER, repo=REPO)
commit_changes = partial(git_operations.commit_remediation_changes_impl, owner=OWNER, repo=REPO)
create_pr = partial(git_operations.create_remediation_pr_impl, owner=OWNER, repo=REPO)
PR_URL = "https://example.invalid/pull/1"
REMEDIATION = RemediationConfig(
    handlers=[
        HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Security\n\nReport privately.\n"),
        HandlerInvocation(handler="file_create", path=".github/ISSUE_TEMPLATE/bug.md", content="# Bug\n"),
    ]
)


@pytest.fixture
def gh_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_gh(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return subprocess.CompletedProcess(["gh", *args], 0, stdout=f"{PR_URL}\n", stderr="")

    monkeypatch.setattr(git_operations, "_gh", fake_gh)
    return calls


def _committed_files(repo: Path, ref: str = "HEAD") -> list[str]:
    out = git(repo, "diff-tree", "-r", "--no-commit-id", "--name-only", ref).stdout
    return sorted(out.split())


def _remote_refs(remote: BareRemote) -> dict[str, str]:
    out = git(remote.path, "for-each-ref", "--format=%(refname) %(objectname)").stdout
    return dict(line.split(" ", 1) for line in out.splitlines())


def _remediate(r_dirty: DirtyRepo, run_id: str | None) -> tuple[str, str, str]:
    path = str(r_dirty.path)
    branch = create_branch(branch_name=REMEDIATION_BRANCH, local_path=path, run_id=run_id)
    assert branch.startswith("✅"), branch
    result = RemediationExecutor(owner=OWNER, repo=REPO, local_path=path, run_id=run_id).execute(
        "C-1", REMEDIATION, dry_run=False
    )
    assert result.success and result.changed, result.details
    commit = commit_changes(local_path=path, run_id=result.run_id)
    assert commit.startswith("✅"), commit
    pr = create_pr(local_path=path, run_id=result.run_id)
    assert pr.startswith("✅"), pr
    assert result.run_id is not None
    return result.run_id, commit, pr


@pytest.mark.integration
class TestUnrelatedWorkInProgress:
    """framework-design.md 15.7, scenario "Unrelated work in progress"."""

    @pytest.fixture
    def remediated(self, r_dirty: DirtyRepo, bare_remote: BareRemote, gh_calls: list[list[str]]):
        bare_remote.attach(r_dirty.path)
        remote_before = _remote_refs(bare_remote)
        assert check_repository_state(r_dirty.path, REMEDIATION_BRANCH) is None
        run_id, commit, pr = _remediate(r_dirty, manifest.new_run_id())
        return run_id, commit, pr, remote_before

    def test_commit_files_equal_the_manifest_files(self, r_dirty: DirtyRepo, remediated) -> None:
        run_id, commit, _, _ = remediated
        run = manifest.load_run(IDENTITY, run_id)
        assert run is not None

        manifest_files = sorted(f.path for f in run.files)
        assert manifest_files == [".github/ISSUE_TEMPLATE/bug.md", "SECURITY.md"]
        assert _committed_files(r_dirty.path) == manifest_files
        for path in manifest_files:
            assert path in commit, "the report lists every committed file"

    def test_user_changes_stay_uncommitted_and_byte_identical(self, r_dirty: DirtyRepo, remediated) -> None:
        assert r_dirty.modified.read_text(encoding="utf-8") == r_dirty.modified_content
        assert r_dirty.env.read_text(encoding="utf-8") == ENV_CONTENT
        status = git(r_dirty.path, "status", "--porcelain", "--untracked-files=all").stdout.splitlines()
        assert sorted(status) == [" M README.md", "?? .env"]
        tracked = git(r_dirty.path, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()
        assert ".env" not in tracked
        assert git(r_dirty.path, "show", "HEAD:README.md").stdout == "# scratch\n"

    def test_stash_list_unchanged(self, r_dirty: DirtyRepo, remediated) -> None:
        assert git(r_dirty.path, "stash", "list").stdout == r_dirty.stash_list

    def test_commit_carries_the_run_trailer(self, r_dirty: DirtyRepo, remediated) -> None:
        run_id = remediated[0]
        message = git(r_dirty.path, "log", "-1", "--format=%B").stdout
        trailers = subprocess.run(
            ["git", "interpret-trailers", "--parse"], input=message, capture_output=True, text=True, check=True
        ).stdout
        assert f"Darnit-Remediation-Run: {run_id}" in trailers.splitlines()

    def test_only_the_remediation_branch_was_pushed(
        self, r_dirty: DirtyRepo, bare_remote: BareRemote, remediated, gh_calls: list[list[str]]
    ) -> None:
        remote_before = remediated[3]
        after = _remote_refs(bare_remote)

        assert set(after) - set(remote_before) == {f"refs/heads/{REMEDIATION_BRANCH}"}
        assert {k: after[k] for k in remote_before} == remote_before
        assert after[f"refs/heads/{REMEDIATION_BRANCH}"] == git(r_dirty.path, "rev-parse", "HEAD").stdout.strip()
        assert [c[:2] for c in gh_calls] == [["pr", "create"]]
        assert gh_calls[0][gh_calls[0].index("--head") + 1] == REMEDIATION_BRANCH

    def test_branch_and_commit_recorded_in_the_manifest(self, r_dirty: DirtyRepo, remediated) -> None:
        run = manifest.load_run(IDENTITY, remediated[0])
        assert run is not None
        assert run.branch == REMEDIATION_BRANCH
        assert run.commit == git(r_dirty.path, "rev-parse", "HEAD").stdout.strip()

    def test_branch_was_created_from_head(self, r_dirty: DirtyRepo, remediated) -> None:
        assert git(r_dirty.path, "rev-parse", "HEAD^").stdout.strip() == r_dirty.head
        assert git(r_dirty.path, "symbolic-ref", "--short", "HEAD").stdout.strip() == REMEDIATION_BRANCH


@pytest.mark.integration
def test_default_run_is_the_latest(r_dirty: DirtyRepo, bare_remote: BareRemote, gh_calls: list[list[str]]) -> None:
    """``run_id=None`` everywhere: the commit tool records the branch the run was committed on."""
    bare_remote.attach(r_dirty.path)

    run_id, _, _ = _remediate(r_dirty, None)

    run = manifest.load_run(IDENTITY)
    assert run is not None and run.run_id == run_id
    assert run.branch == REMEDIATION_BRANCH
    assert _committed_files(r_dirty.path) == sorted(f.path for f in run.files)
    assert git(r_dirty.path, "stash", "list").stdout == r_dirty.stash_list
    assert f"refs/heads/{REMEDIATION_BRANCH}" in _remote_refs(bare_remote)


@pytest.mark.integration
def test_pr_diffs_against_the_branch_base(
    tmp_path: Path, bare_remote: BareRemote, gh_calls: list[list[str]], r_dirty: DirtyRepo
) -> None:
    """A repository whose default branch is not ``main``: the PR targets and diffs against that base."""
    repo = r_dirty.path
    git(repo, "branch", "-m", "main", "develop")
    bare_remote.attach(repo, push="develop")
    git(repo, "remote", "set-head", "origin", "develop")

    _, _, pr = _remediate(r_dirty, manifest.new_run_id())

    assert "**Files changed:** 2" in pr
    create = gh_calls[0]
    assert create[create.index("--base") + 1] == "develop"
