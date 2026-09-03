"""Audit result cache for cross-tool-call persistence.

Caches audit results so the remediate tool can skip re-running the audit
when results are fresh. Feature 035 refactored this module from a
direct-tempdir implementation into a thin wrapper over feature 033's
:class:`~darnit.stores.protocols.AuditCacheStore` Protocol, so an
operator setting ``[stores.cache]`` in ``.baseline.toml`` actually
redirects the cache location.

Two call forms:

* **Backward-compat** (external callers, no store passed): the wrapper
  builds a :class:`~darnit.stores.defaults.FilesystemAuditCacheStore`
  rooted at ``<tempdir>/darnit/<sha256(abspath(repo))[:16]>`` and uses
  the literal cache key ``"audit-cache"``. On-disk path is byte-for-byte
  identical to the pre-feature layout::

      <tempdir>/darnit/<repo-hash>/audit-cache.json

* **Driver call form** (:mod:`darnit.tools.audit` passes both ``store``
  and ``cache_key``): the wrapper uses them verbatim. The driver decides
  the cache_key based on whether ``[stores.cache]`` was configured --
  ``"audit-cache"`` for the default store (root already encodes repo
  identity) or ``sha256(abspath(repo))[:16]`` for a configured store
  (root is operator-picked, key must encode repo identity).

Staleness is tracked via TTL, git HEAD commit hash, and working-tree
dirty state -- all in this wrapper, not in the store. The store is a
plain KV over dict envelopes.

Public API::

    write_audit_cache(local_path, results, summary, level, framework,
                      *, store=None, cache_key=None)
    read_audit_cache(local_path, ttl_seconds=3600,
                     *, store=None, cache_key=None) -> dict | None
    invalidate_audit_cache(local_path, *, store=None, cache_key=None)
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from darnit.core.logging import get_logger
from darnit.sieve.models import CheckResult

if TYPE_CHECKING:
    from darnit.stores.protocols import AuditCacheStore

logger = get_logger("core.audit_cache")

CACHE_FILENAME = "audit-cache.json"
CACHE_VERSION = 1

# Invalidation via write-expired-envelope (feature 035 clarify Q3).
# The AuditCacheStore Protocol has no delete(key) method; instead,
# invalidate_audit_cache overwrites the current envelope with one whose
# timestamp is guaranteed to fail every future TTL check.
_EXPIRED_ENVELOPE: dict[str, Any] = {
    "version": CACHE_VERSION,
    "timestamp": "1970-01-01T00:00:00+00:00",
    "commit": None,
    "commit_dirty": False,
    "level": 0,
    "framework": "",
    "results": [],
    "summary": {},
}


# ---------------------------------------------------------------------------
# Cache location (backward-compat helper)
# ---------------------------------------------------------------------------


def _get_cache_dir(local_path: str) -> Path:
    """Return the per-repo cache directory under the system temp dir.

    Used by:
    * the backward-compat default-store construction in the three public
      wrapper functions when the caller does NOT pass ``store``, and
    * existing tests at ``tests/darnit/core/test_audit_cache.py`` that
      compose the expected on-disk path via this helper.

    Uses a short SHA-256 hash of the repo's resolved absolute path so
    each repository gets an isolated cache directory.
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
    # If we can't determine dirty state, assume dirty (conservative).
    return True


# ---------------------------------------------------------------------------
# Internal store selection
# ---------------------------------------------------------------------------


def _resolve_store_and_key(
    local_path: str,
    store: AuditCacheStore | None,
    cache_key: str | None,
) -> tuple[AuditCacheStore, str]:
    """Return ``(store, cache_key)`` per the two-form contract.

    * Both ``None``: build a default
      :class:`~darnit.stores.defaults.FilesystemAuditCacheStore` rooted at
      ``<tempdir>/darnit/<sha256(abspath(local_path))[:16]>`` and use
      cache_key ``"audit-cache"``. Byte-for-byte legacy path.
    * Both provided: return as-is.
    * Exactly one provided: :class:`TypeError` (partial-kwarg guardrail
      per contracts/audit-cache-wrapper.md).
    """
    if (store is None) != (cache_key is None):
        raise TypeError("store and cache_key must be passed together")
    if store is None:
        # Deferred import to keep the module import graph shallow.
        from darnit.stores.defaults import FilesystemAuditCacheStore

        store = FilesystemAuditCacheStore(_get_cache_dir(local_path))
        cache_key = "audit-cache"
    assert cache_key is not None  # narrow type
    return store, cache_key


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_audit_cache(
    local_path: str,
    results: list[CheckResult],
    summary: dict[str, int],
    level: int,
    framework: str,
    *,
    store: AuditCacheStore | None = None,
    cache_key: str | None = None,
) -> None:
    """Write audit results to the cache via the given (or default) store.

    Composes the cache envelope (version, timestamp, commit, commit_dirty,
    level, framework, results, summary) and hands it to
    ``store.write(cache_key, envelope)``. Failures are logged at warning
    level and swallowed -- per feature 035 FR-007, cache-write failure
    MUST NOT propagate to the audit's exit code.

    Args:
        local_path: Path to the repository root (used for git
            introspection and, when ``store`` is None, for default-store
            construction).
        results: The raw results list from ``run_sieve_audit()``.
        summary: Status count summary from ``run_sieve_audit()``.
        level: Maximum audit level that was evaluated.
        framework: Framework name (e.g. ``"openssf-baseline"``).
        store: Optional :class:`AuditCacheStore` instance. When None, a
            legacy-path default store is constructed. Must be passed
            together with ``cache_key``.
        cache_key: Optional cache key string. When None, defaults to
            ``"audit-cache"`` (used with the default store's per-repo
            tempdir root). Must be passed together with ``store``.
    """
    store, cache_key = _resolve_store_and_key(local_path, store, cache_key)

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

    try:
        store.write(cache_key, envelope)
    except Exception as exc:  # noqa: BLE001 -- FR-007 best-effort
        logger.warning(
            "audit cache write failed (non-fatal): %s: %s",
            type(exc).__name__,
            exc,
        )


def read_audit_cache(
    local_path: str,
    ttl_seconds: int = 3600,
    *,
    store: AuditCacheStore | None = None,
    cache_key: str | None = None,
) -> dict[str, Any] | None:
    """Read cached audit results if they are still fresh.

    Returns the full cache envelope (including ``results`` and
    ``summary``) when the cache exists, has a supported version, is
    within the TTL, and its git commit + dirty state match the current
    repository state.

    Returns ``None`` on any mismatch, missing file, or corruption --
    callers should fall back to running a fresh audit. Never raises.

    Staleness enforcement (TTL / commit / dirty) lives here, NOT in the
    store; the store is a plain KV.
    """
    store, cache_key = _resolve_store_and_key(local_path, store, cache_key)

    try:
        data = store.read(cache_key)
    except Exception as exc:  # noqa: BLE001 -- read must never raise
        logger.debug("audit cache read failed: %s", exc)
        return None

    if data is None:
        logger.debug("No audit cache found for key %s", cache_key)
        return None

    if not isinstance(data, dict):
        logger.debug("Audit cache is not a JSON object")
        return None

    # Version check
    version = data.get("version")
    if not isinstance(version, int) or version > CACHE_VERSION:
        logger.debug("Unknown audit cache version: %s", version)
        return None

    # Staleness: TTL expiry
    timestamp_str = data.get("timestamp")
    if isinstance(timestamp_str, str):
        try:
            cached_time = datetime.fromisoformat(timestamp_str)
            if (datetime.now(UTC) - cached_time).total_seconds() > ttl_seconds:
                logger.debug("Audit cache expired per TTL (%s seconds)", ttl_seconds)
                return None
        except ValueError:
            logger.debug("Audit cache has invalid timestamp: %s", timestamp_str)
            return None
    else:
        logger.debug("Audit cache missing timestamp")
        return None

    # Staleness: commit hash
    cached_commit = data.get("commit")
    if cached_commit is None:
        # Written in a non-git repo -> always stale.
        logger.debug("Audit cache has null commit -- treating as stale")
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


def invalidate_audit_cache(
    local_path: str,
    *,
    store: AuditCacheStore | None = None,
    cache_key: str | None = None,
) -> None:
    """Invalidate the audit cache by writing an expired envelope.

    Feature 035 clarify Q3: since the :class:`AuditCacheStore` Protocol
    has no ``delete(key)`` method, invalidation is implemented as an
    overwrite with an envelope whose timestamp is 1970-01-01T00:00:00Z.
    The next :func:`read_audit_cache` misses on the TTL check.

    The on-disk cache file remains until the next successful write
    overwrites it -- acceptable because the default cache path is an
    operator-invisible tempdir.

    Never raises. Write failures are logged at warning level and
    swallowed (same contract as :func:`write_audit_cache`).
    """
    store, cache_key = _resolve_store_and_key(local_path, store, cache_key)
    try:
        store.write(cache_key, dict(_EXPIRED_ENVELOPE))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "audit cache invalidation failed (non-fatal): %s: %s",
            type(exc).__name__,
            exc,
        )
