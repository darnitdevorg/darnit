"""In-memory AuditCacheStore reference backend (feature 033 T020)."""

from __future__ import annotations

from typing import Any


class InMemoryAuditCacheStore:
    """Dict-backed AuditCacheStore for tests.

    ``self._state`` is a dict keyed by cache_key. write() must NOT raise
    (FR-011); read() returns None on miss.
    """

    def __init__(self, **kwargs) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def read(self, cache_key: str) -> "dict[str, Any] | None":
        return self._state.get(cache_key)

    def write(self, cache_key: str, payload: "dict[str, Any]") -> None:
        # FR-011: cache write is best-effort; swallow all errors.
        try:
            self._state[cache_key] = dict(payload)
        except Exception:
            pass

    def close(self) -> None:
        return None


__all__ = ["InMemoryAuditCacheStore"]
