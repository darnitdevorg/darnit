"""Repository-state checks for remediation's version-control steps (feature 043).

framework-design.md section 15.7: before a git step, remediation stops with
nothing changed on a detached HEAD, a merge or rebase in progress, an
existing remediation branch holding a commit beyond its base without the
``Darnit-Remediation-Run`` trailer, or a dirty working tree when switching to
an existing branch. The executor uses :func:`has_uncommitted_changes` and
:func:`is_ignored` before each write (FR-011, FR-014).

Every function here only reads the repository.
"""

from __future__ import annotations

import os
import posixpath
import subprocess
from collections.abc import Iterable
from pathlib import Path

TRAILER_KEY = "Darnit-Remediation-Run"

_IN_PROGRESS = (
    ("MERGE_HEAD", "a merge is in progress"),
    ("rebase-merge", "a rebase is in progress"),
    ("rebase-apply", "a rebase or patch application is in progress"),
    ("CHERRY_PICK_HEAD", "a cherry-pick is in progress"),
    ("REVERT_HEAD", "a revert is in progress"),
)
_REMOTE = "origin"
_FALLBACK_BASES = ("main", "master")
PROTECTED_BRANCHES = ("main", "master")


class GitStateError(RuntimeError):
    """A git command needed to establish the repository's state failed."""


def run_git(repo: str | Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=stdin,
    )


def _checked(repo: str | Path, *args: str) -> str:
    result = run_git(repo, *args)
    if result.returncode != 0:
        raise GitStateError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.returncode}")
    return result.stdout


def is_work_tree(repo: str | Path) -> bool:
    try:
        result = run_git(repo, "rev-parse", "--is-inside-work-tree")
    except (FileNotFoundError, NotADirectoryError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def from_root(repo: str | Path, paths: Iterable[str]) -> list[str]:
    """Repository-root-relative ``paths`` (as ``git status --porcelain`` and ``diff-tree`` print them), relative to ``repo``.

    A path outside ``repo`` (when ``repo`` is a subdirectory) comes back with a leading ``../``.
    """
    prefix = _checked(repo, "rev-parse", "--show-prefix").strip()
    return [posixpath.relpath(path, prefix) if prefix else path for path in paths]


def has_uncommitted_changes(repo: str | Path, path: str) -> bool:
    """True when ``path`` differs from HEAD in the index or working tree, or is untracked."""
    out = _checked(repo, "--literal-pathspecs", "status", "--porcelain", "-z", "--untracked-files=all", "--", path)
    return bool(out.strip("\0"))


def is_ignored(repo: str | Path, path: str) -> bool:
    """True when the repository's ignore rules exclude the untracked ``path``."""
    result = run_git(repo, "check-ignore", "-q", "--", path)
    if result.returncode in (0, 1):
        return result.returncode == 0
    raise GitStateError(f"git check-ignore failed for {path}: {result.stderr.strip() or result.returncode}")


def has_tracked_changes(repo: str | Path) -> bool:
    """True when a tracked file is modified, staged, or deleted. Untracked files do not count."""
    return bool(_checked(repo, "status", "--porcelain", "-z", "--untracked-files=no").strip("\0"))


def current_branch(repo: str | Path) -> str | None:
    """The checked-out branch, or None on a detached HEAD."""
    result = run_git(repo, "symbolic-ref", "-q", "--short", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def operation_in_progress(repo: str | Path) -> str | None:
    """Why the repository is mid-operation (merge, rebase, ...), or None."""
    args: list[str] = ["rev-parse"]
    for name, _ in _IN_PROGRESS:
        args += ["--git-path", name]
    paths = _checked(repo, *args).splitlines()
    for (_, reason), path in zip(_IN_PROGRESS, paths, strict=True):
        if os.path.lexists(os.path.join(repo, path)):
            return reason
    return None


def resolve_commit(repo: str | Path, ref: str) -> str | None:
    if not ref or ref.startswith("-"):
        return None
    result = run_git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 else None


def branch_exists(repo: str | Path, branch: str) -> bool:
    return resolve_commit(repo, f"refs/heads/{branch}") is not None


def valid_branch_name(repo: str | Path, branch: str) -> bool:
    return not branch.startswith("-") and run_git(repo, "check-ref-format", "--branch", branch).returncode == 0


def resolve_base(
    repo: str | Path, branch: str, base_branch: str | None = None, *, current_first: bool = True
) -> str | None:
    """The ref ``branch`` is based on.

    ``base_branch`` when given; else (with ``current_first``) the current
    branch when it is not ``branch``; else the remote's default branch
    (``origin/HEAD``), then ``origin/main``, ``origin/master``, ``main``,
    ``master``.
    """
    if base_branch:
        return base_branch if resolve_commit(repo, base_branch) else None
    current = current_branch(repo) if current_first else None
    if current and current != branch:
        return current
    result = run_git(repo, "symbolic-ref", "-q", "--short", f"refs/remotes/{_REMOTE}/HEAD")
    candidates = [result.stdout.strip()] if result.returncode == 0 and result.stdout.strip() else []
    candidates += [f"{_REMOTE}/{name}" for name in _FALLBACK_BASES] + list(_FALLBACK_BASES)
    for candidate in candidates:
        if candidate != branch and resolve_commit(repo, candidate):
            return candidate
    return None


def base_branch_name(base: str) -> str:
    """The branch name a pull request targets for ``base`` (``origin/main`` -> ``main``)."""
    prefix = f"{_REMOTE}/"
    return base[len(prefix) :] if base.startswith(prefix) else base


def merge_base(repo: str | Path, base: str, branch: str) -> str | None:
    """The commit where ``branch`` diverged from ``base``, or None when either cannot be resolved."""
    if resolve_commit(repo, base) is None or resolve_commit(repo, f"refs/heads/{branch}") is None:
        return None
    result = run_git(repo, "merge-base", base, f"refs/heads/{branch}")
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def holds_commit(repo: str | Path, tip: str, commit: str) -> bool:
    """True when ``tip`` contains ``commit``, or a rebased copy of every change of it not on ``tip``.

    A rebased copy is a commit on ``tip`` with the same patch (``git cherry``).
    """
    if resolve_commit(repo, commit) is None:
        return False
    result = run_git(repo, "cherry", tip, commit)
    return result.returncode == 0 and all(line.startswith("-") for line in result.stdout.splitlines() if line.strip())


def foreign_commits(repo: str | Path, base: str, branch: str) -> list[str]:
    """Commits on ``branch`` beyond ``base`` whose message lacks the ``Darnit-Remediation-Run`` trailer."""
    out = _checked(
        repo,
        "log",
        "-z",
        f"--format=%H%x01%(trailers:key={TRAILER_KEY},valueonly)",
        f"{base}..refs/heads/{branch}",
        "--",
    )
    foreign = []
    for record in filter(None, (r.strip("\n") for r in out.split("\0"))):
        sha, _, values = record.partition("\x01")
        if not values.strip():
            foreign.append(sha)
    return foreign


def _branch_refusal(repo: str, current: str, branch_name: str, base_branch: str | None) -> str | None:
    if not valid_branch_name(repo, branch_name):
        return f"'{branch_name}' is not a valid branch name"
    if not branch_exists(repo, branch_name):
        if base_branch and resolve_commit(repo, base_branch) != resolve_commit(repo, "HEAD"):
            return (
                f"a new branch is created from HEAD, and base branch '{base_branch}' is not HEAD; "
                f"check out '{base_branch}' first"
            )
        return None
    base = resolve_base(repo, branch_name, base_branch)
    if base is None:
        return f"cannot determine the base of branch '{branch_name}'; pass base_branch"
    foreign = foreign_commits(repo, base, branch_name)
    if foreign:
        listed = ", ".join(sha[:12] for sha in foreign)
        return (
            f"branch '{branch_name}' has {len(foreign)} commit(s) beyond '{base}' without a "
            f"{TRAILER_KEY} trailer ({listed}); it holds work remediation did not make"
        )
    if current != branch_name and has_tracked_changes(repo):
        return (
            f"switching to existing branch '{branch_name}' needs a clean working tree, and there are "
            "uncommitted changes; commit them or choose a new branch name (darnit does not stash)"
        )
    return None


def _pull_request_refusal(repo: str, current: str, branch_name: str | None, base_branch: str | None) -> str | None:
    """Why a pull request from the remediation branch would be refused after the commit, or None."""
    head = branch_name or current
    if head in PROTECTED_BRANCHES:
        return f"a pull request cannot be opened from '{head}'; pass a remediation branch name"
    base = resolve_base(repo, head, base_branch, current_first=False)
    if base is None:
        return f"cannot determine the pull request base for branch '{head}'; pass base_branch"
    if head == base_branch_name(base):
        return f"a pull request cannot be opened from '{head}' into itself; pass a remediation branch name"
    start = branch_name if branch_name and branch_exists(repo, branch_name) else current
    foreign = foreign_commits(repo, base, start)
    if foreign:
        listed = ", ".join(sha[:12] for sha in foreign)
        return (
            f"'{start}' has {len(foreign)} commit(s) not on the pull request base '{base}' without a "
            f"{TRAILER_KEY} trailer ({listed}); a pull request would carry work remediation did not make. "
            f"Push them, or start from a branch based on '{base}'"
        )
    return None


def check_repository_state(
    local_path: str | Path,
    branch_name: str | None = None,
    base_branch: str | None = None,
    *,
    pull_request: bool = False,
) -> str | None:
    """Why a remediation git step must not run here, or None when it may.

    Refuses a checkout that is not a git work tree, a merge, rebase,
    cherry-pick or revert in progress, and a detached HEAD. With
    ``branch_name``: refuses an invalid name; for an existing branch, a commit
    beyond its base (``base_branch``, default the current branch) without the
    ``Darnit-Remediation-Run`` trailer, and tracked uncommitted changes when
    switching to it; for a new branch, a ``base_branch`` other than HEAD,
    because a new branch is created from HEAD. With ``pull_request``: refuses
    a pull request head of ``main``, ``master``, or the pull request base
    branch itself, an undeterminable pull
    request base, and a commit without the trailer that the remediation
    branch would start from and that is not on the pull request base, which
    the pull request tool would refuse after the commit. Changes nothing.
    """
    repo = str(local_path)
    if not is_work_tree(repo):
        return "not a git work tree"
    try:
        in_progress = operation_in_progress(repo)
        if in_progress:
            return f"{in_progress}; finish or abort it first"
        current = current_branch(repo)
        if current is None:
            return "HEAD is detached; check out a branch first"
        if branch_name is not None:
            refusal = _branch_refusal(repo, current, branch_name, base_branch)
            if refusal:
                return refusal
        if pull_request:
            return _pull_request_refusal(repo, current, branch_name, base_branch)
    except (GitStateError, OSError) as e:
        return f"cannot read the repository state: {e}"
    return None


__all__ = [
    "PROTECTED_BRANCHES",
    "TRAILER_KEY",
    "GitStateError",
    "base_branch_name",
    "branch_exists",
    "check_repository_state",
    "current_branch",
    "foreign_commits",
    "from_root",
    "has_tracked_changes",
    "has_uncommitted_changes",
    "holds_commit",
    "is_ignored",
    "is_work_tree",
    "merge_base",
    "operation_in_progress",
    "resolve_base",
    "resolve_commit",
    "run_git",
    "valid_branch_name",
]
