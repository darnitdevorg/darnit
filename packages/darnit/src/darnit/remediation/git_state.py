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

import functools
import os
import posixpath
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

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


@functools.lru_cache(maxsize=1)
def _auditor_gpg_program() -> str:
    """Return the auditor's configured gpg.program, falling back to 'gpg'."""
    for scope in ("--global", "--system"):
        try:
            res = subprocess.run(
                ["git", "config", "--includes", scope, "--get", "gpg.program"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            break
    return "gpg"


@functools.lru_cache(maxsize=1)
def _auditor_gpg_ssh_program() -> str:
    """Return the auditor's configured gpg.ssh.program, falling back to 'ssh-keygen'."""
    for scope in ("--global", "--system"):
        try:
            res = subprocess.run(
                ["git", "config", "--includes", scope, "--get", "gpg.ssh.program"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            break
    return "ssh-keygen"


@functools.lru_cache(maxsize=1)
def _auditor_gpg_x509_program() -> str:
    """Return the auditor's configured gpg.x509.program, falling back to 'gpgsm'."""
    for scope in ("--global", "--system"):
        try:
            res = subprocess.run(
                ["git", "config", "--includes", scope, "--get", "gpg.x509.program"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            break
    return "gpgsm"


_filter_overrides_cache: dict[Path, tuple[tuple[Any, ...], list[str]]] = {}


def clear_repo_filter_cache() -> None:
    """Clear the cached git filter overrides."""
    _filter_overrides_cache.clear()


def _discover_submodule_configs(repo_path: Path, git_dir: Path) -> list[tuple[Path, Path]]:
    """Discover submodule config files and their git directories.

    Returns a list of (config_file, sub_git_dir) pairs for submodules found in:
    1. .git/modules/**/config (standard submodule layout)
    2. The git index (mode 160000 via git ls-files --stage), covering submodules
       with in-tree .git directories and recursing into nested submodules (issue #617 review).
    """
    visited_worktrees: set[Path] = set()
    visited_configs: set[Path] = set()
    entries: list[tuple[Path, Path]] = []

    # 1. Any configs under .git/modules
    modules_dir = git_dir / "modules"
    if modules_dir.is_dir():
        try:
            for p in sorted(modules_dir.rglob("config")):
                if p.is_file() and p not in visited_configs:
                    visited_configs.add(p)
                    entries.append((p, p.parent))
        except OSError:
            pass

    # 2. Submodules from index (mode 160000), including in-tree .git directories and nested submodules
    def _scan_submodules_from_index(current_worktree: Path, depth: int = 0) -> None:
        if depth > 10 or current_worktree in visited_worktrees:
            return
        visited_worktrees.add(current_worktree)

        try:
            res = subprocess.run(
                ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "ls-files", "--stage"],
                cwd=current_worktree,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return

        if res.returncode != 0 or not res.stdout:
            return

        for line in res.stdout.splitlines():
            if not line.startswith("160000 "):
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            rel_path = parts[1]
            sub_worktree = (current_worktree / rel_path).resolve()
            sub_git_target = sub_worktree / ".git"
            sub_git_dir: Path | None = None
            if sub_git_target.is_dir():
                sub_git_dir = sub_git_target
            elif sub_git_target.is_file():
                try:
                    content = sub_git_target.read_text().strip()
                    if content.startswith("gitdir:"):
                        sub_git_dir = (sub_worktree / content.split(":", 1)[1].strip()).resolve()
                except OSError:
                    sub_git_dir = None

            if sub_git_dir and sub_git_dir.is_dir():
                sub_cfg = sub_git_dir / "config"
                if sub_cfg.is_file() and sub_cfg not in visited_configs:
                    visited_configs.add(sub_cfg)
                    entries.append((sub_cfg, sub_git_dir))
                # Recurse into nested submodules
                _scan_submodules_from_index(sub_worktree, depth + 1)

    _scan_submodules_from_index(repo_path, 0)
    return entries


def _repo_filter_overrides(repo: str | Path) -> list[str]:
    """Find filter names in ``repo``'s git config and submodule configs, returning args to neutralize them.

    Results are cached per repository based on .git/config, index, and submodule config mtimes (issue #617).
    """
    try:
        repo_path = Path(repo).resolve()
    except (OSError, ValueError):
        return []

    git_target = repo_path / ".git"
    git_dir: Path | None = None
    if git_target.is_file():
        try:
            content = git_target.read_text().strip()
            if content.startswith("gitdir:"):
                git_dir = (repo_path / content.split(":", 1)[1].strip()).resolve()
        except OSError:
            git_dir = None
    elif git_target.is_dir():
        git_dir = git_target

    if not git_dir or not git_dir.is_dir():
        return []

    # Build cache fingerprint from config mtime, index mtime, and submodule config mtimes
    main_cfg = git_dir / "config"
    try:
        main_mtime = main_cfg.stat().st_mtime_ns if main_cfg.is_file() else 0
    except OSError:
        main_mtime = 0

    index_file = git_dir / "index"
    try:
        index_mtime = index_file.stat().st_mtime_ns if index_file.is_file() else 0
    except OSError:
        index_mtime = 0

    modules_dir = git_dir / "modules"
    try:
        modules_mtime = modules_dir.stat().st_mtime_ns if modules_dir.is_dir() else 0
    except OSError:
        modules_mtime = 0

    if repo_path in _filter_overrides_cache:
        cached_key, cached_overrides = _filter_overrides_cache[repo_path]
        c_main_m, c_index_m, c_modules_m, c_sub_info = cached_key
        if main_mtime == c_main_m and index_mtime == c_index_m and modules_mtime == c_modules_m:
            sub_unchanged = True
            for cfg_str, cfg_m, dir_str, dir_m in c_sub_info:
                try:
                    if Path(cfg_str).stat().st_mtime_ns != cfg_m:
                        sub_unchanged = False
                        break
                    if Path(dir_str).stat().st_mtime_ns != dir_m:
                        sub_unchanged = False
                        break
                except OSError:
                    sub_unchanged = False
                    break
            if sub_unchanged:
                return list(cached_overrides)

    sub_entries = _discover_submodule_configs(repo_path, git_dir)

    names: set[str] = set()

    def _extract_filter_names(output: str) -> None:
        for line in output.splitlines():
            parts = line.split(None, 1)
            if parts:
                key = parts[0]
                if key.startswith("filter.") and "." in key[7:]:
                    name = key[7:].rsplit(".", 1)[0]
                    if name:
                        names.add(name)

    # 1. Main repository config (pass --includes so include.path is followed)
    try:
        res = subprocess.run(
            ["git", "config", "--includes", "--get-regexp", r"^filter\."],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if res.returncode == 0 and res.stdout:
            _extract_filter_names(res.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # 2. Submodule configs (passing --includes so submodule include.path is followed)
    for cfg, _ in sub_entries:
        try:
            res = subprocess.run(
                ["git", "config", "--file", str(cfg), "--includes", "--get-regexp", r"^filter\."],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode == 0 and res.stdout:
                _extract_filter_names(res.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    overrides: list[str] = []
    for name in sorted(names):
        overrides.extend(
            [
                "-c",
                f"filter.{name}.clean=",
                "-c",
                f"filter.{name}.process=",
                "-c",
                f"filter.{name}.required=false",
            ]
        )

    sub_info = []
    for cfg, s_dir in sub_entries:
        cfg_m = cfg.stat().st_mtime_ns if cfg.is_file() else 0
        dir_m = s_dir.stat().st_mtime_ns if s_dir.is_dir() else 0
        sub_info.append((str(cfg), cfg_m, str(s_dir), dir_m))

    cache_key = (main_mtime, index_mtime, modules_mtime, tuple(sub_info))
    _filter_overrides_cache[repo_path] = (cache_key, overrides)
    return list(overrides)


def run_git(
    repo: str | Path,
    *args: str,
    stdin: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a read-side git command on ``repo`` safely.

    To protect the auditor from untrusted repository configuration (issue #617),
    this helper disables ``core.fsmonitor``, neutralizes clean and process filters,
    and pins ``gpg.program``, ``gpg.ssh.program``, and ``gpg.x509.program`` to the
    auditor's configuration (or defaults).
    """
    cmd = [
        "git",
        "--no-optional-locks",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"gpg.program={_auditor_gpg_program()}",
        "-c",
        f"gpg.ssh.program={_auditor_gpg_ssh_program()}",
        "-c",
        f"gpg.x509.program={_auditor_gpg_x509_program()}",
        *_repo_filter_overrides(repo),
        *args,
    ]
    return subprocess.run(
        cmd,
        cwd=repo,
        capture_output=True,
        text=True,
        input=stdin,
        timeout=timeout,
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


def show_prefix(repo: str | Path) -> str:
    """``repo``'s path below the repository root (``""`` at the root), as ``git rev-parse --show-prefix`` prints it."""
    return _checked(repo, "rev-parse", "--show-prefix").strip()


def from_root(repo: str | Path, paths: Iterable[str], *, prefix: str | None = None) -> list[str]:
    """Repository-root-relative ``paths`` (as ``git status --porcelain`` and ``diff-tree`` print them), relative to ``repo``.

    ``prefix`` is :func:`show_prefix` of ``repo``, read when not given. A path
    outside ``repo`` (when ``repo`` is a subdirectory) comes back with a
    leading ``../``.
    """
    if prefix is None:
        prefix = show_prefix(repo)
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


def describe_foreign_commits(repo: str | Path, base: str, branch: str, where: str) -> str | None:
    """``"<n> commit(s) <where> without a ... trailer (<sha>, ...)"`` for :func:`foreign_commits`, or None when there are none."""
    foreign = foreign_commits(repo, base, branch)
    if not foreign:
        return None
    listed = ", ".join(sha[:12] for sha in foreign)
    return f"{len(foreign)} commit(s) {where} without a {TRAILER_KEY} trailer ({listed})"


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
    foreign = describe_foreign_commits(repo, base, branch_name, f"beyond '{base}'")
    if foreign:
        return f"branch '{branch_name}' has {foreign}; it holds work remediation did not make"
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
    foreign = describe_foreign_commits(repo, base, start, f"not on the pull request base '{base}'")
    if foreign:
        return (
            f"'{start}' has {foreign}; a pull request would carry work remediation did not make. "
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
    "describe_foreign_commits",
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
    "show_prefix",
    "valid_branch_name",
]
