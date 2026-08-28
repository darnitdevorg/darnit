"""Unit tests for the store Protocol classes (feature 033 T009).

Verifies runtime_checkable conformance across all five Protocols, the
close() inheritance chain, and negative isinstance-checks for classes
missing methods.
"""

from __future__ import annotations

from darnit.stores.protocols import (
    AttestationStore,
    AuditCacheStore,
    ProjectStateStore,
    ReportStore,
    Store,
)

# ---------------------------------------------------------------------------
# Store base -- close() must exist on any store
# ---------------------------------------------------------------------------


class _MinimalStore:
    def close(self) -> None: ...


class _NoCloseStore:
    pass


class TestStoreBase:
    def test_close_only_satisfies_store(self):
        assert isinstance(_MinimalStore(), Store)

    def test_missing_close_fails_isinstance(self):
        assert not isinstance(_NoCloseStore(), Store)


# ---------------------------------------------------------------------------
# ProjectStateStore
# ---------------------------------------------------------------------------


class _MinimalProjectStateStore:
    def close(self) -> None: ...
    def read_project(self): return None
    def write_project(self, config): pass
    def read_maintainers(self): return []
    def write_maintainers(self, entries): pass


class _ProjectStoreMissingWriteMaintainers:
    def close(self) -> None: ...
    def read_project(self): return None
    def write_project(self, config): pass
    def read_maintainers(self): return []
    # write_maintainers missing


class TestProjectStateStore:
    def test_minimal_satisfies_protocol(self):
        assert isinstance(_MinimalProjectStateStore(), ProjectStateStore)

    def test_missing_method_fails_isinstance(self):
        assert not isinstance(
            _ProjectStoreMissingWriteMaintainers(), ProjectStateStore
        )

    def test_inherits_store(self):
        # Every ProjectStateStore is also a Store.
        assert isinstance(_MinimalProjectStateStore(), Store)


# ---------------------------------------------------------------------------
# AttestationStore
# ---------------------------------------------------------------------------


class _MinimalAttestationStore:
    def close(self) -> None: ...
    def write(self, bundle_id, bundle_bytes, content_type): pass


class TestAttestationStore:
    def test_minimal_satisfies_protocol(self):
        assert isinstance(_MinimalAttestationStore(), AttestationStore)

    def test_inherits_store(self):
        assert isinstance(_MinimalAttestationStore(), Store)


# ---------------------------------------------------------------------------
# ReportStore
# ---------------------------------------------------------------------------


class _MinimalReportStore:
    def close(self) -> None: ...
    def write_markdown(self, report_id, content): pass
    def write_json(self, report_id, content): pass
    def write_sarif(self, report_id, content): pass


class _ReportStoreMissingSarif:
    def close(self) -> None: ...
    def write_markdown(self, report_id, content): pass
    def write_json(self, report_id, content): pass
    # write_sarif missing


class TestReportStore:
    def test_minimal_satisfies_protocol(self):
        assert isinstance(_MinimalReportStore(), ReportStore)

    def test_missing_sarif_fails_isinstance(self):
        assert not isinstance(_ReportStoreMissingSarif(), ReportStore)


# ---------------------------------------------------------------------------
# AuditCacheStore
# ---------------------------------------------------------------------------


class _MinimalAuditCacheStore:
    def close(self) -> None: ...
    def read(self, cache_key): return None
    def write(self, cache_key, envelope): pass


class TestAuditCacheStore:
    def test_minimal_satisfies_protocol(self):
        assert isinstance(_MinimalAuditCacheStore(), AuditCacheStore)

    def test_inherits_store(self):
        assert isinstance(_MinimalAuditCacheStore(), Store)


# ---------------------------------------------------------------------------
# Cross-Protocol isolation -- a class satisfying one Protocol does not
# accidentally satisfy the others (unless it duplicates their methods).
# ---------------------------------------------------------------------------


class TestCrossIsolation:
    def test_project_store_is_not_attestation_store(self):
        # ProjectStateStore has read/write_project + read/write_maintainers;
        # AttestationStore has write(bundle_id, bytes, content_type). No
        # method overlap, so no accidental cross-satisfaction.
        instance = _MinimalProjectStateStore()
        assert isinstance(instance, ProjectStateStore)
        assert not isinstance(instance, AttestationStore)

    def test_attestation_store_is_not_report_store(self):
        instance = _MinimalAttestationStore()
        assert isinstance(instance, AttestationStore)
        assert not isinstance(instance, ReportStore)

    def test_report_store_is_not_audit_cache_store(self):
        instance = _MinimalReportStore()
        assert isinstance(instance, ReportStore)
        assert not isinstance(instance, AuditCacheStore)


# ---------------------------------------------------------------------------
# All Protocols are marked runtime_checkable (introspection-level check)
# ---------------------------------------------------------------------------


class TestRuntimeCheckable:
    def test_all_five_are_runtime_checkable(self):
        # A runtime_checkable Protocol carries the _is_runtime_protocol
        # attribute set to True.
        for cls in (Store, ProjectStateStore, AttestationStore, ReportStore, AuditCacheStore):
            assert getattr(cls, "_is_runtime_protocol", False), (
                f"{cls.__name__} is not runtime_checkable"
            )
