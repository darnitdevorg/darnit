"""US1 isolation: selecting one kind does not affect the others.

Feature 033 T025 / FR-010. When ``[stores.project]`` selects a plugin
but the other three blocks are unset, the resulting bundle must produce
filesystem-default instances for the other three kinds.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from darnit_testchecks.stores import InMemoryProjectStateStore

from darnit.config.framework_schema import StoreBlock, StoresConfig
from darnit.stores.defaults import (
    FilesystemAttestationStore,
    FilesystemAuditCacheStore,
    FilesystemReportStore,
)
from darnit.stores.selection import resolve_stores


class TestUS1Isolation:
    def test_only_project_uses_plugin_others_stay_filesystem(self, tmp_path: Path):
        config = StoresConfig(project=StoreBlock(backend="in-memory"))
        bundle = resolve_stores(config, repo_path=tmp_path)

        assert isinstance(bundle.project, InMemoryProjectStateStore)
        assert isinstance(bundle.attestation, FilesystemAttestationStore)
        assert isinstance(bundle.report, FilesystemReportStore)
        assert isinstance(bundle.cache, FilesystemAuditCacheStore)

    def test_filesystem_defaults_land_on_darnit_subdir(self, tmp_path: Path):
        config = StoresConfig(project=StoreBlock(backend="in-memory"))
        bundle = resolve_stores(config, repo_path=tmp_path)

        # Trigger construction and verify the filesystem defaults were
        # built at their canonical zero-config location. Feature 035
        # rebased the cache default to the legacy tempdir/hash path
        # (SC-008); attestation and report defaults are unchanged.
        att = bundle.attestation
        rep = bundle.report
        cache = bundle.cache
        assert att._root == tmp_path / ".darnit" / "attestations"  # type: ignore[attr-defined]
        assert rep._root == tmp_path / ".darnit" / "reports"  # type: ignore[attr-defined]

        expected_hash = hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest()[:16]
        expected_cache_root = Path(tempfile.gettempdir()) / "darnit" / expected_hash
        assert cache._root == expected_cache_root  # type: ignore[attr-defined]
