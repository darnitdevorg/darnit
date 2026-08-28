"""US1 lazy instantiation: a store never touched is never constructed.

Feature 033 T025a / SC-004. The bundle returned by ``resolve_stores``
carries factory closures; each store's ``__init__`` fires only when the
corresponding property is first accessed. If an audit run never touches
attestations, neither the filesystem default nor a selected plugin
backend should have its constructor called.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from darnit.config.framework_schema import StoreBlock, StoresConfig
from darnit.stores.selection import resolve_stores


class TestUS1LazyInstantiation:
    def test_no_construction_when_kind_never_accessed(self, tmp_path: Path):
        """SC-004: zero constructor calls for an unused store kind."""
        bundle = resolve_stores(None, repo_path=tmp_path)

        with patch(
            "darnit.stores.defaults.attestation.FilesystemAttestationStore.__init__",
            return_value=None,
        ) as mock_init:
            # Simulate an audit that reads project data only. The other
            # three kinds must stay dormant.
            _ = bundle.project
            assert mock_init.call_count == 0

        assert bundle.is_instantiated("project")
        assert not bundle.is_instantiated("attestation")
        assert not bundle.is_instantiated("report")
        assert not bundle.is_instantiated("cache")

    def test_plugin_kind_stays_dormant_when_never_accessed(self, tmp_path: Path):
        """The lazy contract holds equally for plugin-selected kinds."""
        config = StoresConfig(attestation=StoreBlock(backend="in-memory"))
        bundle = resolve_stores(config, repo_path=tmp_path)

        # Patch the plugin's __init__ AFTER resolve_stores (validation
        # completed at resolve time did class-shape checks, not
        # construction). If the audit run never touches attestations,
        # the plugin's constructor must never fire.
        with patch(
            "darnit_testchecks.stores.in_memory_attestation.InMemoryAttestationStore.__init__",
            return_value=None,
        ) as mock_init:
            _ = bundle.project
            _ = bundle.report
            _ = bundle.cache
            assert mock_init.call_count == 0

        assert not bundle.is_instantiated("attestation")

    def test_close_all_does_not_construct_dormant_kinds(self, tmp_path: Path):
        """close_all() must NOT touch a kind that was never accessed."""
        bundle = resolve_stores(None, repo_path=tmp_path)

        with patch(
            "darnit.stores.defaults.report.FilesystemReportStore.__init__",
            return_value=None,
        ) as mock_report_init, patch(
            "darnit.stores.defaults.cache.FilesystemAuditCacheStore.__init__",
            return_value=None,
        ) as mock_cache_init:
            _ = bundle.project  # only access one
            bundle.close_all()
            assert mock_report_init.call_count == 0
            assert mock_cache_init.call_count == 0
