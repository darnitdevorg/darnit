"""Core utilities for the darnit framework.

This module provides fundamental utilities used across the framework:

- **Logging**: Structured logging configuration
- **Models**: Data models for audit results, check results
- **Utilities**: Git detection, path validation
- **Plugin Registry**: Discovery of frameworks

Plugin System:
    The plugin registry discovers frameworks via the ``darnit.frameworks``
    entry point group (framework TOML path providers).

    Example::

        from darnit.core import get_plugin_registry

        registry = get_plugin_registry()
        print(registry.list_frameworks())

See Also:
    - :mod:`darnit.core.registry` for the plugin registry
"""

from .discovery import (
    discover_implementations,
    get_implementation,
)
from .handlers import (
    HandlerInfo,
    HandlerRegistry,
    PassInfo,
    TemplateInfo,
    get_handler,
    get_handler_registry,
    get_template,
    list_handlers,
    register_handler,
    register_pass,
)
from .logging import get_logger
from .models import AuditResult, CheckResult
from .plugin import (
    ComplianceImplementation,
    ControlSpec,
)
from .registry import (
    ENTRY_POINT_FRAMEWORKS,
    FrameworkInfo,
    PluginRegistry,
    get_plugin_registry,
    reset_plugin_registry,
)
from .utils import (
    detect_owner_repo,
    detect_repo_from_git,
    get_git_commit,
    get_git_ref,
    gh_api_safe,
    validate_local_path,
)
from .verification import (
    DEFAULT_TRUSTED_PUBLISHERS,
    AttestationInfo,
    PluginVerifier,
    VerificationCache,
    VerificationConfig,
    VerificationResult,
    verify_plugin,
)

__all__ = [
    # Logging
    "get_logger",
    # Models
    "AuditResult",
    "CheckResult",
    # Utils
    "validate_local_path",
    "detect_owner_repo",
    "detect_repo_from_git",
    "get_git_commit",
    "get_git_ref",
    "gh_api_safe",
    # Legacy plugin system
    "ControlSpec",
    "ComplianceImplementation",
    "discover_implementations",
    "get_implementation",
    # Plugin registry (new)
    "PluginRegistry",
    "get_plugin_registry",
    "reset_plugin_registry",
    "FrameworkInfo",
    "ENTRY_POINT_FRAMEWORKS",
    # Handler registry (new)
    "HandlerRegistry",
    "HandlerInfo",
    "PassInfo",
    "TemplateInfo",
    "get_handler_registry",
    "get_handler",
    "list_handlers",
    "get_template",
    "register_handler",
    "register_pass",
    # Verification (Sigstore)
    "PluginVerifier",
    "VerificationConfig",
    "VerificationResult",
    "VerificationCache",
    "AttestationInfo",
    "verify_plugin",
    "DEFAULT_TRUSTED_PUBLISHERS",
]
