"""US3 T037: registered class not satisfying Protocol raises at selection time.

Feature 033 FR-002 + FR-008. A plugin whose class shape is missing a
required Protocol method (e.g., ``close``) must raise
:class:`StoreProtocolMismatch` at ``resolve_stores`` time and name the
missing methods.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestUS3ProtocolMismatch:
    def test_class_missing_close_raises_protocol_mismatch(self, tmp_path: Path):
        from darnit.config.framework_schema import StoreBlock, StoresConfig
        from darnit.stores import discovery
        from darnit.stores.errors import StoreProtocolMismatch
        from darnit.stores.selection import resolve_stores

        class BrokenReportPlugin:
            def __init__(self, **kw) -> None: pass
            def write_markdown(self, r, c): pass
            def write_json(self, r, c): pass
            def write_sarif(self, r, c): pass
            # close() intentionally missing

        discovery._reset_discovery_cache()
        # Monkey-register via the cache so we don't need a real
        # entry point.
        discovery._DISCOVERY_CACHE["darnit.stores.report"] = {
            "broken": BrokenReportPlugin
        }

        config = StoresConfig(report=StoreBlock(backend="broken"))
        with pytest.raises(StoreProtocolMismatch) as exc:
            resolve_stores(config, repo_path=tmp_path)

        assert "close" in exc.value.missing
        assert exc.value.name == "broken"
        discovery._reset_discovery_cache()
