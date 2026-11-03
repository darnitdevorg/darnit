"""Handler registration system for darnit plugins.

This module provides the `@register_handler` decorator and the registry that
maps a short name to an MCP tool handler function.

Example:
    ```python
    from darnit.core.handlers import register_handler

    @register_handler("check_branch_protection")
    def check_branch_protection(owner: str, repo: str, local_path: Path, config: dict) -> CheckOutput:
        # Check implementation
        ...
    ```

The handler can then be referenced in TOML:
    ```toml
    [controls."OSPS-AC-03.01".check]
    adapter = "builtin"
    handler = "check_branch_protection"
    ```

Security:
    Handler registration is scoped to the plugin that registers it. The registry
    tracks which plugin registered each handler for audit purposes.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class HandlerInfo:
    """Information about a registered handler.

    Attributes:
        name: Short name used to reference the handler
        func: The handler function
        plugin: Name of the plugin that registered this handler
        module: Full module path of the handler
        doc: Handler docstring
    """

    name: str
    func: Callable[..., Any]
    plugin: str | None = None
    module: str | None = None
    doc: str | None = None


class HandlerRegistry:
    """Central registry for handlers.

    This registry is used to discover and resolve handler references
    in TOML configurations. Handlers are registered via decorators
    or explicitly via the register methods.

    Thread Safety:
        The registry is designed for single-threaded use during plugin
        loading. Once plugins are loaded, the registry should be treated
        as read-only.
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._handlers: dict[str, HandlerInfo] = {}
        self._current_plugin: str | None = None

    # =========================================================================
    # Handler Registration
    # =========================================================================

    def register_handler(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        plugin: str | None = None,
    ) -> None:
        """Register a handler function.

        Args:
            name: Short name to register under
            func: The handler function
            plugin: Plugin name (uses current plugin context if None)

        Raises:
            ValueError: If a handler with this name is already registered
        """
        plugin = plugin or self._current_plugin

        if name in self._handlers:
            existing = self._handlers[name]
            if existing.plugin != plugin:
                logger.warning(
                    f"Handler '{name}' already registered by plugin '{existing.plugin}', "
                    f"overwriting with plugin '{plugin}'"
                )

        self._handlers[name] = HandlerInfo(
            name=name,
            func=func,
            plugin=plugin,
            module=f"{func.__module__}.{func.__qualname__}",
            doc=func.__doc__,
        )
        logger.debug(f"Registered handler '{name}' from plugin '{plugin}'")

    def get_handler(self, name: str) -> Callable[..., Any] | None:
        """Get a handler function by name.

        Args:
            name: Handler short name or module:function path

        Returns:
            Handler function or None if not found

        Raises:
            HandlerImportRefused: If ``name`` is a module path the resolution
                policy refuses (see :func:`resolve_module_path`)
        """
        # First check the registry
        if name in self._handlers:
            return self._handlers[name].func

        # Try parsing as module:function path
        if ":" in name:
            return self._load_handler_from_path(name)

        return None

    def get_handler_info(self, name: str) -> HandlerInfo | None:
        """Get full handler information."""
        return self._handlers.get(name)

    def _load_handler_from_path(self, path: str) -> Callable[..., Any] | None:
        """Load a handler from a module:function path under the resolution policy.

        Returns None when an allowed module or its attribute does not exist.

        Raises:
            HandlerImportRefused: If the policy refuses the path
        """
        try:
            return resolve_module_path(path)
        except (ImportError, AttributeError) as e:
            logger.warning(f"Failed to load handler from path '{path}': {e}")
            return None

    # =========================================================================
    # Plugin Context
    # =========================================================================

    def set_plugin_context(self, plugin: str | None) -> None:
        """Set the current plugin context for registrations.

        This is used during plugin loading to automatically associate
        handlers with their source plugin.

        Args:
            plugin: Plugin name or None to clear context
        """
        self._current_plugin = plugin

    def clear(self) -> None:
        """Clear all registrations."""
        self._handlers.clear()
        self._current_plugin = None


# =============================================================================
# Module Path Resolution
# =============================================================================

CORE_PACKAGE = "darnit"


class HandlerImportRefused(ValueError):
    """A ``module:attribute`` path the module resolution policy refuses."""

    def __init__(self, path: str, reason: str, allowed: Iterable[str]) -> None:
        self.path = path
        self.allowed = tuple(sorted(allowed))
        super().__init__(
            f"Refused to import '{path}': {reason}. "
            f"Allowed top-level packages: {', '.join(self.allowed)}"
        )


def allowed_module_packages() -> frozenset[str]:
    """Top-level packages a configured module path may name: core plus installed implementations."""
    from darnit.core.discovery import implementation_packages

    return frozenset({CORE_PACKAGE}) | implementation_packages()


def _refuse(path: str, reason: str) -> HandlerImportRefused:
    error = HandlerImportRefused(path, reason, allowed_module_packages())
    logger.warning(str(error))
    return error


def resolve_module_path(path: str) -> Any:
    """Import the attribute named by ``package.module:attribute``.

    This is the only place the framework imports a module named by
    configuration. The module's top-level package must be ``darnit`` or the
    package of an implementation discovered from the ``darnit.implementations``
    entry points; anything else is refused before it is imported.

    Raises:
        HandlerImportRefused: If the path is malformed or outside the policy
        ImportError: If an allowed module cannot be imported
        AttributeError: If the module has no such attribute
    """
    module_path, sep, attr = path.rpartition(":")
    parts = module_path.split(".")
    if not sep or ":" in module_path or not attr.isidentifier() or not all(part.isidentifier() for part in parts):
        raise _refuse(path, "not of the form 'package.module:attribute'")

    if parts[0] != CORE_PACKAGE and parts[0] not in allowed_module_packages():
        raise _refuse(path, f"'{parts[0]}' is neither darnit nor an installed darnit implementation")

    module = importlib.import_module(module_path)
    return getattr(module, attr)


# =============================================================================
# Global Registry Instance
# =============================================================================

_handler_registry = HandlerRegistry()


def get_handler_registry() -> HandlerRegistry:
    """Get the global handler registry instance."""
    return _handler_registry


# =============================================================================
# Decorators
# =============================================================================


def register_handler(name: str | None = None) -> Callable[[F], F]:
    """Decorator to register a handler function.

    Can be used with or without arguments:
        @register_handler
        def my_handler(...): ...

        @register_handler("custom_name")
        def my_handler(...): ...

    Args:
        name: Handler name (defaults to function name)

    Returns:
        Decorator function
    """

    def decorator(func: F) -> F:
        handler_name = name if name is not None else func.__name__
        _handler_registry.register_handler(handler_name, func)
        return func

    # Handle @register_handler without parentheses
    if callable(name):
        func = name
        handler_name = func.__name__
        _handler_registry.register_handler(handler_name, func)
        return func  # type: ignore[return-value]

    return decorator


# =============================================================================
# Convenience Functions
# =============================================================================


def get_handler(name: str) -> Callable[..., Any] | None:
    """Get a handler by name from the global registry."""
    return _handler_registry.get_handler(name)


__all__ = [
    # Classes
    "HandlerImportRefused",
    "HandlerRegistry",
    "HandlerInfo",
    # Decorator
    "register_handler",
    # Functions
    "get_handler_registry",
    "get_handler",
    "allowed_module_packages",
    "resolve_module_path",
]
