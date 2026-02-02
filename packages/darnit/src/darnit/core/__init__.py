"""Core utilities for the darnit framework.

This module provides fundamental utilities used across the framework:

- **Logging**: Structured logging configuration
- **Models**: Data models for audit results, check results
- **Utilities**: Git detection, path validation
- **Adapters**: Check and remediation adapter interfaces
- **Plugin Registry**: Unified discovery for frameworks and adapters

Plugin System:
    The plugin registry discovers plugins via Python entry points:

    - ``darnit.frameworks`` - Framework TOML path providers
    - ``darnit.check_adapters`` - Check adapter classes
    - ``darnit.remediation_adapters`` - Remediation adapter classes

    Example::

        from darnit.core import get_plugin_registry

        registry = get_plugin_registry()
        registry.discover_all()

        # List available plugins
        print(registry.list_frameworks())
        print(registry.list_check_adapters())

        # Get an adapter by name
        adapter = registry.get_check_adapter("kusari")

See Also:
    - :mod:`darnit.core.registry` for the plugin registry
    - :mod:`darnit.core.adapters` for adapter base classes
"""

from .adapters import (
    CheckAdapter,
    RemediationAdapter,
)
from .discovery import (
    discover_implementations,
    get_default_implementation,
    get_implementation,
)
from .logging import get_logger
from .models import AuditResult, CheckResult
from .plugin import (
    ComplianceImplementation,
    ControlSpec,
)
from .registry import (
    ENTRY_POINT_CHECK_ADAPTERS,
    ENTRY_POINT_FRAMEWORKS,
    ENTRY_POINT_REMEDIATION_ADAPTERS,
    AdapterInfo,
    FrameworkInfo,
    PluginRegistry,
    get_plugin_registry,
    reset_plugin_registry,
)
from .utils import (
    detect_repo_from_git,
    get_git_commit,
    get_git_ref,
    gh_api_safe,
    validate_local_path,
)

__all__ = [
    # Logging
    "get_logger",
    # Models
    "AuditResult",
    "CheckResult",
    # Utils
    "validate_local_path",
    "detect_repo_from_git",
    "get_git_commit",
    "get_git_ref",
    "gh_api_safe",
    # Adapters
    "CheckAdapter",
    "RemediationAdapter",
    # Legacy plugin system
    "ControlSpec",
    "ComplianceImplementation",
    "discover_implementations",
    "get_implementation",
    "get_default_implementation",
    # Plugin registry (new)
    "PluginRegistry",
    "get_plugin_registry",
    "reset_plugin_registry",
    "FrameworkInfo",
    "AdapterInfo",
    "ENTRY_POINT_FRAMEWORKS",
    "ENTRY_POINT_CHECK_ADAPTERS",
    "ENTRY_POINT_REMEDIATION_ADAPTERS",
]
