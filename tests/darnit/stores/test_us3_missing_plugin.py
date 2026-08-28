"""US3 T036: unknown backend raises before any control runs (SC-007).

Feature 033 FR-008. Selecting a backend name that's not registered
must raise :class:`StoreNotInstalled` at ``resolve_stores`` time with a
message that names the backend, the group, and the alternatives.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestUS3MissingPlugin:
    def test_unknown_backend_raises_store_not_installed(self, tmp_path: Path):
        from darnit.config.framework_schema import StoreBlock, StoresConfig
        from darnit.stores import discovery
        from darnit.stores.errors import StoreNotInstalled
        from darnit.stores.selection import resolve_stores

        discovery._reset_discovery_cache()
        config = StoresConfig(
            attestation=StoreBlock(backend="does-not-exist")
        )
        with pytest.raises(StoreNotInstalled) as exc:
            resolve_stores(config, repo_path=tmp_path)

        assert exc.value.name == "does-not-exist"
        assert exc.value.group == "darnit.stores.attestation"
        # Message references the group + name so operators can diagnose.
        msg = str(exc.value)
        assert "does-not-exist" in msg
        assert "darnit.stores.attestation" in msg
