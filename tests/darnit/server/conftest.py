"""Scratch git repositories for remediation git safety tests (feature 043, quickstart.md V3).

- ``r_dirty``: a modified tracked file, an untracked ``.env``, and one stash.
- ``r_detached``: HEAD detached at the first commit.
- ``r_merging``: a conflicting merge left unresolved (``MERGE_HEAD`` present).
- ``r_foreign_branch``: ``fix/compliance`` exists with a commit lacking the
  ``Darnit-Remediation-Run:`` trailer; ``main`` is checked out.
- ``bare_remote``: a bare repository; ``attach(repo)`` wires it as ``origin``.

Every repository is under ``tmp_path``. Git runs with the user's global and
system configuration disabled, and each repository's local configuration sets
an identity, disables signing, and points hooks at its own empty hooks
directory, so git commands run later by product code behave the same.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.conftest_helpers import assert_unchanged, snapshot

__all__ = [
    "BareRemote",
    "DetachedRepo",
    "DirtyRepo",
    "ForeignBranchRepo",
    "MergingRepo",
    "assert_unchanged",
    "git",
    "snapshot",
]

REMEDIATION_BRANCH = "fix/compliance"
ENV_CONTENT = "API_TOKEN=fake-token-not-a-secret\nDATABASE_URL=postgres://user:pass@localhost/db\n"
_ISOLATED_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in ``repo`` without the user's global or system configuration."""
    return subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env={**os.environ, **_ISOLATED_ENV},
    )


def _rev(repo: Path, ref: str = "HEAD") -> str:
    return git(repo, "rev-parse", ref).stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    _write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return _rev(repo)


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True)
    git(root, "init", "-q")
    for key, value in (
        ("user.name", "Test User"),
        ("user.email", "test@example.com"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
        ("core.hooksPath", ".git/hooks"),
    ):
        git(root, "config", "--local", key, value)
    _commit(
        root,
        "init",
        {
            "README.md": "# scratch\n",
            "CHANGELOG.md": "# Changelog\n",
            "src/app.py": "print('hello')\n",
        },
    )
    return root


@dataclass(frozen=True)
class DirtyRepo:
    path: Path
    head: str
    modified: Path
    modified_content: str
    env: Path
    stash_list: str


@dataclass(frozen=True)
class DetachedRepo:
    path: Path
    head: str


@dataclass(frozen=True)
class MergingRepo:
    path: Path
    head: str
    merge_head: str
    conflicted: Path


@dataclass(frozen=True)
class ForeignBranchRepo:
    path: Path
    head: str
    branch: str
    branch_head: str
    foreign_message: str


@dataclass(frozen=True)
class BareRemote:
    path: Path

    def attach(self, repo: Path, *, push: str | None = "main") -> None:
        """Add this remote as ``origin`` of ``repo`` and, unless ``push`` is None, push that branch."""
        git(repo, "remote", "add", "origin", str(self.path))
        if push:
            git(repo, "push", "-q", "origin", f"{push}:refs/heads/{push}")

    def branches(self) -> list[str]:
        out = git(self.path, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
        return sorted(out.split())


@pytest.fixture
def r_dirty(tmp_path: Path) -> DirtyRepo:
    repo = _init_repo(tmp_path / "R-dirty")
    _commit(repo, "add docs", {"docs/guide.md": "# Guide\n"})
    _write(repo, {"CHANGELOG.md": "# Changelog\n\n- stashed work in progress\n"})
    git(repo, "stash", "push", "-q", "-m", "user work in progress")
    modified_content = "# scratch\n\nLocal edit the user has not committed.\n"
    _write(repo, {"README.md": modified_content, ".env": ENV_CONTENT})
    return DirtyRepo(
        path=repo,
        head=_rev(repo),
        modified=repo / "README.md",
        modified_content=modified_content,
        env=repo / ".env",
        stash_list=git(repo, "stash", "list").stdout,
    )


@pytest.fixture
def r_detached(tmp_path: Path) -> DetachedRepo:
    repo = _init_repo(tmp_path / "R-detached")
    first = _rev(repo)
    _commit(repo, "second", {"docs/guide.md": "# Guide\n"})
    git(repo, "checkout", "-q", "--detach", first)
    return DetachedRepo(path=repo, head=first)


@pytest.fixture
def r_merging(tmp_path: Path) -> MergingRepo:
    repo = _init_repo(tmp_path / "R-merging")
    git(repo, "checkout", "-q", "-b", "topic")
    merge_head = _commit(repo, "topic edit", {"src/app.py": "print('topic')\n"})
    git(repo, "checkout", "-q", "main")
    head = _commit(repo, "main edit", {"src/app.py": "print('main')\n"})
    result = git(repo, "merge", "--no-edit", "topic", check=False)
    assert result.returncode != 0, "the merge was expected to conflict"
    return MergingRepo(path=repo, head=head, merge_head=merge_head, conflicted=repo / "src/app.py")


@pytest.fixture
def r_foreign_branch(tmp_path: Path) -> ForeignBranchRepo:
    repo = _init_repo(tmp_path / "R-foreign-branch")
    head = _rev(repo)
    git(repo, "checkout", "-q", "-b", REMEDIATION_BRANCH)
    message = "Someone else's work on this branch"
    branch_head = _commit(repo, message, {"NOTES.md": "Not darnit's.\n"})
    git(repo, "checkout", "-q", "main")
    return ForeignBranchRepo(
        path=repo, head=head, branch=REMEDIATION_BRANCH, branch_head=branch_head, foreign_message=message
    )


@pytest.fixture
def bare_remote(tmp_path: Path) -> BareRemote:
    path = tmp_path / "remote.git"
    path.mkdir()
    git(path, "init", "-q", "--bare")
    return BareRemote(path=path)
