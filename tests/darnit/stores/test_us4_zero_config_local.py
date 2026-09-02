"""Feature 034 T033 / US4: zero-config invariant preserved.

With no `[stores.*]` block, `resolve_stores` MUST return the pre-
feature `Filesystem*Store` classes for all four kinds. Neither the
new `LocalFs*Store` nor the new `UserLocal*Store` should be
instantiated. This is the constitutional invariant that lets us ship
outside-repo backends without changing any operator's day-to-day
behavior.
"""

from __future__ import annotations

from pathlib import Path

from darnit.stores import discovery
from darnit.stores.defaults import (
    FilesystemAttestationStore,
    FilesystemAuditCacheStore,
    FilesystemProjectStateStore,
    FilesystemReportStore,
    LocalFsAttestationStore,
    LocalFsAuditCacheStore,
    LocalFsReportStore,
    UserLocalAttestationStore,
    UserLocalAuditCacheStore,
    UserLocalReportStore,
)
from darnit.stores.selection import resolve_stores


def test_none_config_yields_filesystem_defaults(tmp_path: Path) -> None:
    """None config -> all four kinds resolve to `Filesystem*Store`."""
    discovery._reset_discovery_cache()
    bundle = resolve_stores(None, repo_path=tmp_path)

    assert isinstance(bundle.attestation, FilesystemAttestationStore)
    assert isinstance(bundle.report, FilesystemReportStore)
    assert isinstance(bundle.cache, FilesystemAuditCacheStore)
    assert isinstance(bundle.project, FilesystemProjectStateStore)


def test_none_config_does_not_instantiate_new_backends(tmp_path: Path) -> None:
    """No configured `[stores.*]` -> the new feature 034 backend classes
    are never constructed. Confirms FR-006 / SC-003 at the object level."""
    discovery._reset_discovery_cache()
    bundle = resolve_stores(None, repo_path=tmp_path)

    for backend in (bundle.attestation, bundle.report, bundle.cache, bundle.project):
        assert not isinstance(backend, LocalFsAttestationStore)
        assert not isinstance(backend, LocalFsReportStore)
        assert not isinstance(backend, LocalFsAuditCacheStore)
        assert not isinstance(backend, UserLocalAttestationStore)
        assert not isinstance(backend, UserLocalReportStore)
        assert not isinstance(backend, UserLocalAuditCacheStore)
