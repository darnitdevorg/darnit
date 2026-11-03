"""Reads of the audited repository that stay inside it (framework-design.md 3.0.4).

A path is resolved as the operating system resolves it (``os.path.realpath``,
following every symbolic link in it) and must lie within the resolved
repository root. A path that resolves outside is not a file of the
repository: it is never read and never counts as present.
"""

from __future__ import annotations

import os
from typing import IO, Any

StrPath = str | os.PathLike[str]


class OutsideRepositoryError(OSError):
    """A path resolves, through symbolic links, to a location outside the repository.

    ``entry`` is the repository-relative entry that leads outside (the
    shortest prefix of the path that resolves outside), never the target.
    """

    def __init__(self, path: str, entry: str) -> None:
        super().__init__(f"{entry} resolves outside the repository")
        self.path = path
        self.entry = entry


def _full(root: StrPath, path: StrPath) -> str:
    path = os.fspath(path)
    return path if os.path.isabs(path) else os.path.join(os.fspath(root), path)


def _inside(real_root: str, real_path: str) -> bool:
    try:
        return os.path.commonpath([real_root, real_path]) == real_root
    except ValueError:
        return False


def within_repository(root: StrPath, path: StrPath) -> bool:
    """Whether ``path`` (absolute, or relative to ``root``) resolves inside ``root``."""
    return _inside(os.path.realpath(root), os.path.realpath(_full(root, path)))


def escaping_entry(root: StrPath, path: StrPath) -> str:
    """The repository-relative entry of ``path`` that leads outside ``root``.

    For ``docs/a.md`` where ``docs`` links outside, this is ``docs``, so the
    names of files outside the repository are never reported. A path that is
    already outside ``root`` before any link is followed is returned as given.
    """
    root_abs = os.path.abspath(root)
    real_root = os.path.realpath(root)
    rel = os.path.relpath(os.path.abspath(_full(root, path)), root_abs)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return os.fspath(path)
    parts = [] if rel == os.curdir else rel.split(os.sep)
    for i in range(1, len(parts) + 1):
        if not _inside(real_root, os.path.realpath(os.path.join(root_abs, *parts[:i]))):
            return "/".join(parts[:i])
    return "/".join(parts) or os.curdir


def resolve_in_repository(root: StrPath, path: StrPath) -> str:
    """The resolved path of ``path`` inside ``root``.

    Raises:
        OutsideRepositoryError: ``path`` resolves outside ``root``.
    """
    resolved = os.path.realpath(_full(root, path))
    if not _inside(os.path.realpath(root), resolved):
        raise OutsideRepositoryError(os.fspath(path), escaping_entry(root, path))
    return resolved


def open_in_repository(root: StrPath, path: StrPath, mode: str = "r", **kwargs: Any) -> IO[Any]:
    """Open ``path`` for reading after checking that it resolves inside ``root``.

    Raises:
        OutsideRepositoryError: ``path`` resolves outside ``root`` (an ``OSError``).
        ValueError: ``mode`` is not a read mode.
    """
    if any(flag in mode for flag in "wax+"):
        raise ValueError(f"open_in_repository opens for reading only, not {mode!r}")
    return open(resolve_in_repository(root, path), mode, **kwargs)  # noqa: SIM115 - returned to the caller


def read_repository_text(
    root: StrPath,
    path: StrPath,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> str:
    """The text of ``path``, which must resolve inside ``root``."""
    with open_in_repository(root, path, encoding=encoding, errors=errors) as f:
        return f.read()


def read_repository_bytes(root: StrPath, path: StrPath) -> bytes:
    """The bytes of ``path``, which must resolve inside ``root``."""
    with open_in_repository(root, path, "rb") as f:
        return f.read()


__all__ = [
    "OutsideRepositoryError",
    "escaping_entry",
    "open_in_repository",
    "read_repository_bytes",
    "read_repository_text",
    "resolve_in_repository",
    "within_repository",
]
