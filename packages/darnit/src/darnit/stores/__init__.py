"""Pluggable per-artifact persistence Protocols.

Feature 033: this sub-package defines four ``typing.Protocol`` classes --
:class:`ProjectStateStore`, :class:`AttestationStore`, :class:`ReportStore`,
:class:`AuditCacheStore` -- each of which sits at an audit-boundary
composition point. Filesystem-backed default implementations ship in
:mod:`darnit.stores.defaults`; alternative backends are third-party plugin
packages that register under ``darnit.stores.<kind>`` entry-point groups
(pattern reused from feature 027's ``darnit.question_resolvers``).

The whole abstraction is orthogonal to the sieve pipeline. Store access
happens ONLY at audit-boundary composition (audit driver, remediation
orchestrator, attestation generator, `.project/` reader/writer, audit-cache
reader/writer). Sieve handlers, remediation handlers, and MCP tools MUST
NOT import from this sub-package (FR-017, enforced mechanically by
``tests/darnit/stores/test_import_isolation.py``).

Every Protocol declares ``close()`` (FR-019). The framework calls
``close()`` exactly once at audit-boundary tear-down via
:class:`_StoreBundle.close_all` -- matches feature 031's
``McpPool.teardown_all()`` pattern for a wider per-audit boundary.
"""

from __future__ import annotations

from darnit.stores.errors import (
    StoreError,
    StoreNameCollision,
    StoreNotInstalled,
    StoreOperationError,
    StoreProtocolMismatch,
)
from darnit.stores.protocols import (
    AttestationStore,
    AuditCacheStore,
    ProjectStateStore,
    ReportStore,
    Store,
)

__all__ = [
    "AttestationStore",
    "AuditCacheStore",
    "ProjectStateStore",
    "ReportStore",
    "Store",
    "StoreError",
    "StoreNameCollision",
    "StoreNotInstalled",
    "StoreOperationError",
    "StoreProtocolMismatch",
]
