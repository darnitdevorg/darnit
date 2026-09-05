"""US2 SC-003 zero-config invariance.

Feature 033 T030. When no ``[stores.*]`` block is present in either the
framework TOML or ``.baseline.toml``, ``resolve_stores`` must produce
the four filesystem defaults and NOT construct any plugin backend.
Pre-feature audit paths (system tempdir cache, on-disk .project/,
attestations to repo root) remain the ground truth for what darnit does
without the feature switched on.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from darnit.stores import discovery
from darnit.stores.defaults import (
    FilesystemAttestationStore,
    FilesystemAuditCacheStore,
    FilesystemProjectStateStore,
    FilesystemReportStore,
)
from darnit.stores.selection import resolve_stores


class TestUS2ZeroConfig:
    def test_none_config_yields_filesystem_defaults_for_all_four(self, tmp_path: Path):
        bundle = resolve_stores(None, repo_path=tmp_path)
        assert isinstance(bundle.project, FilesystemProjectStateStore)
        assert isinstance(bundle.attestation, FilesystemAttestationStore)
        assert isinstance(bundle.report, FilesystemReportStore)
        assert isinstance(bundle.cache, FilesystemAuditCacheStore)

    def test_no_plugin_backend_constructed_under_zero_config(self, tmp_path: Path):
        """SC-003: a plugin registered but not selected must never be built."""
        # Reset cache so we can monkey-inject a fake entry.
        discovery._reset_discovery_cache()
        try:
            construct_calls: list[str] = []

            class FakePlugin:
                def __init__(self, **kwargs) -> None:
                    construct_calls.append("attestation")

                def write(self, bundle_id, bundle_bytes, content_type):
                    return None

                def close(self):
                    return None

            # Seed the per-process discovery cache directly so
            # `discover_stores("darnit.stores.attestation")` sees the fake.
            discovery._DISCOVERY_CACHE["darnit.stores.attestation"] = {"fake-plugin": FakePlugin}

            bundle = resolve_stores(None, repo_path=tmp_path)
            # Force realistic access on all four kinds.
            _ = bundle.project
            _ = bundle.attestation
            _ = bundle.report
            _ = bundle.cache
            assert construct_calls == [], (
                "A plugin backend that was NOT selected in TOML was still "
                "constructed under zero-config -- SC-003 violation."
            )
        finally:
            discovery._reset_discovery_cache()

    def test_filesystem_defaults_use_canonical_darnit_paths(self, tmp_path: Path):
        """Zero-config on-disk paths match the pre-feature convention.

        Feature 035 SC-008: cache default moved to the legacy
        ``<tempdir>/darnit/<sha256(abspath(repo))[:16]>`` location so the
        pre-feature ``darnit.core.audit_cache`` on-disk path is preserved
        byte-for-byte after the store-abstraction routing. Attestation
        and report defaults are unchanged.
        """
        bundle = resolve_stores(None, repo_path=tmp_path)
        assert bundle.attestation._root == tmp_path / ".darnit" / "attestations"  # type: ignore[attr-defined]
        assert bundle.report._root == tmp_path / ".darnit" / "reports"  # type: ignore[attr-defined]

        expected_hash = hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest()[:16]
        expected_cache_root = Path(tempfile.gettempdir()) / "darnit" / expected_hash
        assert bundle.cache._root == expected_cache_root  # type: ignore[attr-defined]
