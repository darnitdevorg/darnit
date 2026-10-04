"""Helpers shared by more than one test suite (not fixtures)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


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


def stand_in_tool(
    monkeypatch: pytest.MonkeyPatch,
    bin_dir: Path,
    name: str,
    *,
    stdout: str = "",
    exit_code: int = 0,
    script: str = "",
) -> Path:
    """Put an executable ``name`` first on ``PATH``, standing in for a real tool such as ``zizmor``.

    It runs ``script`` (POSIX sh, with the tool's arguments as ``$@``),
    then writes ``stdout`` exactly (nothing when empty) and exits with
    ``exit_code``.
    """
    lines = ["#!/bin/sh", script]
    if stdout:
        output = bin_dir / f"{name}.stdout"
        output.write_text(stdout, encoding="utf-8")
        lines.append(f"cat '{output}'")
    lines.append(f"exit {exit_code}")
    tool = bin_dir / name
    tool.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return tool
