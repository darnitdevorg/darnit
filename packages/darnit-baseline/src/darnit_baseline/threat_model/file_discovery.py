"""Repository walking with vendor/build exclusion and .gitignore honoring.

Responsible for turning a repository root into a deduplicated list of
`ScannedFile` records filtered by:

1. Baseline exclusion directories (vendor/build/cache directories for common
   language ecosystems)
2. Directory names listed in the root `.gitignore` (prefix match only — full
   gitignore glob semantics are deferred per FR-024)
3. User-supplied additional exclusions from the handler config

The result is consumed by `discovery.py` to drive tree-sitter parsing. Files
with unsupported extensions are still walked (for accounting) but not returned
as scannable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from darnit.core.repo_files import within_repository

from .discovery_models import FileScanStats
from .parsing import detect_language_from_path

logger = logging.getLogger("darnit_baseline.threat_model.file_discovery")


#: Directories that are never scanned, regardless of ``.gitignore``. Users can
#: append to this list via ``exclude_dirs`` in the handler config but cannot
#: disable any of these (FR-024).
BASELINE_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        # Python
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".nox",
        "*.egg-info",
        # JavaScript / TypeScript
        "node_modules",
        ".next",
        ".nuxt",
        ".svelte-kit",
        # Go
        "vendor",
        # Rust / JVM / generic build
        "target",
        "dist",
        "build",
        "out",
        "tmp",
        # VCS
        ".git",
        ".hg",
        ".svn",
        # IDE / OS
        ".idea",
        ".vscode",
        ".DS_Store",
        # Test directories — not production attack surface
        "tests",
        "test",
        "testdata",
        "fixtures",
    }
)


@dataclass(frozen=True)
class ScannedFile:
    """A file the discovery pipeline will parse.

    ``path`` is an absolute filesystem path. ``relpath`` is the path relative
    to the repository root used for display in findings. ``language`` is the
    tree-sitter grammar name returned by ``parsing.detect_language_from_path``.
    """

    path: Path
    relpath: str
    language: str

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


def _parse_gitignore_dirs(gitignore_path: Path) -> set[str]:
    """Extract directory-name patterns from a ``.gitignore`` file.

    Matches only bare directory names (``build/`` → ``build``, ``node_modules``
    → ``node_modules``). Ignores wildcards, negations, and nested paths;
    complex gitignore semantics are explicitly deferred per FR-024.
    """

    if not gitignore_path.is_file():
        return set()

    names: set[str] = set()
    try:
        text = gitignore_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("failed to read %s: %s", gitignore_path, e)
        return names

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        # Skip anything with wildcards, slashes other than a trailing one, or
        # special characters; we only honor bare directory names in v1.
        if any(ch in line for ch in ("*", "?", "[", "]")):
            continue
        # Trim trailing slash, leading slash (absolute within the repo)
        candidate = line.rstrip("/").lstrip("/")
        if "/" in candidate:
            continue
        if candidate:
            names.add(candidate)
    return names


def walk_repo(
    root: Path,
    extra_excludes: Iterable[str] = (),
    shallow_threshold: int = 500,
) -> tuple[list[ScannedFile], FileScanStats]:
    """Walk ``root`` and return scannable files plus file-scan stats.

    Skips directories in the baseline exclusion list, any directory named
    in the repository root's ``.gitignore`` (per the prefix-match rules above),
    and any extra excludes supplied by the caller.

    Files with unknown extensions are counted in ``total_files_seen`` but not
    returned in the scanned-files list (they're neither excluded by rule nor
    in-scope for parsing).
    """

    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"walk_repo: root is not a directory: {root}")

    gitignore = root / ".gitignore"
    gitignore_dirs = _parse_gitignore_dirs(gitignore) if within_repository(root, gitignore) else set()
    extra = {name for name in extra_excludes if name}
    effective_excludes = BASELINE_EXCLUDED_DIRS | gitignore_dirs | extra

    total_files_seen = 0
    excluded_dir_count = 0
    in_scope: list[ScannedFile] = []
    by_language: dict[str, int] = {}

    for dirpath, pruned_count, filenames in _walk_filtered(root, effective_excludes):
        excluded_dir_count += pruned_count
        for name in filenames:
            total_files_seen += 1
            fpath = Path(dirpath) / name
            lang = detect_language_from_path(fpath)
            if lang is None:
                continue
            if not within_repository(root, fpath):
                logger.debug("skipping %s: resolves outside the repository", fpath)
                continue
            try:
                relpath = str(fpath.relative_to(root))
            except ValueError:
                relpath = str(fpath)
            in_scope.append(ScannedFile(path=fpath, relpath=relpath, language=lang))
            by_language[lang] = by_language.get(lang, 0) + 1

    # ``unsupported_file_count`` is the number of files we walked past that
    # had no tree-sitter grammar (README.md, .png, LICENSE, etc.). It is
    # distinct from ``excluded_dir_count``, which counts pruned directories.
    unsupported_file_count = total_files_seen - len(in_scope)

    stats = FileScanStats(
        total_files_seen=total_files_seen,
        excluded_dir_count=excluded_dir_count,
        unsupported_file_count=unsupported_file_count,
        in_scope_files=len(in_scope),
        by_language=dict(by_language),
        shallow_mode=len(in_scope) > shallow_threshold,
        shallow_threshold=shallow_threshold,
    )
    logger.debug(
        "walk_repo: seen=%d, in_scope=%d, unsupported=%d, pruned_dirs=%d, shallow=%s",
        total_files_seen,
        len(in_scope),
        unsupported_file_count,
        excluded_dir_count,
        stats.shallow_mode,
    )
    return in_scope, stats


def _walk_filtered(root: Path, excluded_names: frozenset[str] | set[str]):
    """Depth-first walk of ``root`` skipping any directory whose name matches.

    This is ``os.walk``-like but prunes excluded directory names in-place so
    we never descend into them at all. Yields
    ``(dirpath, pruned_count, filenames)`` where ``pruned_count`` is the
    number of directory entries that were removed from traversal at this
    level, so callers can account for excluded directories in FileScanStats.
    """

    import os

    for dirpath, dirnames, filenames in os.walk(root):
        before = len(dirnames)
        dirnames[:] = [d for d in dirnames if d not in excluded_names]
        pruned = before - len(dirnames)
        yield dirpath, pruned, filenames


__all__ = [
    "BASELINE_EXCLUDED_DIRS",
    "ScannedFile",
    "walk_repo",
]
