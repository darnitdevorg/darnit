"""Minimal no-op AttestationStore for entry-point discovery tests."""

from __future__ import annotations


class ExampleAttestationStore:
    """Records writes to a class-level list. Testing-only."""

    _writes: list[tuple[str, bytes, str]] = []

    def __init__(self, **kwargs) -> None:
        pass

    def write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None:
        type(self)._writes.append((bundle_id, bundle_bytes, content_type))

    def close(self) -> None:
        return None
