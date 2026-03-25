"""Plugin discovery for darnit compliance implementations.

This module discovers installed compliance implementations via Python entry points.
Implementations register under the 'darnit.implementations' group.
"""


from darnit.core.verification import PluginVerifier, VerificationConfig

from .logging import get_logger
from .plugin import ComplianceImplementation

logger = get_logger("core.discovery")

# Cache for discovered implementations
_implementations: dict[str, ComplianceImplementation] | None = None


def discover_implementations() -> dict[str, ComplianceImplementation]:
    """Discover compliance implementations from entry points."""
    global _implementations

    if _implementations is not None:
        return _implementations

    _implementations = {}

    # Use importlib.metadata for Python 3.9+
    from importlib.metadata import entry_points

    eps = entry_points(group="darnit.implementations")

    # Create plugin verifier (default: allow unsigned plugins for backward compatibility)
    verification_config = VerificationConfig(allow_unsigned=True)
    verifier = PluginVerifier(verification_config)

    for ep in eps:
        try:
            try:
                verification_result = verifier.verify_plugin(ep.name)
            except Exception as e:
                    logger.warning(
                        f"Plugin verification errored for '{ep.name}', loading anyway because "
                        f"allow_unsigned=True: {e}"
                    )
                    verification_result = None

            if verification_result is not None and not verification_result.verified:
                message = verification_result.error or verification_result.warning or "unknown verification failure"

                if verification_config.allow_unsigned:
                    logger.warning(
                        f"Plugin '{ep.name}' failed verification but will be loaded anyway: "
                        f"{message}"
                    )
                else:
                    logger.warning(
                        f"Skipping plugin '{ep.name}' because verification failed: "
                        f"{message}"
                    )
                    continue

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
        except Exception as e:
            logger.error(f"Error occurred while verifying or loading plugin '{ep.name}': {e}")
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


def clear_cache() -> None:
    """Clear the implementation cache.

    Useful for testing or when implementations may have changed.
    """
    global _implementations
    _implementations = None


__all__ = [
    "discover_implementations",
    "get_implementation",
    "clear_cache",
]
