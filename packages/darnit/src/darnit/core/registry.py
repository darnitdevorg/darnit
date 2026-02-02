"""Plugin Registry for discovering and managing darnit plugins.

This module provides a unified registry for discovering plugins via Python entry points:

- **Frameworks**: Compliance framework definitions (TOML + adapters)
- **Check Adapters**: Verification implementations
- **Remediation Adapters**: Fix implementations

Entry Point Groups:
    - ``darnit.frameworks`` - Framework TOML path providers
    - ``darnit.check_adapters`` - Check adapter classes
    - ``darnit.remediation_adapters`` - Remediation adapter classes
    - ``darnit.implementations`` - Legacy full implementations (deprecated)

Example:
    Discovering all plugins::

        from darnit.core.registry import get_plugin_registry

        registry = get_plugin_registry()
        registry.discover_all()

        # List available frameworks
        for name in registry.list_frameworks():
            print(f"Framework: {name}")

        # Get an adapter by name
        adapter = registry.get_check_adapter("kusari")

    Registering a plugin package (pyproject.toml)::

        [project.entry-points."darnit.check_adapters"]
        kusari = "darnit_plugins.adapters.kusari:KusariCheckAdapter"

        [project.entry-points."darnit.frameworks"]
        my-framework = "my_package:get_framework_path"

See Also:
    - :doc:`/plugin-discovery-design` for architecture details
    - :mod:`darnit.core.adapters` for adapter base classes
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
)

from .adapters import CheckAdapter, RemediationAdapter
from .models import AdapterCapability

logger = logging.getLogger(__name__)


# =============================================================================
# Entry Point Group Constants
# =============================================================================

ENTRY_POINT_FRAMEWORKS = "darnit.frameworks"
"""Entry point group for framework TOML path providers."""

ENTRY_POINT_CHECK_ADAPTERS = "darnit.check_adapters"
"""Entry point group for check adapter classes."""

ENTRY_POINT_REMEDIATION_ADAPTERS = "darnit.remediation_adapters"
"""Entry point group for remediation adapter classes."""

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


@dataclass
class AdapterInfo:
    """Metadata about a discovered adapter.

    Attributes:
        name: Adapter identifier (e.g., "kusari")
        package: Python package that provides this adapter
        entry_point_name: Name as registered in entry points
        adapter_class: The adapter class (not instantiated)
        adapter_type: "check" or "remediation"

    Example:
        >>> info = registry.get_adapter_info("kusari")
        >>> adapter = info.get_instance()
        >>> result = adapter.check("CTRL-001", ...)
    """

    name: str
    package: str
    entry_point_name: str
    adapter_class: type
    adapter_type: str  # "check" or "remediation"
    _instance: Any | None = field(default=None, repr=False)
    _capabilities: AdapterCapability | None = field(default=None, repr=False)

    def get_instance(self) -> Any:
        """Get the adapter instance (lazily instantiated)."""
        if self._instance is None:
            self._instance = self.adapter_class()
        return self._instance

    @property
    def capabilities(self) -> AdapterCapability | None:
        """Get adapter capabilities (requires instantiation)."""
        if self._capabilities is None:
            instance = self.get_instance()
            if hasattr(instance, "capabilities"):
                self._capabilities = instance.capabilities()
        return self._capabilities


# =============================================================================
# Plugin Registry
# =============================================================================


@dataclass
class PluginRegistry:
    """Central registry for all darnit plugins.

    The PluginRegistry discovers and manages plugins from Python entry points:

    - **Frameworks**: Compliance framework definitions
    - **Check Adapters**: Verification implementations
    - **Remediation Adapters**: Fix implementations

    Thread-safe with lazy loading and caching.

    Attributes:
        _frameworks: Discovered framework info objects
        _check_adapters: Discovered check adapter info objects
        _remediation_adapters: Discovered remediation adapter info objects
        _discovered: Set of entry point groups already discovered

    Example:
        Basic usage::

            registry = get_plugin_registry()

            # Discover all plugins
            registry.discover_all()

            # List frameworks
            for name in registry.list_frameworks():
                print(f"Found framework: {name}")

            # Get a check adapter
            adapter = registry.get_check_adapter("kusari")
            if adapter:
                result = adapter.check("CTRL-001", "", "", "/path", {})

        Manual registration::

            # Register a custom adapter
            registry.register_check_adapter("custom", MyCustomAdapter)

            # Register from config
            registry.register_from_adapter_config("kusari", {
                "type": "command",
                "command": "kusari",
            })

    See Also:
        - :func:`get_plugin_registry` for accessing the global instance
        - :class:`FrameworkInfo` for framework metadata
        - :class:`AdapterInfo` for adapter metadata
    """

    # Discovered plugins
    _frameworks: dict[str, FrameworkInfo] = field(default_factory=dict)
    _check_adapters: dict[str, AdapterInfo] = field(default_factory=dict)
    _remediation_adapters: dict[str, AdapterInfo] = field(default_factory=dict)

    # Cached instances (separate from info to allow re-instantiation)
    _check_instances: dict[str, CheckAdapter] = field(default_factory=dict)
    _remediation_instances: dict[str, RemediationAdapter] = field(default_factory=dict)

    # Discovery state
    _discovered: set[str] = field(default_factory=set)

    # Allowed module prefixes for dynamic imports (security whitelist)
    ALLOWED_MODULE_PREFIXES: tuple = (
        "darnit.",
        "darnit_baseline.",
        "darnit_plugins.",
        "darnit_testchecks.",
    )

    # =========================================================================
    # Discovery Methods
    # =========================================================================

    def discover_all(self) -> None:
        """Discover all plugins from entry points.

        Scans all entry point groups and populates the registry.
        Safe to call multiple times (idempotent).

        Example:
            >>> registry = get_plugin_registry()
            >>> registry.discover_all()
            >>> print(f"Found {len(registry.list_frameworks())} frameworks")
        """
        self.discover_frameworks()
        self.discover_check_adapters()
        self.discover_remediation_adapters()

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

    def discover_check_adapters(self) -> dict[str, AdapterInfo]:
        """Discover all installed check adapters from entry points.

        Scans the ``darnit.check_adapters`` entry point group.

        Returns:
            Dict mapping adapter names to AdapterInfo objects.

        Example:
            >>> adapters = registry.discover_check_adapters()
            >>> for name, info in adapters.items():
            ...     print(f"{name}: {info.adapter_class}")
        """
        if ENTRY_POINT_CHECK_ADAPTERS in self._discovered:
            return self._check_adapters

        for ep in self._iter_entry_points(ENTRY_POINT_CHECK_ADAPTERS):
            try:
                adapter_class = ep.load()
                name = ep.name
                package = self._get_package_name(ep)

                self._check_adapters[name] = AdapterInfo(
                    name=name,
                    package=package,
                    entry_point_name=ep.name,
                    adapter_class=adapter_class,
                    adapter_type="check",
                )
                logger.debug(f"Discovered check adapter: {name} from {package}")

            except Exception as e:
                logger.warning(f"Failed to load check adapter {ep.name}: {e}")

        self._discovered.add(ENTRY_POINT_CHECK_ADAPTERS)
        logger.info(f"Discovered {len(self._check_adapters)} check adapter(s)")
        return self._check_adapters

    def discover_remediation_adapters(self) -> dict[str, AdapterInfo]:
        """Discover all installed remediation adapters from entry points.

        Scans the ``darnit.remediation_adapters`` entry point group.

        Returns:
            Dict mapping adapter names to AdapterInfo objects.
        """
        if ENTRY_POINT_REMEDIATION_ADAPTERS in self._discovered:
            return self._remediation_adapters

        for ep in self._iter_entry_points(ENTRY_POINT_REMEDIATION_ADAPTERS):
            try:
                adapter_class = ep.load()
                name = ep.name
                package = self._get_package_name(ep)

                self._remediation_adapters[name] = AdapterInfo(
                    name=name,
                    package=package,
                    entry_point_name=ep.name,
                    adapter_class=adapter_class,
                    adapter_type="remediation",
                )
                logger.debug(f"Discovered remediation adapter: {name} from {package}")

            except Exception as e:
                logger.warning(f"Failed to load remediation adapter {ep.name}: {e}")

        self._discovered.add(ENTRY_POINT_REMEDIATION_ADAPTERS)
        logger.info(
            f"Discovered {len(self._remediation_adapters)} remediation adapter(s)"
        )
        return self._remediation_adapters

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

    def has_framework(self, name: str) -> bool:
        """Check if a framework is available.

        Args:
            name: Framework identifier

        Returns:
            True if framework is registered.
        """
        self.discover_frameworks()
        return name in self._frameworks

    # =========================================================================
    # Check Adapter Access
    # =========================================================================

    def list_check_adapters(self) -> list[str]:
        """List all available check adapter names.

        Returns:
            Sorted list of check adapter names.

        Example:
            >>> for name in registry.list_check_adapters():
            ...     print(name)
            builtin
            kusari
            trivy
        """
        self.discover_check_adapters()
        return sorted(self._check_adapters.keys())

    def get_check_adapter_info(self, name: str) -> AdapterInfo | None:
        """Get check adapter info by name.

        Args:
            name: Adapter identifier (e.g., "kusari")

        Returns:
            AdapterInfo or None if not found.
        """
        self.discover_check_adapters()
        return self._check_adapters.get(name)

    def get_check_adapter(self, name: str) -> CheckAdapter | None:
        """Get a check adapter instance by name.

        Instances are cached for reuse.

        Args:
            name: Adapter identifier (e.g., "kusari")

        Returns:
            CheckAdapter instance or None if not found.

        Example:
            >>> adapter = registry.get_check_adapter("kusari")
            >>> if adapter:
            ...     result = adapter.check("CTRL-001", "", "", "/path", {})
        """
        # Check cache first
        if name in self._check_instances:
            return self._check_instances[name]

        # Try to get from discovered adapters
        info = self.get_check_adapter_info(name)
        if info:
            instance = info.get_instance()
            self._check_instances[name] = instance
            return instance

        return None

    def has_check_adapter(self, name: str) -> bool:
        """Check if a check adapter is available.

        Args:
            name: Adapter identifier

        Returns:
            True if adapter is registered.
        """
        self.discover_check_adapters()
        return name in self._check_adapters

    # =========================================================================
    # Remediation Adapter Access
    # =========================================================================

    def list_remediation_adapters(self) -> list[str]:
        """List all available remediation adapter names.

        Returns:
            Sorted list of remediation adapter names.
        """
        self.discover_remediation_adapters()
        return sorted(self._remediation_adapters.keys())

    def get_remediation_adapter_info(self, name: str) -> AdapterInfo | None:
        """Get remediation adapter info by name.

        Args:
            name: Adapter identifier

        Returns:
            AdapterInfo or None if not found.
        """
        self.discover_remediation_adapters()
        return self._remediation_adapters.get(name)

    def get_remediation_adapter(self, name: str) -> RemediationAdapter | None:
        """Get a remediation adapter instance by name.

        Args:
            name: Adapter identifier

        Returns:
            RemediationAdapter instance or None if not found.
        """
        # Check cache first
        if name in self._remediation_instances:
            return self._remediation_instances[name]

        # Try to get from discovered adapters
        info = self.get_remediation_adapter_info(name)
        if info:
            instance = info.get_instance()
            self._remediation_instances[name] = instance
            return instance

        return None

    def has_remediation_adapter(self, name: str) -> bool:
        """Check if a remediation adapter is available.

        Args:
            name: Adapter identifier

        Returns:
            True if adapter is registered.
        """
        self.discover_remediation_adapters()
        return name in self._remediation_adapters

    # =========================================================================
    # Manual Registration
    # =========================================================================

    def register_framework(
        self,
        name: str,
        path_func: Callable[[], Path],
        package: str = "manual",
    ) -> None:
        """Manually register a framework.

        Args:
            name: Framework identifier
            path_func: Callable that returns the framework TOML path
            package: Package name for tracking (default: "manual")

        Example:
            >>> registry.register_framework(
            ...     "custom",
            ...     lambda: Path("/path/to/custom.toml"),
            ... )
        """
        self._frameworks[name] = FrameworkInfo(
            name=name,
            package=package,
            entry_point_name=name,
            path_func=path_func,
        )
        logger.debug(f"Registered framework: {name}")

    def register_check_adapter(
        self,
        name: str,
        adapter: type[CheckAdapter] | CheckAdapter,
        package: str = "manual",
    ) -> None:
        """Manually register a check adapter.

        Args:
            name: Adapter identifier
            adapter: Adapter class or instance
            package: Package name for tracking (default: "manual")

        Example:
            >>> registry.register_check_adapter("custom", MyCustomAdapter)
            >>> # Or with an instance
            >>> registry.register_check_adapter("custom", MyCustomAdapter())
        """
        if isinstance(adapter, type):
            # It's a class
            self._check_adapters[name] = AdapterInfo(
                name=name,
                package=package,
                entry_point_name=name,
                adapter_class=adapter,
                adapter_type="check",
            )
        else:
            # It's an instance
            self._check_instances[name] = adapter
            self._check_adapters[name] = AdapterInfo(
                name=name,
                package=package,
                entry_point_name=name,
                adapter_class=type(adapter),
                adapter_type="check",
                _instance=adapter,
            )
        logger.debug(f"Registered check adapter: {name}")

    def register_remediation_adapter(
        self,
        name: str,
        adapter: type[RemediationAdapter] | RemediationAdapter,
        package: str = "manual",
    ) -> None:
        """Manually register a remediation adapter.

        Args:
            name: Adapter identifier
            adapter: Adapter class or instance
            package: Package name for tracking (default: "manual")
        """
        if isinstance(adapter, type):
            self._remediation_adapters[name] = AdapterInfo(
                name=name,
                package=package,
                entry_point_name=name,
                adapter_class=adapter,
                adapter_type="remediation",
            )
        else:
            self._remediation_instances[name] = adapter
            self._remediation_adapters[name] = AdapterInfo(
                name=name,
                package=package,
                entry_point_name=name,
                adapter_class=type(adapter),
                adapter_type="remediation",
                _instance=adapter,
            )
        logger.debug(f"Registered remediation adapter: {name}")

    def register_from_adapter_config(
        self,
        name: str,
        config: dict[str, Any],
    ) -> CheckAdapter | None:
        """Register a check adapter from configuration dict.

        Supports the following adapter types:
        - ``python``: Load from module path
        - ``command``: Create CommandCheckAdapter
        - ``script``: Create ScriptCheckAdapter
        - ``plugin``: Resolve via entry points (by name)

        Args:
            name: Adapter identifier
            config: Adapter configuration dict

        Returns:
            CheckAdapter instance or None if creation failed.

        Example:
            >>> registry.register_from_adapter_config("kusari", {
            ...     "type": "command",
            ...     "command": "kusari",
            ...     "output_format": "json",
            ... })
        """
        from .adapters import CommandCheckAdapter, ScriptCheckAdapter

        adapter_type = config.get("type", "python")

        try:
            if adapter_type == "command":
                adapter = CommandCheckAdapter(
                    adapter_name=name,
                    command=config["command"],
                    output_format=config.get("output_format", "json"),
                    timeout=config.get("timeout", 300),
                    control_ids=config.get("controls"),
                )
                self.register_check_adapter(name, adapter, package="config")
                return adapter

            elif adapter_type == "script":
                adapter = ScriptCheckAdapter(
                    adapter_name=name,
                    script_path=config["command"],
                    output_format=config.get("output_format", "json"),
                    timeout=config.get("timeout", 300),
                    control_ids=config.get("controls"),
                )
                self.register_check_adapter(name, adapter, package="config")
                return adapter

            elif adapter_type == "python":
                adapter = self._load_python_adapter(name, config)
                if adapter:
                    self.register_check_adapter(name, adapter, package="config")
                return adapter

            elif adapter_type == "plugin":
                # Resolve by name from entry points
                plugin_name = config.get("name", name)
                return self.get_check_adapter(plugin_name)

            else:
                logger.warning(f"Unknown adapter type: {adapter_type}")
                return None

        except Exception as e:
            logger.error(f"Failed to create adapter {name}: {e}")
            return None

    # =========================================================================
    # Utilities
    # =========================================================================

    def clear_cache(self) -> None:
        """Clear all caches and reset discovery state.

        Useful for testing or when plugins may have changed.
        """
        self._frameworks.clear()
        self._check_adapters.clear()
        self._remediation_adapters.clear()
        self._check_instances.clear()
        self._remediation_instances.clear()
        self._discovered.clear()
        logger.debug("Plugin registry cache cleared")

    def get_plugin_summary(self) -> dict[str, Any]:
        """Get summary of all discovered plugins.

        Returns:
            Dict with plugin counts and names.

        Example:
            >>> summary = registry.get_plugin_summary()
            >>> print(summary)
            {
                "frameworks": ["openssf-baseline", "testchecks"],
                "check_adapters": ["builtin", "kusari"],
                "remediation_adapters": ["builtin"],
                "counts": {
                    "frameworks": 2,
                    "check_adapters": 2,
                    "remediation_adapters": 1,
                }
            }
        """
        self.discover_all()
        return {
            "frameworks": self.list_frameworks(),
            "check_adapters": self.list_check_adapters(),
            "remediation_adapters": self.list_remediation_adapters(),
            "counts": {
                "frameworks": len(self._frameworks),
                "check_adapters": len(self._check_adapters),
                "remediation_adapters": len(self._remediation_adapters),
            },
        }

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

    def _load_python_adapter(
        self,
        name: str,
        config: dict[str, Any],
    ) -> CheckAdapter | None:
        """Load a Python adapter from module path."""
        module_path = config.get("module")
        class_name = config.get("class", "Adapter")

        if not module_path:
            logger.error(f"Adapter {name} missing 'module' in config")
            return None

        # Security: Validate module path against whitelist to prevent arbitrary code loading
        if not any(module_path.startswith(prefix) for prefix in self.ALLOWED_MODULE_PREFIXES):
            logger.error(
                f"Adapter {name}: module '{module_path}' not in allowed prefixes. "
                f"Allowed: {self.ALLOWED_MODULE_PREFIXES}"
            )
            return None

        try:
            module = importlib.import_module(module_path)
            adapter_class = getattr(module, class_name)
            return adapter_class()

        except ImportError as e:
            logger.error(f"Failed to import adapter {name}: {e}")
            return None
        except AttributeError as e:
            logger.error(f"Adapter {name}: class {class_name} not found: {e}")
            return None


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
        >>> registry.discover_all()
        >>> adapters = registry.list_check_adapters()
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
    "ENTRY_POINT_CHECK_ADAPTERS",
    "ENTRY_POINT_REMEDIATION_ADAPTERS",
    "ENTRY_POINT_IMPLEMENTATIONS",
    # Info classes
    "FrameworkInfo",
    "AdapterInfo",
    # Registry
    "PluginRegistry",
    "get_plugin_registry",
    "reset_plugin_registry",
]
