"""Plugin Registry for discovering darnit frameworks.

This module discovers compliance frameworks via Python entry points.

Entry Point Groups:
    - ``darnit.frameworks`` - Framework TOML path providers
    - ``darnit.implementations`` - Full implementations (see :mod:`darnit.core.discovery`)

Example:
    Discovering frameworks::

        from darnit.core.registry import get_plugin_registry

        registry = get_plugin_registry()

        # List available frameworks
        for name in registry.list_frameworks():
            print(f"Framework: {name}")

    Registering a framework package (pyproject.toml)::

        [project.entry-points."darnit.frameworks"]
        my-framework = "my_package:get_framework_path"
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# =============================================================================
# Entry Point Group Constants
# =============================================================================

ENTRY_POINT_FRAMEWORKS = "darnit.frameworks"
"""Entry point group for framework TOML path providers."""

ENTRY_POINT_IMPLEMENTATIONS = "darnit.implementations"
"""Entry point group for legacy implementations (deprecated)."""


# =============================================================================
# Plugin Info Classes
# =============================================================================


@dataclass
class FrameworkInfo:
    """Metadata about a discovered framework.

    Attributes:
        name: Framework identifier (e.g., "openssf-baseline")
        package: Python package that provides this framework
        entry_point_name: Name as registered in entry points
        path_func: Callable that returns the framework TOML path

    Example:
        >>> info = registry.get_framework_info("openssf-baseline")
        >>> print(info.path)  # Lazily loads path
        /path/to/openssf-baseline.toml
    """

    name: str
    package: str
    entry_point_name: str
    path_func: Callable[[], Path]
    _path: Path | None = field(default=None, repr=False)

    @property
    def path(self) -> Path:
        """Get the framework TOML path (lazily loaded)."""
        if self._path is None:
            self._path = self.path_func()
        return self._path


# =============================================================================
# Plugin Registry
# =============================================================================


@dataclass
class PluginRegistry:
    """Registry of the frameworks installed through entry points.

    Discovery is lazy and cached.

    Attributes:
        _frameworks: Discovered framework info objects
        _discovered: Set of entry point groups already discovered

    Example:
        Basic usage::

            registry = get_plugin_registry()

            for name in registry.list_frameworks():
                print(f"Found framework: {name}")

    See Also:
        - :func:`get_plugin_registry` for accessing the global instance
        - :class:`FrameworkInfo` for framework metadata
    """

    # Discovered plugins
    _frameworks: dict[str, FrameworkInfo] = field(default_factory=dict)

    # Discovery state
    _discovered: set[str] = field(default_factory=set)

    # =========================================================================
    # Discovery Methods
    # =========================================================================

    def discover_frameworks(self) -> dict[str, FrameworkInfo]:
        """Discover all installed frameworks from entry points.

        Scans the ``darnit.frameworks`` entry point group.

        Returns:
            Dict mapping framework names to FrameworkInfo objects.

        Example:
            >>> frameworks = registry.discover_frameworks()
            >>> for name, info in frameworks.items():
            ...     print(f"{name}: {info.path}")
        """
        if ENTRY_POINT_FRAMEWORKS in self._discovered:
            return self._frameworks

        for ep in self._iter_entry_points(ENTRY_POINT_FRAMEWORKS):
            try:
                path_func = ep.load()
                name = ep.name

                # Get package name from entry point
                package = self._get_package_name(ep)

                self._frameworks[name] = FrameworkInfo(
                    name=name,
                    package=package,
                    entry_point_name=ep.name,
                    path_func=path_func,
                )
                logger.debug(f"Discovered framework: {name} from {package}")

            except Exception as e:
                logger.warning(f"Failed to load framework {ep.name}: {e}")

        self._discovered.add(ENTRY_POINT_FRAMEWORKS)
        logger.info(f"Discovered {len(self._frameworks)} framework(s)")
        return self._frameworks

    # =========================================================================
    # Framework Access
    # =========================================================================

    def list_frameworks(self) -> list[str]:
        """List all available framework names.

        Returns:
            Sorted list of framework names.

        Example:
            >>> for name in registry.list_frameworks():
            ...     print(name)
            openssf-baseline
            testchecks
        """
        self.discover_frameworks()
        return sorted(self._frameworks.keys())

    def get_framework_info(self, name: str) -> FrameworkInfo | None:
        """Get framework info by name.

        Args:
            name: Framework identifier (e.g., "openssf-baseline")

        Returns:
            FrameworkInfo or None if not found.
        """
        self.discover_frameworks()
        return self._frameworks.get(name)

    def get_framework_path(self, name: str) -> Path | None:
        """Get the TOML path for a framework.

        Args:
            name: Framework identifier (e.g., "openssf-baseline")

        Returns:
            Path to framework TOML file or None if not found.

        Example:
            >>> path = registry.get_framework_path("openssf-baseline")
            >>> if path:
            ...     config = load_framework_config(path)
        """
        info = self.get_framework_info(name)
        return info.path if info else None

    # =========================================================================
    # Utilities
    # =========================================================================

    def clear_cache(self) -> None:
        """Clear all caches and reset discovery state.

        Useful for testing or when plugins may have changed.
        """
        self._frameworks.clear()
        self._discovered.clear()
        logger.debug("Plugin registry cache cleared")

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _iter_entry_points(self, group: str):
        """Iterate entry points for a group (Python version compatible)."""
        from importlib.metadata import entry_points

        return entry_points(group=group)

    def _get_package_name(self, entry_point) -> str:
        """Extract package name from entry point."""
        # Try different attributes based on Python version
        if hasattr(entry_point, "dist") and entry_point.dist:
            return entry_point.dist.name
        elif hasattr(entry_point, "module"):
            return entry_point.module.split(".")[0]
        else:
            return "unknown"


# =============================================================================
# Global Registry Instance
# =============================================================================

_global_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    """Get the global plugin registry instance.

    The registry is lazily created on first access.

    Returns:
        Global PluginRegistry instance.

    Example:
        >>> registry = get_plugin_registry()
        >>> frameworks = registry.list_frameworks()
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = PluginRegistry()
    return _global_registry


def reset_plugin_registry() -> None:
    """Reset the global plugin registry.

    Creates a fresh registry instance. Useful for testing.
    """
    global _global_registry
    _global_registry = None


__all__ = [
    # Entry point constants
    "ENTRY_POINT_FRAMEWORKS",
    "ENTRY_POINT_IMPLEMENTATIONS",
    # Info classes
    "FrameworkInfo",
    # Registry
    "PluginRegistry",
    "get_plugin_registry",
    "reset_plugin_registry",
]
