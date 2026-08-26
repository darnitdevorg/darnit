"""Exception hierarchy for the pluggable-stores abstraction (feature 033).

Each concrete class corresponds to a spec-level Functional Requirement:

* :class:`StoreNotInstalled` -- FR-008 (fail-fast on unresolvable backend).
* :class:`StoreProtocolMismatch` -- FR-002 + FR-008 (runtime Protocol check).
* :class:`StoreNameCollision` -- FR-009 (two plugins register the same name).
* :class:`StoreOperationError` -- FR-011 (backend-side operational failure).

All four inherit from :class:`StoreError`, the base class the framework can
catch when it wants to distinguish store-side failures from arbitrary
Python errors.
"""

from __future__ import annotations


class StoreError(Exception):
    """Base class for every store-related failure."""


class StoreNotInstalled(StoreError):
    """Selected backend is not registered under the target entry-point group.

    Raised by the selection layer (:mod:`darnit.stores.selection`) at
    framework-config load time, per FR-008 (fail-fast on unresolvable
    backend selection). The framework MUST NOT silently fall back to the
    filesystem default (FR-012); the operator's selection is honored to
    the point of failure.
    """

    def __init__(self, group: str, name: str, available: list[str]) -> None:
        alternatives = ", ".join(sorted(available)) if available else "(none installed)"
        super().__init__(
            f"no store registered under {group!r} with name {name!r}; "
            f"installed alternatives: {alternatives}"
        )
        self.group = group
        self.name = name
        self.available = list(available)


class StoreProtocolMismatch(StoreError):
    """Registered class does not satisfy the target Protocol.

    Raised at selection / instantiation time when
    ``isinstance(instance, ProtocolClass)`` fails, per FR-002 (runtime
    Protocol conformance) and FR-008 (fail-fast).
    """

    def __init__(self, group: str, name: str, cls: type, missing: list[str]) -> None:
        super().__init__(
            f"{group}/{name} -> {cls.__module__}.{cls.__qualname__} does not "
            f"satisfy the Protocol; missing methods: "
            f"{', '.join(missing) if missing else 'unknown'}"
        )
        self.group = group
        self.name = name
        self.cls = cls
        self.missing = list(missing)


class StoreNameCollision(StoreError):
    """Two entry points register the same short name under one group.

    Raised by :func:`darnit.stores.discovery.discover_stores` at framework-
    load time, per FR-009. No implicit "last wins" resolution -- operator
    disambiguation is required.
    """

    def __init__(self, group: str, name: str, first: str, second: str) -> None:
        super().__init__(
            f"two entry points register {name!r} under {group!r}: {first} vs "
            f"{second}. Uninstall one, or rename the entry point in one "
            f"plugin's pyproject.toml."
        )
        self.group = group
        self.name = name
        self.first = first
        self.second = second


class StoreOperationError(StoreError):
    """Backend-side operational failure at read or write time.

    Raised by store implementations to surface a failed operation to the
    caller (per FR-011). Caller code interprets according to the per-
    Protocol failure semantics documented in
    ``specs/033-pluggable-stores/contracts/*.md``:

    * :class:`darnit.stores.ProjectStateStore` -- read failure -> caller
      resolves affected controls WARN; write failure -> audit-run error.
    * :class:`darnit.stores.AttestationStore` -- write failure -> audit-run
      error with the store surfaced.
    * :class:`darnit.stores.ReportStore` -- write failure -> audit-run error
      with the format name.
    * :class:`darnit.stores.AuditCacheStore` -- MUST NOT raise; caller code
      catches and logs. Best-effort.
    """


__all__ = [
    "StoreError",
    "StoreNameCollision",
    "StoreNotInstalled",
    "StoreOperationError",
    "StoreProtocolMismatch",
]
