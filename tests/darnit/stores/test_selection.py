"""Tests for `resolve_stores` -- TOML block -> instantiated backend.

Feature 033 T019.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from darnit.config.framework_schema import StoreBlock, StoresConfig
from darnit.stores import discovery
from darnit.stores.defaults import (
    FilesystemAttestationStore,
    FilesystemAuditCacheStore,
    FilesystemProjectStateStore,
    FilesystemReportStore,
)
from darnit.stores.errors import StoreNotInstalled, StoreProtocolMismatch
from darnit.stores.selection import resolve_stores


@pytest.fixture(autouse=True)
def _reset_discovery_cache():
    discovery._reset_discovery_cache()
    yield
    discovery._reset_discovery_cache()


class TestAllDefaults:
    def test_none_config_yields_all_filesystem_defaults(self, tmp_path: Path):
        bundle = resolve_stores(None, repo_path=tmp_path)
        assert isinstance(bundle.project, FilesystemProjectStateStore)
        assert isinstance(bundle.attestation, FilesystemAttestationStore)
        assert isinstance(bundle.report, FilesystemReportStore)
        assert isinstance(bundle.cache, FilesystemAuditCacheStore)

    def test_empty_stores_config_same_as_none(self, tmp_path: Path):
        bundle = resolve_stores(StoresConfig(), repo_path=tmp_path)
        assert isinstance(bundle.project, FilesystemProjectStateStore)


class TestPluginSelection:
    def _register(self, monkeypatch, group: str, name: str, cls):
        """Fake a single entry-point registration under `group`."""
        ep = MagicMock()
        ep.name = name
        ep.value = f"{cls.__module__}:{cls.__qualname__}"
        ep.load.return_value = cls
        dist = MagicMock()
        dist.metadata = {"Name": "test-pkg"}
        ep.dist = dist

        original = discovery.metadata.entry_points

        def _entry_points(**kwargs):
            g = kwargs.get("group")
            if g == group:
                return [ep]
            return original(**kwargs)

        monkeypatch.setattr(discovery.metadata, "entry_points", _entry_points)

    def test_plugin_backend_instantiated(self, monkeypatch, tmp_path: Path):
        # A minimal AttestationStore plugin.
        class MyPlugin:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self._writes = []

            def write(self, bundle_id, bundle_bytes, content_type):
                self._writes.append((bundle_id, bundle_bytes, content_type))

            def close(self):
                pass

        self._register(monkeypatch, "darnit.stores.attestation", "myplugin", MyPlugin)

        config = StoresConfig(
            attestation=StoreBlock(backend="myplugin", extra_key="extra_val")
        )
        bundle = resolve_stores(config, repo_path=tmp_path)
        assert isinstance(bundle.attestation, MyPlugin)
        # backend-specific keys pass through
        assert bundle.attestation.kwargs.get("extra_key") == "extra_val"
        # `backend` field itself is NOT passed as a kwarg
        assert "backend" not in bundle.attestation.kwargs
        # Other kinds still use defaults
        assert isinstance(bundle.project, FilesystemProjectStateStore)

    def test_missing_plugin_raises_store_not_installed(self, monkeypatch, tmp_path: Path):
        # No plugin registered under this name.
        monkeypatch.setattr(
            discovery.metadata, "entry_points", lambda **kw: []
        )
        config = StoresConfig(project=StoreBlock(backend="nonexistent"))
        with pytest.raises(StoreNotInstalled) as exc:
            resolve_stores(config, repo_path=tmp_path)
        assert exc.value.name == "nonexistent"
        assert exc.value.group == "darnit.stores.project"

    def test_plugin_not_satisfying_protocol_raises_mismatch(self, monkeypatch, tmp_path: Path):
        # Missing `close()` (violates Store base + AttestationStore Protocol).
        class BrokenPlugin:
            def __init__(self, **kw): pass
            def write(self, bundle_id, bundle_bytes, content_type): pass
            # close() missing

        self._register(monkeypatch, "darnit.stores.attestation", "broken", BrokenPlugin)
        config = StoresConfig(attestation=StoreBlock(backend="broken"))
        with pytest.raises(StoreProtocolMismatch) as exc:
            resolve_stores(config, repo_path=tmp_path)
        assert "close" in exc.value.missing


class TestBundleClose:
    def test_close_all_calls_close_on_each_accessed(self, tmp_path: Path):
        bundle = resolve_stores(None, repo_path=tmp_path)
        # Force instantiation of all four via property access, then wrap
        # each close() to count.
        counter = {"n": 0}
        for kind in ("project", "attestation", "report", "cache"):
            store = getattr(bundle, kind)
            assert bundle.is_instantiated(kind)
            original = store.close

            def _wrapped(orig=original):
                counter["n"] += 1
                orig()

            store.close = _wrapped  # type: ignore[method-assign]

        bundle.close_all()
        assert counter["n"] == 4
        # After close_all, every kind must reset to un-instantiated so
        # a repeat call is a no-op.
        for kind in ("project", "attestation", "report", "cache"):
            assert not bundle.is_instantiated(kind)

    def test_close_all_skips_never_accessed(self, tmp_path: Path):
        """SC-004: a store never accessed is never constructed and never closed."""
        bundle = resolve_stores(None, repo_path=tmp_path)
        # Only touch .project. The other three stay lazy.
        _ = bundle.project
        assert bundle.is_instantiated("project")
        assert not bundle.is_instantiated("attestation")
        assert not bundle.is_instantiated("report")
        assert not bundle.is_instantiated("cache")
        bundle.close_all()
        # close_all still safe; nothing to close for the untouched three.
        assert not bundle.is_instantiated("project")

    def test_close_all_swallows_per_store_exceptions(self, tmp_path: Path):
        bundle = resolve_stores(None, repo_path=tmp_path)
        # Force construction, then break one store's close().
        for kind in ("project", "attestation", "report", "cache"):
            _ = getattr(bundle, kind)

        def _boom():
            raise RuntimeError("nope")

        bundle._instances["project"].close = _boom  # type: ignore[method-assign]
        # Must not raise.
        bundle.close_all()
        for kind in ("project", "attestation", "report", "cache"):
            assert not bundle.is_instantiated(kind)

    def test_close_all_repeat_safe(self, tmp_path: Path):
        bundle = resolve_stores(None, repo_path=tmp_path)
        bundle.close_all()
        bundle.close_all()  # must not raise
