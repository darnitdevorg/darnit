"""Helpers shared by more than one test suite (not fixtures)."""

from __future__ import annotations

import hashlib
from pathlib import Path


def snapshot(root: Path) -> dict[str, str | None]:
    """Every path under ``root`` except ``.git/``, mapped to a content digest (None for directories)."""
    tree: dict[str, str | None] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] == ".git":
            continue
        tree[relative.as_posix()] = None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return tree


def assert_unchanged(root: Path, before: dict[str, str | None]) -> None:
    """Fail naming every file created, modified, or deleted since ``before``."""
    after = snapshot(root)
    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    assert not (created or deleted or modified), (
        f"repository changed: created={created} modified={modified} deleted={deleted}"
    )
