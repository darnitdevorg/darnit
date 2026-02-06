"""Plugin discovery for darnit compliance implementations.

This module discovers installed compliance implementations via Python entry points.
Implementations register under the 'darnit.implementations' group.
"""


from .logging import get_logger
from .plugin import ComplianceImplementation

logger = get_logger("core.discovery")

# Cache for discovered implementations
_implementations: dict[str, ComplianceImplementation] | None = None


def discover_implementations() -> dict[str, ComplianceImplementation]:
    """Discover all installed compliance implementations.

    Implementations are discovered via Python entry points registered under
    the 'darnit.implementations' group.

    Returns:
        Dict mapping implementation names to implementation instances.

    Example:
        implementations = discover_implementations()
        baseline = implementations.get("openssf-baseline")
        if baseline:
            controls = baseline.get_all_controls()
    """
    global _implementations

    if _implementations is not None:
        return _implementations

    _implementations = {}

    # Use importlib.metadata for Python 3.9+
    from importlib.metadata import entry_points
    eps = entry_points(group="darnit.implementations")

    # TODO: Integrate plugin verification before loading.
    # The PluginVerifier (darnit.core.verification) is fully implemented but
    # not yet called here. Before loading each entry point, we should:
    #   1. Call PluginVerifier.verify_plugin(ep.name)
    #   2. Skip plugins that fail verification (when allow_unsigned=False)
    #   3. Log warnings for unsigned plugins (when allow_unsigned=True)
    # This requires reading VerificationConfig from the user's .baseline.toml.
    # See: docs/SECURITY_GUIDE.md "Plugin Security Model" for configuration details.

    for ep in eps:
        try:
            # Load the entry point (calls the register() function)
            register_func = ep.load()
            impl = register_func()

            if isinstance(impl, ComplianceImplementation):
                _implementations[impl.name] = impl
                logger.info(f"Discovered implementation: {impl.name} v{impl.version}")
            else:
                logger.warning(
                    f"Entry point {ep.name} returned {type(impl)}, "
                    f"expected ComplianceImplementation"
                )
        except (ImportError, AttributeError, TypeError) as e:
            logger.error(f"Failed to load implementation {ep.name}: {e}")
            continue

    logger.info(f"Discovered {len(_implementations)} implementation(s)")
    return _implementations


def get_implementation(name: str) -> ComplianceImplementation | None:
    """Get a specific implementation by name.

    Args:
        name: Implementation name (e.g., 'openssf-baseline')

    Returns:
        Implementation instance or None if not found.
    """
    implementations = discover_implementations()
    return implementations.get(name)


def get_default_implementation() -> ComplianceImplementation | None:
    """Get the default implementation.

    Returns the first discovered implementation, preferring 'openssf-baseline'
    if available.

    Returns:
        Implementation instance or None if no implementations found.
    """
    implementations = discover_implementations()

    # Prefer openssf-baseline as the default
    if "openssf-baseline" in implementations:
        return implementations["openssf-baseline"]

    # Otherwise return the first available
    if implementations:
        return next(iter(implementations.values()))

    return None


def clear_cache() -> None:
    """Clear the implementation cache.

    Useful for testing or when implementations may have changed.
    """
    global _implementations
    _implementations = None


__all__ = [
    "discover_implementations",
    "get_implementation",
    "get_default_implementation",
    "clear_cache",
]
