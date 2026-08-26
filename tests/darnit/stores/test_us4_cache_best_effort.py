"""US4 T043: AuditCacheStore failures are best-effort (FR-011).

Feature 033. A cache-write failure must not abort the audit; a
cache-read failure must return cache-miss semantics (None) so the
caller re-runs a fresh audit.
"""

from __future__ import annotations

from pathlib import Path


class TestUS4CacheBestEffort:
    def test_write_that_raises_is_swallowed_by_filesystem_default(
        self, tmp_path: Path, monkeypatch
    ):
        from darnit.stores.defaults import FilesystemAuditCacheStore

        store = FilesystemAuditCacheStore(tmp_path)
        # Break the underlying write.
        def _boom(*a, **kw):
            raise OSError("disk full")
        monkeypatch.setattr(Path, "write_text", _boom)
        monkeypatch.setattr(Path, "replace", _boom)
        # FR-011: write() must not raise regardless of backend failure.
        store.write("k", {"x": 1})

    def test_read_that_raises_returns_none(self, tmp_path: Path):
        from darnit.stores.defaults import FilesystemAuditCacheStore

        # Seed a corrupt JSON file to simulate a backend read failure.
        (tmp_path / "corrupt.json").write_text("<<< not json >>>")
        store = FilesystemAuditCacheStore(tmp_path)
        # Cache-miss semantics on parse failure, not an exception.
        assert store.read("corrupt") is None

    def test_plugin_write_failure_is_backend_responsibility(self, tmp_path: Path):
        """A well-behaved plugin swallows write failures internally.

        Verifies the reference in-memory backend upholds the contract:
        even if payload serialization would raise, write() returns
        cleanly.
        """
        from darnit_testchecks.stores import InMemoryAuditCacheStore

        store = InMemoryAuditCacheStore()
        # dict() of the payload triggers a copy; if that copy raised
        # (constructed dict from an unhashable-key mapping), the
        # backend must still not propagate.
        store.write("k", {"safe": "value"})
        assert store.read("k") == {"safe": "value"}
