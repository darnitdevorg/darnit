"""Plugin discovery for darnit compliance implementations.

This module discovers installed compliance implementations via Python entry points.
Implementations register under the 'darnit.implementations' group.
"""


import json
from pathlib import Path
from typing import TYPE_CHECKING

from darnit.core.verification import PluginVerifier, VerificationConfig

from .logging import get_logger
from .plugin import ComplianceImplementation

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint

    from darnit.config.framework_schema import PluginsConfig

logger = get_logger("core.discovery")

# Keyed by verification policy so two repos in one process do not share a pass.
_implementations: dict[str, dict[str, ComplianceImplementation]] = {}


def _load_plugin_policy(repo_path: Path | str | None) -> "PluginsConfig | None":
    """Read ``[plugins]`` from ``.baseline.toml``.

    None is unconfigured. A file that exists but will not parse raises;
    it is not treated as permissive.
    """
    if repo_path is None:
        return None

    # Imported here so core does not depend on config at import time.
    from darnit.config.merger import load_user_config

    user_config = load_user_config(Path(repo_path))
    return user_config.plugins if user_config is not None else None


def _policy_cache_key(plugins: "PluginsConfig | None") -> str:
    """Key from verification settings only.

    Unset policy shares one key. Explicit ``allow_unsigned = true`` does not.
    """
    if plugins is None:
        return ""

    policy: dict = {}
    if "global_allow_unsigned" in plugins.model_fields_set:
        policy["allow_unsigned"] = plugins.global_allow_unsigned
    if plugins.global_trusted_publishers:
        policy["trusted_publishers"] = list(plugins.global_trusted_publishers)

    per_plugin: dict[str, dict] = {}
    for name in sorted(plugins.plugins):
        plugin = plugins.plugins[name]
        entry: dict = {}
        if "allow_unsigned" in plugin.model_fields_set:
            entry["allow_unsigned"] = plugin.allow_unsigned
        if plugin.trusted_publishers:
            entry["trusted_publishers"] = list(plugin.trusted_publishers)
        if entry:
            per_plugin[name] = entry
    if per_plugin:
        policy["plugins"] = per_plugin

    if not policy:
        return ""

    return json.dumps(policy, sort_keys=True)


def _resolve_distribution_name(ep: "EntryPoint") -> str:
    """Return the installed distribution name backing an entry point.

    Verification looks plugins up by distribution name (``darnit-baseline``),
    not by the entry-point slug (``openssf-baseline``). Entry points built by
    hand have no ``dist``, so fall back to the slug.
    """
    dist = getattr(ep, "dist", None)
    dist_name = getattr(dist, "name", None) if dist is not None else None
    if dist_name:
        return dist_name

    logger.debug(
        "Entry point '%s' carries no distribution metadata; verifying under "
        "the entry-point name instead.",
        ep.name,
    )
    return ep.name


def discover_implementations(
    repo_path: Path | str | None = None,
) -> dict[str, ComplianceImplementation]:
    """Discover compliance implementations from entry points.

    Args:
        repo_path: Repository whose ``.baseline.toml`` supplies plugin policy.
            None leaves it unconfigured.
    """
    plugins_config = _load_plugin_policy(repo_path)
    cache_key = _policy_cache_key(plugins_config)

    cached = _implementations.get(cache_key)
    if cached is not None:
        return cached

    # Publish first so a plugin register() that re-enters discovery does not recurse.
    implementations: dict[str, ComplianceImplementation] = {}
    _implementations[cache_key] = implementations

    # Use importlib.metadata for Python 3.9+
    from importlib.metadata import entry_points

    eps = entry_points(group="darnit.implementations")

    for ep in eps:
        try:
            dist_name = _resolve_distribution_name(ep)
            verification_config = VerificationConfig.from_plugins_config(
                plugins_config, dist_name
            )
            verifier = PluginVerifier(verification_config)

            try:
                verification_result = verifier.verify_plugin(dist_name)
            except Exception as e:
                if not verification_config.allow_unsigned:
                    logger.warning(
                        f"Skipping plugin '{ep.name}' because verification errored "
                        f"and unsigned plugins are not allowed: {e}"
                    )
                    continue

                logger.warning(
                    f"Plugin verification errored for '{ep.name}', loading anyway "
                    f"because unsigned plugins are allowed: {e}"
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
                implementations[impl.name] = impl
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

    logger.info(f"Discovered {len(implementations)} implementation(s)")
    return implementations


def get_implementation(
    name: str, repo_path: Path | str | None = None
) -> ComplianceImplementation | None:
    """Get a specific implementation by name.

    Args:
        name: Implementation name (e.g., 'openssf-baseline')
        repo_path: Repository supplying the plugin verification policy.

    Returns:
        Implementation instance or None if not found.
    """
    implementations = discover_implementations(repo_path)
    return implementations.get(name)


def register_implementation_handlers(
    framework_name: str | None, repo_path: Path | str | None = None
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
        repo_path: Repository supplying the plugin verification policy.

    Returns:
        True if handlers were registered, False if there was nothing to do
        (no framework name, no such implementation, or the implementation
        does not expose ``register_handlers``).
    """
    if not framework_name:
        return False

    impl = get_implementation(framework_name, repo_path)
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
    """Clear every policy's implementation cache."""
    _implementations.clear()


__all__ = [
    "clear_cache",
    "discover_implementations",
    "get_implementation",
    "register_implementation_handlers",
]
