"""Tests for the four filesystem-backed default store implementations.

Feature 033 T017.
"""

from __future__ import annotations

from pathlib import Path

from darnit.stores.defaults import (
    FilesystemAttestationStore,
    FilesystemAuditCacheStore,
    FilesystemReportStore,
)


class TestFilesystemAttestationStore:
    def test_write_creates_root_if_missing(self, tmp_path: Path):
        root = tmp_path / "attestations"
        assert not root.exists()
        store = FilesystemAttestationStore(root)
        store.write("bundle-1", b'{"foo":1}', "application/vnd.in-toto+json")
        target = root / "bundle-1.intoto.json"
        assert target.exists()
        assert target.read_bytes() == b'{"foo":1}'

    def test_write_sigstore_extension(self, tmp_path: Path):
        store = FilesystemAttestationStore(tmp_path)
        store.write("b2", b"sig-bytes", "application/vnd.dev.sigstore.bundle+json")
        assert (tmp_path / "b2.sigstore.json").exists()

    def test_write_unknown_content_type_uses_bin(self, tmp_path: Path):
        store = FilesystemAttestationStore(tmp_path)
        store.write("b3", b"raw", "application/octet-stream")
        assert (tmp_path / "b3.bin").exists()

    def test_bundle_id_sanitized(self, tmp_path: Path):
        store = FilesystemAttestationStore(tmp_path)
        store.write("owner/repo/run-42", b"data", "application/json")
        # `/` replaced with `_`
        found = list(tmp_path.glob("owner_repo_run-42*"))
        assert len(found) == 1

    def test_close_idempotent(self, tmp_path: Path):
        store = FilesystemAttestationStore(tmp_path)
        store.close()
        store.close()  # must not raise


class TestFilesystemReportStore:
    def test_writes_three_formats(self, tmp_path: Path):
        store = FilesystemReportStore(tmp_path)
        store.write_markdown("audit-1", "# hello")
        store.write_json("audit-1", '{"x":1}')
        store.write_sarif("audit-1", '{"runs":[]}')
        assert (tmp_path / "audit-1.md").read_text() == "# hello"
        assert (tmp_path / "audit-1.json").read_text() == '{"x":1}'
        assert (tmp_path / "audit-1.sarif").read_text() == '{"runs":[]}'

    def test_creates_missing_dir(self, tmp_path: Path):
        target = tmp_path / "nested" / "dir"
        store = FilesystemReportStore(target)
        store.write_json("r", '{"ok":true}')
        assert (target / "r.json").exists()

    def test_close_idempotent(self, tmp_path: Path):
        store = FilesystemReportStore(tmp_path)
        store.close()
        store.close()


class TestFilesystemAuditCacheStore:
    def test_read_miss_returns_none(self, tmp_path: Path):
        store = FilesystemAuditCacheStore(tmp_path)
        assert store.read("nokey") is None

    def test_write_then_read_roundtrip(self, tmp_path: Path):
        store = FilesystemAuditCacheStore(tmp_path)
        store.write("k1", {"a": 1, "b": [2, 3]})
        assert store.read("k1") == {"a": 1, "b": [2, 3]}

    def test_atomic_rename_leaves_no_tempfile(self, tmp_path: Path):
        store = FilesystemAuditCacheStore(tmp_path)
        store.write("k", {"x": 1})
        # Only the target JSON should be present; no `.tmp` residue.
        tmpfiles = list(tmp_path.glob("*.tmp"))
        assert tmpfiles == []

    def test_write_swallows_backend_failure(self, tmp_path: Path, monkeypatch):
        store = FilesystemAuditCacheStore(tmp_path)
        # Make mkdir fail. FR-011: AuditCacheStore write MUST NOT raise.
        def _boom(*a, **kw):
            raise OSError("nope")
        monkeypatch.setattr(Path, "mkdir", _boom)
        store.write("k", {"x": 1})  # would raise if implementation broken

    def test_read_swallows_json_corruption(self, tmp_path: Path):
        target = tmp_path / "k.json"
        target.write_text("this is not json")
        store = FilesystemAuditCacheStore(tmp_path)
        assert store.read("k") is None

    def test_close_idempotent(self, tmp_path: Path):
        store = FilesystemAuditCacheStore(tmp_path)
        store.close()
        store.close()


# ---------------------------------------------------------------------------
# FilesystemProjectStateStore has its own store<->reader dependency that
# doesn't fully land until Phase 3 T021's reader refactor; we test its
# basic construction + close idempotence here and the round-trip in the
# US1 tests once T021 is in place.
# ---------------------------------------------------------------------------


class TestFilesystemProjectStateStore:
    def test_constructs(self, tmp_path: Path):
        from darnit.stores.defaults import FilesystemProjectStateStore

        store = FilesystemProjectStateStore(tmp_path)
        assert store.project_yaml == tmp_path / ".project" / "project.yaml"
        assert store.maintainers_yaml == tmp_path / ".project" / "maintainers.yaml"

    def test_close_idempotent(self, tmp_path: Path):
        from darnit.stores.defaults import FilesystemProjectStateStore

        store = FilesystemProjectStateStore(tmp_path)
        store.close()
        store.close()

    def test_read_missing_project_returns_none(self, tmp_path: Path):
        from darnit.stores.defaults import FilesystemProjectStateStore

        store = FilesystemProjectStateStore(tmp_path)
        assert store.read_project() is None
