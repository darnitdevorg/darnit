"""Store Protocols (feature 033 T008).

Five Protocols implementing the persistence extension surface:

* :class:`Store` -- the shared ``close()`` contract every store carries.
* :class:`ProjectStateStore` -- ``.project/`` project + maintainers I/O.
* :class:`AttestationStore` -- write-only attestation-bundle persistence.
* :class:`ReportStore` -- write-only Markdown/JSON/SARIF audit-report
  persistence.
* :class:`AuditCacheStore` -- read + write for the per-audit-run cache.

Every Protocol is decorated with :func:`typing.runtime_checkable` so
``isinstance(instance, ProtocolClass)`` is a fast Protocol-conformance
check (FR-002). The framework uses this at :func:`darnit.stores.selection.resolve_stores`
time to fail-fast on plugin classes that do not satisfy the Protocol.

See ``specs/033-pluggable-stores/contracts/`` for the per-Protocol contract
docs (TOML surface, method-by-method contracts, per-Protocol failure
semantics from FR-011, and non-goals for v0).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    # Forward references avoid circular import between stores and context.
    from darnit.context.dot_project import MaintainerEntry, ProjectConfig


@runtime_checkable
class Store(Protocol):
    """Base Protocol carrying the shared ``close()`` contract (FR-019).

    Every concrete Store Protocol inherits from this. The framework calls
    :meth:`close` exactly once per instantiated store at audit-boundary
    tear-down via :meth:`darnit.stores.selection._StoreBundle.close_all`.
    """

    def close(self) -> None:
        """Release any resources held by this store.

        Contract (FR-019):

        * MUST be idempotent -- a second call is a no-op, not an error.
        * MUST NOT raise on the "already closed" case.
        * MAY raise on unrecoverable teardown failure (network partition,
          disk full during flush). The framework wraps the call in
          try/except and logs; it does NOT re-raise.
        """
        ...


@runtime_checkable
class ProjectStateStore(Store, Protocol):
    """Read + write for ``.project/project.yaml`` and ``.project/maintainers.yaml``.

    Failure semantics (FR-011):

    * ``read_project`` / ``read_maintainers`` failure -> caller resolves
      affected controls WARN (never silent PASS, never silent FAIL).
    * ``write_project`` / ``write_maintainers`` failure -> caller
      surfaces the error to the operator; the audit-run fails.

    Concurrency: sync in v0. Single-caller assumed within an audit run.
    """

    def read_project(self) -> ProjectConfig | None:
        """Load the project configuration. Return None if not present.

        Raises:
            StoreOperationError: on backend failure that is not "not found".
        """
        ...

    def write_project(self, config: ProjectConfig) -> None:
        """Persist the project configuration.

        Preconditions:
            ``config`` is a valid :class:`~darnit.context.dot_project.ProjectConfig`.

        Raises:
            StoreOperationError: on backend failure.
        """
        ...

    def read_maintainers(self) -> list[MaintainerEntry]:
        """Load the maintainer entries. Empty list if none present.

        Raises:
            StoreOperationError: on backend failure that is not "not found".
        """
        ...

    def write_maintainers(self, entries: list[MaintainerEntry]) -> None:
        """Persist the maintainer entries.

        Raises:
            StoreOperationError: on backend failure.
        """
        ...


@runtime_checkable
class AttestationStore(Store, Protocol):
    """Write-only surface for attestation bundles.

    Failure semantics (FR-011): a raise on ``write`` surfaces as an
    audit-run error naming the store; the attestation is NOT reported as
    persisted. Rationale: an attestation that quietly failed to persist
    is a compliance record that quietly didn't happen. Constitution II
    demands the error be visible.

    Read-back is NOT in v0. Attestations are consumed downstream by
    other tooling (Sigstore, in-toto verifiers); if darnit needs to
    enumerate its own attestations, add ``list_bundles()`` as an
    additive Protocol extension.
    """

    def write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None:
        """Persist an attestation bundle.

        Args:
            bundle_id: Stable, filesystem-safe identifier that correlates
                the bundle with the audit run that produced it.
            bundle_bytes: The serialized attestation.
            content_type: Media type (e.g., ``"application/vnd.in-toto+json"``,
                ``"application/vnd.dev.sigstore.bundle+json"``).

        Raises:
            StoreOperationError: on any backend failure.
        """
        ...


@runtime_checkable
class ReportStore(Store, Protocol):
    """Write surface for audit reports in the three supported formats.

    Format-specific methods (rather than a generic ``write(format, content)``)
    so the "three formats, always these three" invariant is enforceable
    by mypy/pyright. Adding a fourth format is an additive Protocol
    change.

    v0 has no existing report-writing call site to migrate. The Protocol
    exists so downstream features (starting with #341) can write through
    the Protocol without having to introduce the abstraction
    retroactively.

    Failure semantics (FR-011): a raise on ``write_*`` surfaces as an
    audit-run error naming the format.
    """

    def write_markdown(self, report_id: str, content: str) -> None:
        """Persist a Markdown-formatted audit report.

        Raises:
            StoreOperationError: on backend failure.
        """
        ...

    def write_json(self, report_id: str, content: str) -> None:
        """Persist a JSON audit report.

        Raises:
            StoreOperationError: on backend failure.
        """
        ...

    def write_sarif(self, report_id: str, content: str) -> None:
        """Persist a SARIF-formatted audit report.

        Raises:
            StoreOperationError: on backend failure.
        """
        ...


@runtime_checkable
class AuditCacheStore(Store, Protocol):
    """Read + write for the per-audit-run cache.

    Failure semantics (FR-011): cache is **best-effort**. Both
    :meth:`read` and :meth:`write` MUST NOT raise. Backend failures are
    swallowed by the caller (read returns cache-miss; write is logged
    and the audit continues). Rationale: cache is a performance
    optimization, not a correctness requirement. A failing cache write
    leads to an extra audit run -- a slowdown, not a compliance error.

    TTL semantics live in the caller (see :mod:`darnit.core.audit_cache`);
    the store is a dumb read-through / write-through KV.
    """

    def read(self, cache_key: str) -> dict[str, Any] | None:
        """Load a cache envelope. Return None on miss OR on backend failure.

        MUST NOT raise.
        """
        ...

    def write(self, cache_key: str, envelope: dict[str, Any]) -> None:
        """Persist a cache envelope.

        MUST NOT raise. Backend failures are logged; audit continues.
        """
        ...


__all__ = [
    "AttestationStore",
    "AuditCacheStore",
    "ProjectStateStore",
    "ReportStore",
    "Store",
]
