"""Working-tree snapshots for previewing and recording exec remediations (feature 043, framework-design 4.4).

The files a command may see are the tracked files and the untracked files
the repository does not ignore; outside a git checkout, every file except
``.git/``. A preview copies them into a scratch directory, runs the command
there, and compares; an apply compares the checkout before and after.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from darnit.remediation import git_state
from darnit.remediation.plan import FileChange, content_digest, normalize_repo_path


@dataclass
class TreeDiff:
    """What changed between two snapshots: ``changes`` as FileChanges, and what a FileChange cannot express."""

    changes: list[FileChange] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    not_text: list[str] = field(default_factory=list)

    @property
    def representable(self) -> bool:
        return not self.deleted and not self.not_text


def all_files(root: str | Path) -> list[str]:
    """Every file under ``root`` except inside ``.git/`` directories."""
    root = Path(root)
    found: list[str] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        found += [(Path(directory) / name).relative_to(root).as_posix() for name in filenames]
    return sorted(found)


def visible_files(root: str | Path) -> list[str]:
    """Tracked plus untracked-not-ignored files under ``root`` (every file outside a git checkout).

    Raises:
        git_state.GitStateError: the checkout's file list cannot be read.
    """
    root = Path(root)
    if not git_state.is_work_tree(root):
        return all_files(root)
    result = git_state.run_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if result.returncode != 0:
        raise git_state.GitStateError(f"git ls-files failed: {result.stderr.strip() or result.returncode}")
    paths = sorted({p for p in result.stdout.split("\0") if p})
    return [p for p in paths if (root / p).is_file() or (root / p).is_symlink()]


def ignored(root: str | Path, paths: Iterable[str]) -> set[str]:
    """The ``paths`` that ``root``'s ignore rules exclude (none outside a git checkout)."""
    paths = list(paths)
    if not paths or not git_state.is_work_tree(root):
        return set()
    result = git_state.run_git(root, "check-ignore", "-z", "--stdin", stdin="\0".join(paths) + "\0")
    if result.returncode not in (0, 1):
        raise git_state.GitStateError(f"git check-ignore failed: {result.stderr.strip() or result.returncode}")
    return {p for p in result.stdout.split("\0") if p}


def user_changed(root: str | Path) -> set[str]:
    """Paths under ``root``, relative to it, with uncommitted changes (modified, staged, or untracked); empty outside git."""
    if not git_state.is_work_tree(root):
        return set()
    result = git_state.run_git(
        root, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames", "--", "."
    )
    if result.returncode != 0:
        raise git_state.GitStateError(f"git status failed: {result.stderr.strip() or result.returncode}")
    paths = git_state.from_root(root, [entry[3:] for entry in result.stdout.split("\0") if len(entry) > 3])
    return {path for path in paths if not path.startswith("../")}


def digests(root: str | Path, paths: Iterable[str]) -> dict[str, str]:
    root = Path(root)
    found = {}
    for path in paths:
        try:
            found[path] = content_digest((root / path).read_bytes())
        except (FileNotFoundError, IsADirectoryError):
            continue
    return found


def copy_files(source: str | Path, destination: str | Path, paths: Iterable[str]) -> None:
    source, destination = Path(source), Path(destination)
    for path in paths:
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / path, target, follow_symlinks=False)


def diff(root: str | Path, before: Mapping[str, str], after_paths: Iterable[str]) -> TreeDiff:
    """The difference between ``before`` (path to content digest) and the files ``after_paths`` under ``root`` now."""
    root = Path(root)
    after = digests(root, after_paths)
    result = TreeDiff(deleted=sorted(set(before) - set(after)))
    for path in sorted(after):
        if before.get(path) == after[path]:
            continue
        try:
            content = (root / path).read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            result.not_text.append(path)
            continue
        relative = normalize_repo_path(path)
        if path in before:
            result.changes.append(
                FileChange(path=relative, action="modify", content=content, before_digest=before[path])
            )
        else:
            result.changes.append(FileChange(path=relative, action="create", content=content))
    return result


__all__ = ["TreeDiff", "all_files", "copy_files", "diff", "digests", "ignored", "user_changed", "visible_files"]
