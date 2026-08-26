"""US4 T045: no silent fallback to filesystem when a plugin is selected (FR-012).

Feature 033. When TOML selects a backend, the framework MUST use it (or
raise). It must never quietly swap in the filesystem default when the
selected backend fails.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


class TestUS4NoSilentFallback:
    def test_selected_plugin_prevents_filesystem_default_construction(
        self, tmp_path: Path
    ):
        from darnit_testchecks.stores import InMemoryProjectStateStore

        from darnit.config.framework_schema import StoreBlock, StoresConfig
        from darnit.stores.selection import resolve_stores

        config = StoresConfig(project=StoreBlock(backend="in-memory"))

        with patch(
            "darnit.stores.defaults.project.FilesystemProjectStateStore.__init__",
            return_value=None,
        ) as fs_ctor:
            bundle = resolve_stores(config, repo_path=tmp_path)
            # Trigger construction of the project store.
            store = bundle.project

        # Selected plugin was constructed, filesystem default was NOT.
        assert isinstance(store, InMemoryProjectStateStore)
        assert fs_ctor.call_count == 0

    def test_missing_plugin_raises_no_filesystem_fallback(self, tmp_path: Path):
        from darnit.config.framework_schema import StoreBlock, StoresConfig
        from darnit.stores import discovery
        from darnit.stores.errors import StoreNotInstalled
        from darnit.stores.selection import resolve_stores

        discovery._reset_discovery_cache()
        config = StoresConfig(project=StoreBlock(backend="phantom"))

        with patch(
            "darnit.stores.defaults.project.FilesystemProjectStateStore.__init__",
            return_value=None,
        ) as fs_ctor:
            import pytest as _pytest
            with _pytest.raises(StoreNotInstalled):
                resolve_stores(config, repo_path=tmp_path)
            # Fail-fast: no filesystem default constructed either.
            assert fs_ctor.call_count == 0
