"""In-memory AttestationStore reference backend (feature 033 T020)."""

from __future__ import annotations


class InMemoryAttestationStore:
    """Dict-backed AttestationStore for tests.

    Records every write as (bundle_id, bundle_bytes, content_type) in
    ``self._state`` (a list). Tests assert on it directly.
    """

    def __init__(self, **kwargs) -> None:
        self._state: list[tuple[str, bytes, str]] = []

    def write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None:
        self._state.append((bundle_id, bundle_bytes, content_type))

    def close(self) -> None:
        return None


__all__ = ["InMemoryAttestationStore"]
