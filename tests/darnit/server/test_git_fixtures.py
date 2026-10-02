"""The scratch git repositories are in the state the feature 043 git safety tests rely on."""

from __future__ import annotations

from .conftest import (
    ENV_CONTENT,
    BareRemote,
    DetachedRepo,
    DirtyRepo,
    ForeignBranchRepo,
    MergingRepo,
    git,
    snapshot,
)


def test_r_dirty_state(r_dirty: DirtyRepo) -> None:
    status = git(r_dirty.path, "status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    assert sorted(status) == [" M README.md", "?? .env"]
    assert r_dirty.modified.read_text(encoding="utf-8") == r_dirty.modified_content
    assert r_dirty.env.read_text(encoding="utf-8") == ENV_CONTENT
    stashes = r_dirty.stash_list.splitlines()
    assert len(stashes) == 1 and "user work in progress" in stashes[0]
    assert git(r_dirty.path, "stash", "list").stdout == r_dirty.stash_list
    assert git(r_dirty.path, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"


def test_r_dirty_snapshot_detects_changes(r_dirty: DirtyRepo) -> None:
    before = snapshot(r_dirty.path)
    assert ".env" in before and "README.md" in before
    r_dirty.env.write_text("changed\n", encoding="utf-8")
    assert snapshot(r_dirty.path)[".env"] != before[".env"]


def test_r_detached_state(r_detached: DetachedRepo) -> None:
    assert git(r_detached.path, "symbolic-ref", "-q", "HEAD", check=False).returncode != 0
    assert git(r_detached.path, "rev-parse", "HEAD").stdout.strip() == r_detached.head
    assert git(r_detached.path, "status", "--porcelain").stdout == ""


def test_r_merging_state(r_merging: MergingRepo) -> None:
    git_dir = r_merging.path / git(r_merging.path, "rev-parse", "--git-dir").stdout.strip()
    assert (git_dir / "MERGE_HEAD").read_text().strip() == r_merging.merge_head
    status = git(r_merging.path, "status", "--porcelain").stdout.splitlines()
    assert status == ["UU src/app.py"]
    assert "<<<<<<<" in r_merging.conflicted.read_text(encoding="utf-8")


def test_r_foreign_branch_state(r_foreign_branch: ForeignBranchRepo) -> None:
    repo = r_foreign_branch.path
    assert git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip() == "main"
    assert git(repo, "rev-parse", r_foreign_branch.branch).stdout.strip() == r_foreign_branch.branch_head
    log = git(repo, "log", "--format=%B", f"main..{r_foreign_branch.branch}").stdout
    assert r_foreign_branch.foreign_message in log
    assert "Darnit-Remediation-Run:" not in log
    assert git(repo, "status", "--porcelain").stdout == ""


def test_bare_remote_accepts_push(r_dirty: DirtyRepo, bare_remote: BareRemote) -> None:
    assert git(bare_remote.path, "rev-parse", "--is-bare-repository").stdout.strip() == "true"
    bare_remote.attach(r_dirty.path)
    assert git(r_dirty.path, "remote", "get-url", "origin").stdout.strip() == str(bare_remote.path)
    assert bare_remote.branches() == ["main"]
    assert git(bare_remote.path, "rev-parse", "main").stdout.strip() == r_dirty.head


def test_bare_remote_attaches_without_push(r_foreign_branch: ForeignBranchRepo, bare_remote: BareRemote) -> None:
    bare_remote.attach(r_foreign_branch.path, push=None)
    assert bare_remote.branches() == []
    git(r_foreign_branch.path, "push", "-q", "origin", r_foreign_branch.branch)
    assert bare_remote.branches() == [r_foreign_branch.branch]
