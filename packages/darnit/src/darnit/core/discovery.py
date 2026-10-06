"""Plugin discovery for darnit compliance implementations.

This module discovers installed compliance implementations via Python entry points.
Implementations register under the 'darnit.implementations' group.
"""

from typing import TYPE_CHECKING, NamedTuple

from darnit.core.verification import PluginVerifier, VerificationConfig, VerificationResult

from .logging import get_logger
from .plugin import ComplianceImplementation

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint

    from darnit.config.operator.schema import PluginSettings

logger = get_logger("core.discovery")


class _PolicyKey(NamedTuple):
    """The verification inputs that can change whether a plugin is accepted.

    Derived from the effective ``VerificationConfig``, never from
    ``PluginSettings`` directly: ``PluginSettings()`` and
    ``PluginSettings(allow_unsigned=False)`` hold the same field value, but
    only the second concludes the policy (``model_fields_set``), so they must
    not be treated as the same policy.

    ``cache_dir`` and ``cache_ttl`` are deliberately absent -- they decide
    where a verification result is memoized, not whether a plugin is accepted.
    """

    allow_unsigned: bool
    trusted_publishers: tuple[str, ...]
    verify_online: bool


def _policy_key(config: VerificationConfig) -> _PolicyKey:
    """Reduce a verification config to the inputs that affect acceptance."""
    return _PolicyKey(
        allow_unsigned=config.allow_unsigned,
        # Already folds in use_default_publishers.
        trusted_publishers=tuple(config.get_all_trusted_publishers()),
        verify_online=config.verify_online,
    )


# Cache for discovered implementations, plus the policy they were verified
# under. Both are process-global, so a caller that supplies no operator policy
# must not leave a permissive cache behind for a later strict audit to reuse.
_implementations: dict[str, ComplianceImplementation] | None = None
_cache_policy: _PolicyKey | None = None


def _resolve_distribution_name(ep: "EntryPoint") -> str | None:
    """Return the installed distribution name backing an entry point.

    Verification looks plugins up by distribution name (``darnit-baseline``),
    not by the entry-point slug (``openssf-baseline``). An entry point with
    no installed distribution identity cannot be verified, so this does not
    fall back to ``ep.name``.
    """
    dist = getattr(ep, "dist", None)
    dist_name = getattr(dist, "name", None) if dist is not None else None
    if isinstance(dist_name, str) and dist_name.strip():
        return dist_name.strip()
    return None


def _accept_plugin(name: str, result: VerificationResult, allow_unsigned: bool) -> bool:
    """Return whether ``name`` may be loaded under ``result``.

    ``allow_unsigned`` applies only to a completed unsigned observation and to
    a signed plugin whose publisher is not trusted. Invalid and undetermined
    results are skipped. A result with no status and ``verified`` false is
    skipped rather than treated as unsigned.
    """
    status = result.status
    verified = result.verified
    trusted = result.trusted
    error = result.error
    warning = result.warning

    if status == "unsigned":
        if allow_unsigned and verified:
            logger.warning("Plugin '%s' is not signed; unsigned plugins are allowed.", name)
            return True
        logger.warning("Skipping plugin '%s': it is not signed.", name)
        return False

    if status == "invalid":
        if error:
            logger.warning("Skipping plugin '%s': its attestation is invalid: %s.", name, error)
        else:
            logger.warning("Skipping plugin '%s': its attestation is invalid.", name)
        return False

    if status == "undetermined":
        reason = str(error).strip().rstrip(".") if error else ""
        if reason:
            logger.warning(
                "Skipping plugin '%s': signature state could not be determined: %s.",
                name,
                reason,
            )
        else:
            logger.warning("Skipping plugin '%s': signature state could not be determined.", name)
        return False

    if status == "signed":
        if verified and trusted:
            return True
        if verified:
            if warning:
                logger.warning("%s", warning)
            return True
        publisher = result.publisher or "an unknown publisher"
        logger.warning(
            "Skipping plugin '%s': signed by an untrusted publisher: %s.",
            name,
            publisher,
        )
        return False

    if verified:
        return True
    logger.warning("Skipping plugin '%s': signature state could not be determined.", name)
    return False


def discover_implementations(
    plugins: "PluginSettings | None" = None,
) -> dict[str, ComplianceImplementation]:
    """Discover compliance implementations from entry points.

    Args:
        plugins: The operator's ``[plugins]`` settings, taken from an operator
            configuration that has already passed the feature-040 containment
            check for the audit target. None keeps this module's existing
            default policy. The audited repository is never a source for this.

    Returns:
        Mapping of implementation name to instance.
    """
    global _implementations, _cache_policy

    verification_config = VerificationConfig.from_plugin_settings(plugins)
    policy = _policy_key(verification_config)

    if _implementations is not None and _cache_policy == policy:
        return _implementations

    if _implementations is not None:
        logger.debug(
            "Plugin verification policy changed; re-verifying %d implementation(s).",
            len(_implementations),
        )

    # Assigned before the loop so that a plugin whose register() re-enters
    # discovery sees the partial result rather than recursing.
    _implementations = {}
    _cache_policy = policy

    # Use importlib.metadata for Python 3.9+
    from importlib.metadata import entry_points

    eps = entry_points(group="darnit.implementations")

    verifier = PluginVerifier(verification_config)

    for ep in eps:
        try:
            dist_name = _resolve_distribution_name(ep)
            if dist_name is None:
                logger.warning(
                    "Skipping entry point '%s': its installed distribution identity could not be determined.",
                    ep.name,
                )
                continue

            try:
                verification_result = verifier.verify_plugin(dist_name)
            except Exception as e:
                logger.warning(
                    "Skipping plugin '%s': signature state could not be determined: %s.",
                    ep.name,
                    e,
                )
                continue

            if not _accept_plugin(ep.name, verification_result, verification_config.allow_unsigned):
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


def get_implementation(
    name: str, plugins: "PluginSettings | None" = None
) -> ComplianceImplementation | None:
    """Get a specific implementation by name.

    Args:
        name: Implementation name (e.g., 'openssf-baseline')
        plugins: Operator ``[plugins]`` settings to verify under. See
            ``discover_implementations``.

    Returns:
        Implementation instance or None if not found.
    """
    implementations = discover_implementations(plugins)
    return implementations.get(name)


def register_implementation_handlers(
    framework_name: str | None, plugins: "PluginSettings | None" = None
) -> bool:
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
        plugins: Operator ``[plugins]`` settings to verify under. See
            ``discover_implementations``.

    Returns:
        True if handlers were registered, False if there was nothing to do
        (no framework name, no such implementation, or the implementation
        exposes neither ``register_sieve_handlers`` nor ``register_handlers``).
    """
    if not framework_name:
        return False

    impl = get_implementation(framework_name, plugins)
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
    # names here makes registration explicit and cache-independent. A plugin
    # may define both (darnit-example registers its step types in one and its
    # MCP tools in the other), so every one present is called.
    # hasattr per Constitution Principle I: missing methods degrade, never crash.
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
    """Clear the implementation cache and the policy it was built under.

    Useful for testing or when implementations may have changed.
    """
    global _implementations, _cache_policy
    _implementations = None
    _cache_policy = None


__all__ = [
    "clear_cache",
    "discover_implementations",
    "get_implementation",
    "register_implementation_handlers",
]
