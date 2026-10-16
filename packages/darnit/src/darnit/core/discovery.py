"""Plugin discovery for darnit compliance implementations.

This module discovers installed compliance implementations via Python entry points.
Implementations register under the 'darnit.implementations' group.

darnit does not verify plugin signatures (framework-design 6.6). The operator's
``[plugins] allowed`` list decides which entry points are loaded at all.
"""

from collections.abc import Iterable

from .logging import get_logger
from .plugin import ComplianceImplementation

logger = get_logger("core.discovery")

# Cache for discovered implementations
_implementations: dict[str, ComplianceImplementation] | None = None
_implementation_packages: frozenset[str] = frozenset()

# Entry point names the operator allows; None allows every installed plugin.
_allowed: frozenset[str] | None = None


def set_allowed_plugins(names: Iterable[str] | None) -> None:
    """Load only these ``darnit.implementations`` and ``darnit.frameworks`` entry points.

    Applied from operator configuration ``[plugins] allowed`` (framework-design
    6.6). An empty or ``None`` list allows every installed plugin. Changing the
    list clears the implementation and framework caches so the next lookup
    loads only allowed entry points.
    """
    global _allowed
    allowed = frozenset(names) if names else None
    if allowed == _allowed:
        return
    _allowed = allowed
    clear_cache()
    from .registry import get_plugin_registry

    get_plugin_registry().clear_cache()


def plugin_allowed(entry_point_name: str) -> bool:
    """Whether the operator allows the plugin entry point with this name to load."""
    return _allowed is None or entry_point_name in _allowed


def discover_implementations() -> dict[str, ComplianceImplementation]:
    """Discover compliance implementations from entry points the operator allows."""
    global _implementations, _implementation_packages

    if _implementations is not None:
        return _implementations

    _implementations = {}
    packages: set[str] = set()

    from importlib.metadata import entry_points

    for ep in entry_points(group="darnit.implementations"):
        if not plugin_allowed(ep.name):
            logger.debug(f"Not loading implementation {ep.name}: not in plugins.allowed")
            continue
        try:
            # Load the entry point (calls the register() function)
            register_func = ep.load()
            impl = register_func()

            if isinstance(impl, ComplianceImplementation):
                _implementations[impl.name] = impl
                packages.add(ep.module.partition(".")[0])
                logger.info(f"Discovered implementation: {impl.name} v{impl.version}")
            else:
                logger.warning(
                    f"Entry point {ep.name} returned {type(impl)}, "
                    f"expected ComplianceImplementation"
                )

        except (ImportError, AttributeError, TypeError) as e:
            logger.error(f"Failed to load implementation {ep.name}: {e}")
            continue
        except Exception as e:
            logger.error(f"Error occurred while loading plugin '{ep.name}': {e}")
            continue

    _implementation_packages = frozenset(packages)
    logger.info(f"Discovered {len(_implementations)} implementation(s)")
    return _implementations


def implementation_packages() -> frozenset[str]:
    """Top-level packages of the discovered implementations' entry points.

    Read from entry point metadata (``darnit_csl:register`` gives
    ``darnit_csl``), so the framework names no implementation package
    itself. Only implementations that discovery accepted are included.
    """
    discover_implementations()
    return _implementation_packages


def get_implementation(name: str) -> ComplianceImplementation | None:
    """Get a specific implementation by name.

    Args:
        name: Implementation name (e.g., 'openssf-baseline')

    Returns:
        Implementation instance or None if not found.
    """
    implementations = discover_implementations()
    return implementations.get(name)


def register_implementation_handlers(framework_name: str | None) -> bool:
    """Register a framework implementation's custom sieve handlers.

    Plugin packages that ship Python sieve handlers (as opposed to controls
    built only from the built-in handlers) expose them through
    ``register_handlers()``. Until that runs, TOML controls referencing a
    plugin handler by short name resolve to nothing and the orchestrator
    falls through to `manual`, producing a WARN that looks like "we could
    not verify" rather than "this handler was never loaded" (issue #427).

    Idempotent: the underlying registry overwrites by name, and
    implementations are cached, so repeat calls are cheap and safe.

    Args:
        framework_name: Implementation name (e.g. ``"reproducibility"``).
            ``None`` is accepted and is a no-op, so callers that may not
            have resolved a framework do not need to guard.

    Returns:
        True if handlers were registered, False if there was nothing to do
        (no framework name, no such implementation, or the implementation
        exposes neither ``register_handlers`` nor the compatibility name
        ``register_sieve_handlers``).
    """
    if not framework_name:
        return False

    impl = get_implementation(framework_name)
    if impl is None:
        logger.debug("No implementation found for '%s'", framework_name)
        return False

    # register_handlers() is the protocol hook (framework-design 6.4, #451).
    # register_sieve_handlers is accepted for compatibility with out-of-tree
    # plugins written before the hook was standardized; it is not a supported
    # choice, and no in-tree plugin uses it. A plugin defining both has each
    # called. Calling here, rather than relying on a plugin's register()
    # entry point, keeps registration independent of the discovery cache
    # (#427). hasattr per Constitution Principle I: missing methods degrade,
    # never crash.
    methods = [getattr(impl, name) for name in ("register_sieve_handlers", "register_handlers") if hasattr(impl, name)]
    if not methods:
        return False

    try:
        for method in methods:
            method()
    except Exception as err:  # noqa: BLE001 - a bad plugin must not kill the audit
        logger.warning(
            "Failed to register handlers for '%s': %s: %s",
            framework_name,
            type(err).__name__,
            err,
        )
        return False

    logger.debug("Registered handlers for '%s'", framework_name)
    return True


def clear_cache() -> None:
    """Clear the implementation cache.

    Useful for testing or when implementations may have changed.
    """
    global _implementations, _implementation_packages
    _implementations = None
    _implementation_packages = frozenset()


__all__ = [
    "clear_cache",
    "discover_implementations",
    "get_implementation",
    "implementation_packages",
    "plugin_allowed",
    "register_implementation_handlers",
    "set_allowed_plugins",
]
