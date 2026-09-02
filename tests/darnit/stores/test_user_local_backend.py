"""Backend tests for `user-local` (feature 034 T028 + T029)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from darnit.config.framework_schema import StoreBlock, StoresConfig
from darnit.stores.defaults import platform_paths
from darnit.stores.defaults.user_local import (
    UserLocalAttestationStore,
    UserLocalAuditCacheStore,
    UserLocalReportStore,
)
from darnit.stores.errors import StoreNotInstalled
from darnit.stores.selection import resolve_stores

_LOGGER = "darnit.stores.local"


class TestUserLocalAttestation:
    def test_round_trip_at_platform_data_root_for_attestations(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """T028 (a): pin the platform data root into `tmp_path` via
        `platform.system() -> "Linux"` + `XDG_DATA_HOME=<tmp_path>`
        so the write lands somewhere reproducible."""
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Linux"
        )
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        store = UserLocalAttestationStore()
        store.write("acme", b'{"x":1}', "application/vnd.in-toto+json")
        target = tmp_path / "darnit" / "attestations" / "acme.intoto.json"
        assert target.exists()

    def test_explicit_root_kwarg_warn_and_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog,
    ) -> None:
        """T028 (b): passing `root` to user-local logs a warning and
        uses the platform default anyway."""
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Linux"
        )
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        bogus = "/never/written/to"

        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            store = UserLocalAttestationStore(root=bogus)

        assert any(
            "user-local backend ignores" in r.getMessage()
            for r in caplog.records
        )
        # The store's write path uses the platform root.
        store.write("acme", b"x", "application/vnd.in-toto+json")
        assert (
            tmp_path / "darnit" / "attestations" / "acme.intoto.json"
        ).exists()
        assert not Path(bogus).exists()

    def test_info_log_uses_user_local_backend_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog,
    ) -> None:
        """T028 (c): SC-009 backend name correctness. Info log line MUST
        include `(user-local)`, not `(local-fs)`."""
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Linux"
        )
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        store = UserLocalAttestationStore()
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            store.write("acme", b'{"x":1}', "application/vnd.in-toto+json")

        msgs = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
        assert any(m.startswith("wrote attestation (user-local): ") for m in msgs)
        assert not any("(local-fs)" in m for m in msgs)


class TestUserLocalReport:
    def test_round_trip_at_platform_data_root_for_reports(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Linux"
        )
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        store = UserLocalReportStore()
        store.write_markdown("run-1", "# body")
        assert (
            tmp_path / "darnit" / "reports" / "run-1.md"
        ).exists()


class TestUserLocalCache:
    def test_round_trip_at_platform_cache_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Linux"
        )
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        store = UserLocalAuditCacheStore()
        store.write("k1", {"x": 1})
        assert (
            tmp_path / "darnit" / "audit-cache" / "k1.json"
        ).exists()
        assert store.read("k1") == {"x": 1}


class TestUserLocalNotRegisteredForProject:
    """T029: FR-009 enforced at discovery layer."""

    def test_stores_project_backend_user_local_raises(
        self, tmp_path: Path
    ) -> None:
        from darnit.stores import discovery

        # Reset cache so a stale earlier lookup doesn't mask the intent.
        discovery._reset_discovery_cache()

        config = StoresConfig(
            project=StoreBlock(backend="user-local"),
        )
        with pytest.raises(StoreNotInstalled) as exc_info:
            resolve_stores(config, repo_path=tmp_path)

        err = exc_info.value
        # StoreNotInstalled carries `.name` and `.group`.
        assert err.name == "user-local"
        assert err.group == "darnit.stores.project"
