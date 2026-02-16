"""Audit result cache for cross-tool-call persistence.

Caches audit results in a temp directory so that the remediate tool can
skip re-running the audit when results are fresh.  Each repository gets
its own cache keyed by a short hash of its absolute path:

    $TMPDIR/darnit/<repo-hash>/audit-cache.json

Staleness is tracked via the git HEAD commit hash and working-tree
dirty state.  Any mismatch → cache miss → remediate falls back to
running a fresh audit.

Public API:
    write_audit_cache(local_path, results, summary, level, framework)
    read_audit_cache(local_path) -> dict | None
    invalidate_audit_cache(local_path)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("core.audit_cache")

CACHE_FILENAME = "audit-cache.json"
CACHE_VERSION = 1


# ---------------------------------------------------------------------------
# Cache location
# ---------------------------------------------------------------------------


def _get_cache_dir(local_path: str) -> Path:
    """Return the per-repo cache directory under the system temp dir.

    Uses a short SHA-256 hash of the repo's resolved absolute path so
    that each repository gets an isolated cache directory.
    """
    resolved = str(Path(local_path).resolve())
    repo_hash = hashlib.sha256(resolved.encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "darnit" / repo_hash


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _get_head_commit(local_path: str) -> str | None:
    """Return the current HEAD commit hash, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=local_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _is_working_tree_dirty(local_path: str) -> bool:
    """Return True if the working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=local_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return len(result.stdout.strip()) > 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    # If we can't determine dirty state, assume dirty (conservative)
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_audit_cache(
    local_path: str,
    results: list[dict[str, Any]],
    summary: dict[str, int],
    level: int,
    framework: str,
) -> None:
    """Write audit results to the cache.

    Creates the cache directory if it doesn't exist.  Uses atomic write
    (tempfile + rename) to prevent corruption from interrupted writes.

    Args:
        local_path: Path to the repository root.
        results: The raw results list from ``run_sieve_audit()``.
        summary: Status count summary from ``run_sieve_audit()``.
        level: Maximum audit level that was evaluated.
        framework: Framework name (e.g. ``"openssf-baseline"``).
    """
    cache_dir = _get_cache_dir(local_path)
    cache_dir.mkdir(parents=True, exist_ok=True)

    envelope: dict[str, Any] = {
        "version": CACHE_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _get_head_commit(local_path),
        "commit_dirty": _is_working_tree_dirty(local_path),
        "level": level,
        "framework": framework,
        "results": results,
        "summary": summary,
    }

    cache_path = cache_dir / CACHE_FILENAME

    # Atomic write: write to temp file in same directory, then rename.
    fd, tmp_path = tempfile.mkstemp(
        dir=str(cache_dir), suffix=".tmp", prefix="audit-cache-"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(envelope, f, indent=2)
        os.replace(tmp_path, str(cache_path))
        logger.debug("Wrote audit cache to %s", cache_path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_audit_cache(local_path: str) -> dict[str, Any] | None:
    """Read cached audit results if they are still fresh.

    Returns the full cache envelope (including ``results`` and ``summary``)
    when the cache exists, is valid JSON, has a supported version, and
    the git commit + dirty state match the current repository state.

    Returns ``None`` on any mismatch, missing file, or corruption —
    callers should fall back to running a fresh audit.
    """
    cache_path = _get_cache_dir(local_path) / CACHE_FILENAME

    if not cache_path.is_file():
        logger.debug("No audit cache file at %s", cache_path)
        return None

    # Parse JSON
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Corrupt or unreadable audit cache: %s", exc)
        return None

    if not isinstance(data, dict):
        logger.debug("Audit cache is not a JSON object")
        return None

    # Version check
    version = data.get("version")
    if not isinstance(version, int) or version > CACHE_VERSION:
        logger.debug("Unknown audit cache version: %s", version)
        return None

    # Staleness: commit hash
    cached_commit = data.get("commit")
    if cached_commit is None:
        # Written in a non-git repo → always stale
        logger.debug("Audit cache has null commit — treating as stale")
        return None

    current_commit = _get_head_commit(local_path)
    if current_commit != cached_commit:
        logger.debug(
            "Audit cache stale: commit %s != current %s",
            cached_commit,
            current_commit,
        )
        return None

    # Staleness: dirty state
    cached_dirty = data.get("commit_dirty", False)
    current_dirty = _is_working_tree_dirty(local_path)
    if cached_dirty != current_dirty:
        logger.debug(
            "Audit cache stale: dirty %s != current %s",
            cached_dirty,
            current_dirty,
        )
        return None

    logger.debug("Audit cache hit (commit=%s, dirty=%s)", cached_commit, cached_dirty)
    return data


def invalidate_audit_cache(local_path: str) -> None:
    """Delete the audit cache file if it exists.

    No-op if the file is already missing.
    """
    cache_path = _get_cache_dir(local_path) / CACHE_FILENAME
    try:
        cache_path.unlink(missing_ok=True)
        logger.debug("Invalidated audit cache at %s", cache_path)
    except OSError as exc:
        logger.debug("Could not remove audit cache: %s", exc)
