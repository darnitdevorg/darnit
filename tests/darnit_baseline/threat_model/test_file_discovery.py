"""Tests for darnit_baseline.threat_model.file_discovery.

Covers baseline exclusions, .gitignore directory matching, user-supplied
extra excludes, shallow-mode activation, and FileScanStats accounting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit_baseline.threat_model.file_discovery import (
    BASELINE_EXCLUDED_DIRS,
    ScannedFile,
    _parse_gitignore_dirs,
    walk_repo,
)


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_baseline_exclusions_present() -> None:
    """A handful of canonical vendor dirs must be in the baseline list."""
    for name in (
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "vendor",
        "dist",
        "build",
        ".git",
    ):
        assert name in BASELINE_EXCLUDED_DIRS


def test_baseline_exclusions_are_honored(tmp_path: Path) -> None:
    """Files inside excluded directories must not appear in the scan result."""
    _write(tmp_path / "src/app.py", "def foo(): pass\n")
    _write(tmp_path / "node_modules/pkg/index.js", "module.exports = {};\n")
    _write(tmp_path / ".venv/lib/python/site.py", "# vendor\n")
    _write(tmp_path / "__pycache__/cached.pyc", "")

    files, stats = walk_repo(tmp_path)
    relpaths = {f.relpath.replace("\\", "/") for f in files}

    assert "src/app.py" in relpaths
    assert not any("node_modules" in p for p in relpaths)
    assert not any(".venv" in p for p in relpaths)
    assert not any("__pycache__" in p for p in relpaths)
    assert stats.in_scope_files == 1
    # Three top-level directories were pruned: node_modules, .venv, __pycache__
    assert stats.excluded_dir_count == 3


def test_gitignore_dirs_excluded(tmp_path: Path) -> None:
    """Directory names listed in .gitignore must also be excluded."""
    _write(tmp_path / ".gitignore", "my_build/\ncustom_cache\n")
    _write(tmp_path / "src/a.py", "x = 1\n")
    _write(tmp_path / "my_build/generated.py", "x = 2\n")
    _write(tmp_path / "custom_cache/blob.py", "x = 3\n")

    files, stats = walk_repo(tmp_path)
    relpaths = {f.relpath.replace("\\", "/") for f in files}

    assert "src/a.py" in relpaths
    assert not any("my_build" in p for p in relpaths)
    assert not any("custom_cache" in p for p in relpaths)
    assert stats.in_scope_files == 1


def test_gitignore_wildcards_ignored_in_v1(tmp_path: Path) -> None:
    """V1 only honors bare directory names; wildcards are not parsed."""
    _write(tmp_path / ".gitignore", "*.pyc\n!keep/\nsub/*/tmp\n")
    dirs = _parse_gitignore_dirs(tmp_path / ".gitignore")
    # All three entries have characters v1 does not parse
    assert dirs == set()


def test_gitignore_missing_returns_empty_set(tmp_path: Path) -> None:
    dirs = _parse_gitignore_dirs(tmp_path / "does-not-exist")
    assert dirs == set()


def test_extra_excludes_are_additive(tmp_path: Path) -> None:
    """User-supplied extra_excludes supplement — they do not replace — the baseline."""
    _write(tmp_path / "src/app.py", "pass\n")
    _write(tmp_path / "node_modules/pkg/x.js", "pass\n")  # baseline still excluded
    _write(tmp_path / "custom_vendor/x.py", "pass\n")  # user exclusion

    files, _ = walk_repo(tmp_path, extra_excludes=["custom_vendor"])
    relpaths = {f.relpath.replace("\\", "/") for f in files}

    assert "src/app.py" in relpaths
    assert not any("node_modules" in p for p in relpaths)
    assert not any("custom_vendor" in p for p in relpaths)


def test_language_detection_populates_by_language(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "pass\n")
    _write(tmp_path / "b.js", "var x = 1;\n")
    _write(tmp_path / "c.ts", "const x: number = 1;\n")
    _write(tmp_path / "d.go", "package main\n")
    _write(tmp_path / "e.yaml", "name: x\n")
    _write(tmp_path / "f.tsx", "const C = () => <div/>;\n")
    _write(tmp_path / "README.md", "# readme\n")  # unsupported, skipped

    files, stats = walk_repo(tmp_path)

    assert stats.by_language["python"] == 1
    assert stats.by_language["javascript"] == 1
    assert stats.by_language["typescript"] == 1
    assert stats.by_language["go"] == 1
    assert stats.by_language["yaml"] == 1
    assert stats.by_language["tsx"] == 1
    assert stats.in_scope_files == 6
    assert stats.total_files_seen == 7  # includes README.md
    assert stats.unsupported_file_count == 1
    assert stats.excluded_dir_count == 0  # nothing to prune in this fixture


def test_shallow_mode_flag_tracks_in_scope_count(tmp_path: Path) -> None:
    for i in range(3):
        _write(tmp_path / f"a{i}.py", "pass\n")

    _, stats = walk_repo(tmp_path, shallow_threshold=2)
    assert stats.shallow_mode is True
    assert stats.in_scope_files == 3

    _, stats2 = walk_repo(tmp_path, shallow_threshold=10)
    assert stats2.shallow_mode is False


def test_walk_repo_rejects_non_directory(tmp_path: Path) -> None:
    target = tmp_path / "not_a_dir.py"
    target.write_text("x = 1\n")
    with pytest.raises(ValueError, match="not a directory"):
        walk_repo(target)


def test_excluded_dir_count_tracks_gitignore_prunes(tmp_path: Path) -> None:
    """Pruned directories from .gitignore should increment excluded_dir_count."""
    _write(tmp_path / ".gitignore", "custom_cache\nanother\n")
    _write(tmp_path / "src/a.py", "pass\n")
    _write(tmp_path / "custom_cache/x.py", "pass\n")
    _write(tmp_path / "another/y.py", "pass\n")

    files, stats = walk_repo(tmp_path)
    assert stats.in_scope_files == 1
    # Two .gitignore dirs pruned at the top level
    assert stats.excluded_dir_count == 2


def test_file_scan_stats_invariant(tmp_path: Path) -> None:
    """FileScanStats enforces total == unsupported + in_scope."""
    _write(tmp_path / "a.py", "pass\n")
    _write(tmp_path / "README.md", "# readme\n")
    _, stats = walk_repo(tmp_path)
    assert stats.total_files_seen == stats.unsupported_file_count + stats.in_scope_files


def test_relpath_is_repo_relative(tmp_path: Path) -> None:
    _write(tmp_path / "deep/nested/file.py", "pass\n")
    files, _ = walk_repo(tmp_path)
    assert len(files) == 1
    assert files[0].relpath.replace("\\", "/") == "deep/nested/file.py"
    assert files[0].path.is_absolute()
    assert files[0].language == "python"
    assert isinstance(files[0], ScannedFile)
