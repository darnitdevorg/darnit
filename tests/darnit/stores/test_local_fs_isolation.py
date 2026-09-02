"""Isolation checks: redirecting one kind MUST NOT redirect others.

SC-007: `.project/` stays in the repo even when other kinds are
routed to outside-repo backends. FR-005: no double-writes.

Phase 3 T011 covers attestation-only redirect; Phase 4 T021 adds
report+cache; Phase 5 T030 adds the user-local variant.
"""

from __future__ import annotations

from pathlib import Path

from darnit.config.framework_schema import StoreBlock, StoresConfig
from darnit.stores.defaults import (
    FilesystemAttestationStore,
    FilesystemAuditCacheStore,
    FilesystemProjectStateStore,
    FilesystemReportStore,
    LocalFsAttestationStore,
    LocalFsAuditCacheStore,
    LocalFsReportStore,
    UserLocalAttestationStore,
)
from darnit.stores.selection import resolve_stores


def test_only_attestation_redirects(tmp_path: Path) -> None:
    """T011: `[stores.attestation] backend = "local-fs"` and no other
    `[stores.*]` block set. Only attestation gets the LocalFs* class;
    everything else stays on the pre-feature filesystem default."""
    att_root = tmp_path / "atts-outside"
    config = StoresConfig(
        attestation=StoreBlock(backend="local-fs", root=str(att_root)),
    )
    bundle = resolve_stores(config, repo_path=tmp_path)

    assert isinstance(bundle.attestation, LocalFsAttestationStore)
    assert isinstance(bundle.report, FilesystemReportStore)
    assert isinstance(bundle.cache, FilesystemAuditCacheStore)
    assert isinstance(bundle.project, FilesystemProjectStateStore)


def test_report_and_cache_isolation(tmp_path: Path) -> None:
    """T021: `[stores.report]` + `[stores.cache]` set to `local-fs`, others
    unset. Only those two redirect; attestation + project stay on the
    in-repo default (SC-007 for the report+cache pair)."""
    report_root = tmp_path / "reports-outside"
    cache_root = tmp_path / "cache-outside"
    config = StoresConfig(
        report=StoreBlock(backend="local-fs", root=str(report_root)),
        cache=StoreBlock(backend="local-fs", root=str(cache_root)),
    )
    bundle = resolve_stores(config, repo_path=tmp_path)

    assert isinstance(bundle.report, LocalFsReportStore)
    assert isinstance(bundle.cache, LocalFsAuditCacheStore)
    assert isinstance(bundle.attestation, FilesystemAttestationStore)
    assert isinstance(bundle.project, FilesystemProjectStateStore)


def test_user_local_attestation_project_stays_in_repo(tmp_path: Path) -> None:
    """T030: `[stores.attestation] backend = "user-local"` and no other
    `[stores.*]` block set. `bundle.project` is still the in-repo
    `FilesystemProjectStateStore` (SC-007 for the user-local variant).

    Uses `resolve_stores` selection only -- we don't run an audit here,
    so the platform-computed root of `UserLocalAttestationStore` is
    never actually written to."""
    config = StoresConfig(
        attestation=StoreBlock(backend="user-local"),
    )
    bundle = resolve_stores(config, repo_path=tmp_path)

    assert isinstance(bundle.attestation, UserLocalAttestationStore)
    assert isinstance(bundle.project, FilesystemProjectStateStore)
    # `bundle.project` uses the audit's `repo_path` as its root, which
    # in this test is `tmp_path` -- so `.project/` would live under
    # `tmp_path`, NOT under the user-local platform root.
    assert bundle.project._repo_path == tmp_path
