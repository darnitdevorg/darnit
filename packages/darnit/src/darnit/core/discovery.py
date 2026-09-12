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
        does not expose ``register_handlers``).
    """
    if not framework_name:
        return False

    impl = get_implementation(framework_name)
    if impl is None:
        logger.debug("No implementation found for '%s'", framework_name)
        return False

    # Two method names are in use across in-tree plugins:
    #   register_handlers       -- documented in CLAUDE.md; darnit-baseline
    #   register_sieve_handlers -- darnit-gittuf, darnit-reproducibility
    # Those two work today only because their `register()` entry point calls
    # register_sieve_handlers() during discovery. That is a side channel, not
    # the protocol: discovery results are cached, so any caller that warmed
    # the cache earlier in the process leaves the handlers unregistered and
    # every plugin control silently falls through to `manual`. Accepting both
    # names here makes registration explicit and cache-independent.
    # hasattr per Constitution Principle I: missing methods degrade, never crash.
    method = None
    for name in ("register_handlers", "register_sieve_handlers"):
        if hasattr(impl, name):
            method = getattr(impl, name)
            break
    if method is None:
        return False

    try:
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
    global _implementations
    _implementations = None


__all__ = [
    "clear_cache",
    "discover_implementations",
    "get_implementation",
    "register_implementation_handlers",
]
