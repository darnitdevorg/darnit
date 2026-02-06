"""Handler registration system for darnit plugins.

This module provides the `@register_handler` and `@register_pass` decorators
for auto-registering check handlers and custom pass implementations when
plugins are loaded.

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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterable

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


@dataclass
class PassInfo:
    """Information about a registered custom pass.

    Attributes:
        name: Short name used to reference the pass
        cls: The pass class
        plugin: Name of the plugin that registered this pass
        module: Full module path of the pass class
        doc: Pass class docstring
    """

    name: str
    cls: type
    plugin: str | None = None
    module: str | None = None
    doc: str | None = None


@dataclass
class TemplateInfo:
    """Information about a discovered template.

    Attributes:
        name: Template name (filename without extension)
        path: Full path to the template file
        plugin: Name of the plugin that provides this template
        content: Cached template content (loaded on demand)
    """

    name: str
    path: Path
    plugin: str | None = None
    content: str | None = None

    def load_content(self) -> str:
        """Load template content from file."""
        if self.content is None:
            self.content = self.path.read_text()
        return self.content


class HandlerRegistry:
    """Central registry for handlers, passes, and templates.

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
        self._passes: dict[str, PassInfo] = {}
        self._templates: dict[str, TemplateInfo] = {}
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

    def list_handlers(self, plugin: str | None = None) -> list[HandlerInfo]:
        """List all registered handlers.

        Args:
            plugin: Filter by plugin name (None = all handlers)

        Returns:
            List of HandlerInfo objects
        """
        handlers = list(self._handlers.values())
        if plugin is not None:
            handlers = [h for h in handlers if h.plugin == plugin]
        return handlers

    # Allowed module prefixes for handler imports (security allowlist)
    # Only modules starting with these prefixes can be dynamically loaded
    ALLOWED_MODULE_PREFIXES = (
        "darnit.",
        "darnit_baseline.",
        "darnit_example.",
        "darnit_testchecks.",
    )

    def _load_handler_from_path(self, path: str) -> Callable[..., Any] | None:
        """Load handler from module:function path.

        Security: Only modules matching ALLOWED_MODULE_PREFIXES can be loaded
        to prevent arbitrary code execution via malicious module paths.

        Args:
            path: String in format "module.path:function_name"

        Returns:
            Handler function or None if loading fails or module not allowed
        """
        try:
            module_path, func_name = path.rsplit(":", 1)

            # Validate module path against allowlist to prevent arbitrary imports
            if not any(module_path.startswith(prefix) for prefix in self.ALLOWED_MODULE_PREFIXES):
                logger.warning(
                    f"Module path '{module_path}' not in allowed prefixes: "
                    f"{self.ALLOWED_MODULE_PREFIXES}"
                )
                return None

            module = importlib.import_module(module_path)
            return getattr(module, func_name, None)
        except (ValueError, ImportError, AttributeError) as e:
            logger.warning(f"Failed to load handler from path '{path}': {e}")
            return None

    # =========================================================================
    # Pass Registration
    # =========================================================================

    def register_pass(
        self,
        name: str,
        cls: type,
        *,
        plugin: str | None = None,
    ) -> None:
        """Register a custom pass class.

        Args:
            name: Short name to register under
            cls: The pass class
            plugin: Plugin name (uses current plugin context if None)
        """
        plugin = plugin or self._current_plugin

        if name in self._passes:
            existing = self._passes[name]
            logger.warning(
                f"Pass '{name}' already registered by plugin '{existing.plugin}', "
                f"overwriting with plugin '{plugin}'"
            )

        self._passes[name] = PassInfo(
            name=name,
            cls=cls,
            plugin=plugin,
            module=f"{cls.__module__}.{cls.__qualname__}",
            doc=cls.__doc__,
        )
        logger.debug(f"Registered pass '{name}' from plugin '{plugin}'")

    def get_pass(self, name: str) -> type | None:
        """Get a pass class by name."""
        if name in self._passes:
            return self._passes[name].cls
        return None

    def list_passes(self, plugin: str | None = None) -> list[PassInfo]:
        """List all registered passes."""
        passes = list(self._passes.values())
        if plugin is not None:
            passes = [p for p in passes if p.plugin == plugin]
        return passes

    # =========================================================================
    # Template Registration
    # =========================================================================

    def register_template(
        self,
        name: str,
        path: Path,
        *,
        plugin: str | None = None,
    ) -> None:
        """Register a template file.

        Args:
            name: Template name (usually filename without extension)
            path: Full path to template file
            plugin: Plugin name
        """
        plugin = plugin or self._current_plugin

        if name in self._templates:
            existing = self._templates[name]
            logger.warning(
                f"Template '{name}' already registered by plugin '{existing.plugin}', "
                f"overwriting with plugin '{plugin}'"
            )

        self._templates[name] = TemplateInfo(
            name=name,
            path=path,
            plugin=plugin,
        )
        logger.debug(f"Registered template '{name}' from plugin '{plugin}'")

    def get_template(self, name: str) -> TemplateInfo | None:
        """Get a template by name."""
        return self._templates.get(name)

    def list_templates(self, plugin: str | None = None) -> list[TemplateInfo]:
        """List all registered templates."""
        templates = list(self._templates.values())
        if plugin is not None:
            templates = [t for t in templates if t.plugin == plugin]
        return templates

    def discover_templates(
        self,
        templates_dir: Path,
        *,
        plugin: str | None = None,
        extensions: Iterable[str] = (".md", ".txt", ".j2", ".jinja2"),
    ) -> int:
        """Discover and register templates from a directory.

        Args:
            templates_dir: Directory to search for templates
            plugin: Plugin name to associate with discovered templates
            extensions: File extensions to consider as templates

        Returns:
            Number of templates discovered
        """
        if not templates_dir.is_dir():
            return 0

        count = 0
        extensions_set = set(extensions)

        for template_path in templates_dir.iterdir():
            if template_path.is_file() and template_path.suffix in extensions_set:
                name = template_path.stem  # filename without extension
                self.register_template(name, template_path, plugin=plugin)
                count += 1

        logger.debug(f"Discovered {count} templates from {templates_dir}")
        return count

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
        self._passes.clear()
        self._templates.clear()
        self._current_plugin = None


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


def register_pass(name: str | None = None) -> Callable[[type], type]:
    """Decorator to register a custom pass class.

    Can be used with or without arguments:
        @register_pass
        class MyPass: ...

        @register_pass("custom_name")
        class MyPass: ...

    Args:
        name: Pass name (defaults to class name)

    Returns:
        Decorator function
    """

    def decorator(cls: type) -> type:
        pass_name = name if name is not None else cls.__name__
        _handler_registry.register_pass(pass_name, cls)
        return cls

    # Handle @register_pass without parentheses
    if isinstance(name, type):
        cls = name
        pass_name = cls.__name__
        _handler_registry.register_pass(pass_name, cls)
        return cls  # type: ignore[return-value]

    return decorator


# =============================================================================
# Convenience Functions
# =============================================================================


def get_handler(name: str) -> Callable[..., Any] | None:
    """Get a handler by name from the global registry."""
    return _handler_registry.get_handler(name)


def list_handlers(plugin: str | None = None) -> list[HandlerInfo]:
    """List all registered handlers."""
    return _handler_registry.list_handlers(plugin)


def get_template(name: str) -> TemplateInfo | None:
    """Get a template by name from the global registry."""
    return _handler_registry.get_template(name)


__all__ = [
    # Classes
    "HandlerRegistry",
    "HandlerInfo",
    "PassInfo",
    "TemplateInfo",
    # Decorators
    "register_handler",
    "register_pass",
    # Functions
    "get_handler_registry",
    "get_handler",
    "list_handlers",
    "get_template",
]
