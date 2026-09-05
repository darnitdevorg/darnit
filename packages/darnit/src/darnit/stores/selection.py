"""TOML block -> instantiated backend resolution (feature 033 T015 + T025a).

Consumes the four ``StoresConfig`` fields, looks up each requested
backend via :mod:`darnit.stores.discovery`, and returns a
:class:`_StoreBundle` whose per-kind fields lazily instantiate the store
on first access.

Two-phase design (T025a):

* At ``resolve_stores`` time, we do all *validation*:
  discover the plugin, verify its class shape satisfies the target
  Protocol, and construct a factory closure. This preserves FR-008 /
  SC-007 (unknown backend or Protocol mismatch raises BEFORE any control
  runs).
* At first access of ``bundle.project`` / ``.attestation`` / ``.report``
  / ``.cache``, the factory fires and the store is memoized. This
  preserves FR-006 / SC-004 (an audit that never touches an artifact
  class never constructs its store).

``close_all()`` iterates only the stores that were actually
instantiated; a bundle whose ``.cache`` was never touched will never
call ``.cache.close()``. Idempotent per FR-019.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger
from darnit.stores.defaults import (
    FilesystemAttestationStore,
    FilesystemAuditCacheStore,
    FilesystemProjectStateStore,
    FilesystemReportStore,
)
from darnit.stores.discovery import discover_stores
from darnit.stores.errors import StoreNotInstalled, StoreProtocolMismatch
from darnit.stores.protocols import (
    AttestationStore,
    AuditCacheStore,
    ProjectStateStore,
    ReportStore,
)

logger = get_logger("stores.selection")

_STORE_KINDS = ("project", "attestation", "report", "cache")

_KIND_META = {
    "project": ("darnit.stores.project", ProjectStateStore),
    "attestation": ("darnit.stores.attestation", AttestationStore),
    "report": ("darnit.stores.report", ReportStore),
    "cache": ("darnit.stores.cache", AuditCacheStore),
}


class _StoreBundle:
    """Lazy-instantiating holder for the four resolved stores.

    Fields are exposed as read-only properties (``project``,
    ``attestation``, ``report``, ``cache``). On first access, the
    corresponding factory fires and the returned instance is memoized.
    ``close_all()`` closes only stores that were actually accessed.
    """

    def __init__(self, factories: dict[str, Callable[[], Any]]) -> None:
        self._factories = dict(factories)
        self._instances: dict[str, Any] = {}

    def _get(self, kind: str) -> Any:
        if kind not in self._instances:
            factory = self._factories.get(kind)
            if factory is None:
                return None
            self._instances[kind] = factory()
        return self._instances[kind]

    @property
    def project(self) -> ProjectStateStore | None:
        return self._get("project")

    @property
    def attestation(self) -> AttestationStore | None:
        return self._get("attestation")

    @property
    def report(self) -> ReportStore | None:
        return self._get("report")

    @property
    def cache(self) -> AuditCacheStore | None:
        return self._get("cache")

    def is_instantiated(self, kind: str) -> bool:
        """Return True if ``kind``'s store was actually constructed."""
        return kind in self._instances

    def close_all(self) -> None:
        """Call ``close()`` on every INSTANTIATED store, then clear.

        Skips kinds that were never accessed (SC-004: no ghost close on
        a store the run never built). Per-store failures are logged and
        swallowed. Idempotent (FR-019).
        """
        for kind, store in list(self._instances.items()):
            try:
                store.close()
            except Exception as err:  # noqa: BLE001
                logger.warning(
                    "close() on %s store raised %s: %s",
                    kind,
                    type(err).__name__,
                    err,
                )
        self._instances.clear()


def resolve_stores(
    stores_config: Any,
    *,
    repo_path: Path,
    attestation_root: Path | None = None,
    report_root: Path | None = None,
    cache_root: Path | None = None,
) -> _StoreBundle:
    """Validate the four store selections and return a lazy bundle.

    Args:
        stores_config: A :class:`darnit.config.framework_schema.StoresConfig`
            (or None for zero-config).
        repo_path: Repository root; passed to filesystem defaults that
            need it.
        attestation_root, report_root, cache_root: Optional overrides for
            filesystem-default roots. When None, uses
            ``<repo_path>/.darnit/{attestations,reports}`` for the first two
            and ``<tempfile.gettempdir()>/darnit/<sha256(abspath(repo))[:16]>``
            for the cache (feature 035: matches the pre-feature
            :mod:`darnit.core.audit_cache` on-disk path).

    Returns:
        A :class:`_StoreBundle` whose fields lazily instantiate on first
        access. If the run never touches an artifact class its store is
        never constructed.

    Raises:
        StoreNotInstalled: A selection names a backend not registered.
        StoreProtocolMismatch: A registered class does not satisfy the
            target Protocol at the class level.
    """
    attestation_root = attestation_root or (repo_path / ".darnit" / "attestations")
    report_root = report_root or (repo_path / ".darnit" / "reports")
    if cache_root is None:
        # Feature 035: default cache lands at the legacy per-repo tempdir path
        # (<tempdir>/darnit/<sha256(abspath(repo))[:16]>) so bundle.cache's
        # default backend produces the same on-disk path as the pre-feature
        # audit_cache wrapper. The wrapper passes cache_key = "audit-cache"
        # in the default-store case, yielding <root>/audit-cache.json.
        _repo_hash = hashlib.sha256(str(repo_path.resolve()).encode()).hexdigest()[:16]
        cache_root = Path(tempfile.gettempdir()) / "darnit" / _repo_hash

    default_factories = {
        "project": lambda: FilesystemProjectStateStore(repo_path),
        "attestation": lambda: FilesystemAttestationStore(attestation_root),
        "report": lambda: FilesystemReportStore(report_root),
        "cache": lambda: FilesystemAuditCacheStore(cache_root),
    }

    factories: dict[str, Callable[[], Any]] = {}
    for kind in _STORE_KINDS:
        block = None if stores_config is None else getattr(stores_config, kind, None)
        if block is None:
            factories[kind] = default_factories[kind]
        else:
            factories[kind] = _validate_and_make_factory(kind, block, repo_path=repo_path)

    return _StoreBundle(factories)


def _validate_and_make_factory(kind: str, block: Any, *, repo_path: Path) -> Callable[[], Any]:
    """Discover the plugin, validate its class shape, return a factory.

    Validation runs eagerly (before the factory fires) so a bad
    selection raises before any control runs (FR-008, SC-007). The
    factory closure captures kwargs and defers ``cls(...)`` until the
    bundle actually needs the store.
    """
    group, protocol_cls = _KIND_META[kind]
    registered = discover_stores(group)
    name = block.backend
    if name not in registered:
        raise StoreNotInstalled(
            group=group,
            name=name,
            available=list(registered.keys()),
        )
    cls = registered[name]

    # Class-shape Protocol check (avoids instantiation).
    missing = [attr for attr in _protocol_methods(protocol_cls) if not hasattr(cls, attr)]
    if missing:
        raise StoreProtocolMismatch(
            group=group,
            name=name,
            cls=cls,
            missing=missing,
        )

    kwargs = {k: v for k, v in dict(block.model_extra or {}).items() if k != "backend"}
    kwargs.setdefault("repo_path", repo_path)

    def _factory() -> Any:
        try:
            return cls(**kwargs)
        except TypeError:
            fallback = {k: v for k, v in kwargs.items() if k != "repo_path"}
            return cls(**fallback)

    return _factory


def _protocol_methods(protocol_cls: type) -> list[str]:
    """Enumerate the callable attribute names a Protocol requires."""
    names: list[str] = []
    for attr in dir(protocol_cls):
        if attr.startswith("_"):
            continue
        if not callable(getattr(protocol_cls, attr, None)):
            continue
        names.append(attr)
    return names


__all__ = ["_StoreBundle", "resolve_stores"]
