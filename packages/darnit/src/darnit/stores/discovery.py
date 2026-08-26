"""Entry-point discovery for pluggable store backends.

Feature 033 T014 (research decision R-003). Matches the pattern feature
027's :mod:`darnit.harness.resolver_discovery` established for the
``darnit.question_resolvers`` group, adapted for the four store groups
plus name-collision detection (FR-009).

Discovery runs exactly once per process. Results are cached in a
module-level dict keyed by entry-point group name; subsequent calls
return the cached mapping. This locks FR-005's "at framework-load time"
contract without requiring the caller to cache separately.
"""

from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING

from darnit.core.logging import get_logger
from darnit.stores.errors import StoreNameCollision

if TYPE_CHECKING:
    from darnit.stores.protocols import Store

logger = get_logger("stores.discovery")

STORE_ENTRY_POINT_GROUPS: tuple[str, ...] = (
    "darnit.stores.project",
    "darnit.stores.attestation",
    "darnit.stores.report",
    "darnit.stores.cache",
)

_DISCOVERY_CACHE: dict[str, dict[str, type[Store]]] = {}


def discover_stores(group: str) -> dict[str, type[Store]]:
    """Discover backend classes registered under ``group``.

    Returns a mapping from entry-point name to the backend class the
    entry point points at. The class is loaded but NOT instantiated;
    instantiation happens in :mod:`darnit.stores.selection` with the
    backend-specific kwargs from the operator's TOML block.

    Broken entry points (raise on ``ep.load()``) are logged as WARNING
    and skipped -- one bad plugin does not blank the discovery result
    for the whole group. Name collisions (FR-009) raise
    :class:`StoreNameCollision` immediately; there is no implicit
    "last wins" resolution.

    Args:
        group: One of :data:`STORE_ENTRY_POINT_GROUPS`.

    Returns:
        Mapping ``entry_point_name -> backend_class``. Cached per group
        for the process lifetime.

    Raises:
        StoreNameCollision: two entry points under ``group`` register
            the same short name.
    """
    cached = _DISCOVERY_CACHE.get(group)
    if cached is not None:
        return cached

    found: dict[str, type[Store]] = {}
    source: dict[str, str] = {}  # name -> package for collision messages

    try:
        eps = metadata.entry_points(group=group)
    except TypeError:
        # Python 3.9 kwargs-not-supported shape; darnit requires 3.11+
        # so this is a defensive fallback.
        eps = [
            ep
            for ep in metadata.entry_points()  # type: ignore[call-arg]
            if getattr(ep, "group", None) == group
        ]

    for ep in eps:
        # Resolve the source package name for collision messages.
        pkg = getattr(ep, "dist", None)
        pkg_name = pkg.metadata["Name"] if pkg is not None else str(ep.value)

        if ep.name in found:
            raise StoreNameCollision(
                group=group,
                name=ep.name,
                first=source.get(ep.name, "unknown"),
                second=pkg_name,
            )

        try:
            cls = ep.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "store entry point %r under %s failed to load: %s: %s",
                ep.name,
                group,
                type(exc).__name__,
                exc,
            )
            continue

        found[ep.name] = cls
        source[ep.name] = pkg_name

    _DISCOVERY_CACHE[group] = found
    return found


def _reset_discovery_cache() -> None:
    """Test-only helper to clear the discovery cache.

    Not part of the public API. Tests that mock entry-point registration
    call this between cases so each case sees a fresh discovery.
    """
    _DISCOVERY_CACHE.clear()


__all__ = ["STORE_ENTRY_POINT_GROUPS", "discover_stores"]
