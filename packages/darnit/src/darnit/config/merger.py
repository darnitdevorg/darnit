"""Config merger for combining framework and user configurations.

This module provides functionality to merge framework configurations with
user customizations, applying proper override semantics.

Merge Rules:
    1. Scalar values: User overrides framework
    2. Objects/dicts: Deep merge (user keys override, framework keys preserved)
    3. Arrays/lists: User replaces framework entirely
    4. Special keys:
        - status = "n/a" → Marks control as not applicable
        - check = {...} → Replaces entire check config
        - extends = "..." → Specifies base framework

Framework Resolution:
    The ``extends`` field in user config can reference frameworks by name.
    Resolution order:

    1. Explicit path (if ``extends`` contains "/" or ends in ".toml")
    2. Entry point lookup via :class:`~darnit.core.registry.PluginRegistry`

    Example::

        # .baseline.toml
        extends = "openssf-baseline"  # Resolved via entry points

Example:
    Loading and merging configurations::

        from darnit.config.merger import (
            load_framework_config,
            load_framework_by_name,
            load_user_config,
            load_effective_config,
        )

        # Load by path
        framework = load_framework_config(Path("openssf-baseline.toml"))

        # Load by name (via entry points)
        framework = load_framework_by_name("openssf-baseline")

        # Load user config and merge
        effective = load_effective_config(
            framework_path=Path("openssf-baseline.toml"),
            repo_path=Path("/path/to/repo"),
        )

        # Or load by framework name
        effective = load_effective_config_by_name(
            framework_name="openssf-baseline",
            repo_path=Path("/path/to/repo"),
        )

See Also:
    - :mod:`darnit.core.registry` for plugin discovery
    - :mod:`darnit.config.framework_schema` for framework config schema
    - :mod:`darnit.config.user_schema` for user config schema
"""

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from .framework_schema import (
    AdapterConfig,
    ControlConfig,
    FrameworkConfig,
    FrameworkDefaults,
)
from .user_schema import (
    ControlOverride,
    ControlStatus,
    UserConfig,
)

# =============================================================================
# Effective Configuration
# =============================================================================


@dataclass
class EffectiveControl:
    """Merged control configuration with framework + user overrides.

    Level and domain are optional to support frameworks that don't use
    maturity levels or domain categorization. Use the tags dict for
    flexible key-value metadata that can be filtered uniformly.
    """
    control_id: str
    name: str
    description: str

    # Optional framework-specific fields
    level: int | None = None  # Maturity level - None if framework doesn't use levels
    domain: str | None = None  # Domain code - None if not applicable

    # Source tracking
    from_framework: bool = True
    from_user: bool = False

    # Status
    status: ControlStatus | None = None
    status_reason: str | None = None

    # Check routing
    check_adapter: str = "builtin"
    check_handler: str | None = None
    check_config: dict[str, Any] = field(default_factory=dict)

    # Remediation routing
    remediation_adapter: str = "builtin"
    remediation_handler: str | None = None
    remediation_config: dict[str, Any] = field(default_factory=dict)

    # Framework pass configuration (for sieve)
    passes_config: dict[str, Any] | None = None

    # Flexible key-value tags for filtering and metadata
    tags: dict[str, Any] = field(default_factory=dict)
    security_severity: float | None = None
    docs_url: str | None = None

    def is_applicable(self) -> bool:
        """Check if control should be evaluated."""
        return self.status not in (ControlStatus.NA, ControlStatus.DISABLED)


@dataclass
class EffectiveConfig:
    """Merged configuration combining framework and user configs.

    This is the runtime configuration used by the audit engine.
    """
    # Framework metadata
    framework_name: str
    framework_version: str
    spec_version: str | None = None

    # Merged adapters (framework + user)
    adapters: dict[str, AdapterConfig] = field(default_factory=dict)

    # Merged controls
    controls: dict[str, EffectiveControl] = field(default_factory=dict)

    # Settings from user config
    cache_results: bool = True
    cache_ttl: int = 300
    timeout: int = 300

    # Source configs (for reference)
    _framework_config: FrameworkConfig | None = None
    _user_config: UserConfig | None = None

    def get_controls_by_level(self, level: int) -> dict[str, EffectiveControl]:
        """Get all applicable controls at a specific level.

        Note: Controls without a level (level=None) are not included.
        """
        return {
            cid: ctrl for cid, ctrl in self.controls.items()
            if ctrl.level == level and ctrl.is_applicable()
        }

    def get_controls_by_domain(self, domain: str) -> dict[str, EffectiveControl]:
        """Get all applicable controls in a specific domain.

        Note: Controls without a domain (domain=None) are not included.
        """
        return {
            cid: ctrl for cid, ctrl in self.controls.items()
            if ctrl.domain == domain and ctrl.is_applicable()
        }

    def get_excluded_controls(self) -> dict[str, str]:
        """Get all non-applicable controls with reasons."""
        return {
            cid: ctrl.status_reason or "No reason provided"
            for cid, ctrl in self.controls.items()
            if not ctrl.is_applicable()
        }

    def get_adapter(self, name: str) -> AdapterConfig | None:
        """Get adapter configuration by name."""
        return self.adapters.get(name)


# =============================================================================
# Merge Functions
# =============================================================================


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries.

    Rules:
    - Scalar values: override replaces base
    - Dicts: recursive merge
    - Lists: override replaces base entirely

    Args:
        base: Base dictionary (from framework)
        override: Override dictionary (from user)

    Returns:
        Merged dictionary
    """
    result = copy.deepcopy(base)

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursive merge for nested dicts
            result[key] = deep_merge(result[key], value)
        else:
            # Override scalar or list values
            result[key] = copy.deepcopy(value)

    return result


def merge_control(
    control_id: str,
    framework_control: ControlConfig | None,
    user_override: ControlOverride | None,
    defaults: FrameworkDefaults,
) -> EffectiveControl:
    """Merge a single control's framework config with user override.

    Args:
        control_id: Control identifier
        framework_control: Framework definition (may be None for custom controls)
        user_override: User override (may be None)
        defaults: Framework defaults

    Returns:
        Merged EffectiveControl
    """
    # Start with framework config or create minimal for custom control
    if framework_control:
        # Build tags dict - start with explicit tags, then add level/domain if present
        tags = dict(framework_control.tags) if framework_control.tags else {}
        if framework_control.level is not None:
            tags["level"] = framework_control.level
        if framework_control.domain is not None:
            tags["domain"] = framework_control.domain
        if framework_control.security_severity is not None:
            tags["security_severity"] = framework_control.security_severity

        effective = EffectiveControl(
            control_id=control_id,
            name=framework_control.name,
            level=framework_control.level,
            domain=framework_control.domain,
            description=framework_control.description,
            from_framework=True,
            check_adapter=defaults.check_adapter,
            remediation_adapter=defaults.remediation_adapter,
            tags=tags,
            security_severity=framework_control.security_severity,
            docs_url=framework_control.docs_url,
        )

        # Apply framework check config
        if framework_control.check:
            effective.check_adapter = framework_control.check.adapter
            effective.check_handler = framework_control.check.handler
            effective.check_config = dict(framework_control.check.config)

        # Apply framework remediation config
        if framework_control.remediation:
            effective.remediation_adapter = framework_control.remediation.adapter
            effective.remediation_handler = framework_control.remediation.handler
            effective.remediation_config = dict(framework_control.remediation.config)

        # Store passes config for sieve
        if framework_control.passes:
            effective.passes_config = framework_control.passes.model_dump()

    else:
        # Custom control from user - name and description required, level/domain optional
        effective = EffectiveControl(
            control_id=control_id,
            name=control_id,
            description="User-defined control",
            from_framework=False,
            from_user=True,
        )

    # Apply user overrides
    if user_override:
        effective.from_user = True

        # Status override
        if user_override.status:
            effective.status = user_override.status
            effective.status_reason = user_override.reason

        # Check override
        if user_override.check:
            effective.check_adapter = user_override.check.adapter
            if user_override.check.handler:
                effective.check_handler = user_override.check.handler
            if user_override.check.config:
                effective.check_config = deep_merge(
                    effective.check_config,
                    user_override.check.config,
                )

        # Remediation override
        if user_override.remediation:
            effective.remediation_adapter = user_override.remediation.adapter
            if user_override.remediation.handler:
                effective.remediation_handler = user_override.remediation.handler
            if user_override.remediation.config:
                effective.remediation_config = deep_merge(
                    effective.remediation_config,
                    user_override.remediation.config,
                )

        # Passes override (advanced)
        if user_override.passes:
            if effective.passes_config:
                effective.passes_config = deep_merge(
                    effective.passes_config,
                    user_override.passes.model_dump(exclude_none=True),
                )
            else:
                effective.passes_config = user_override.passes.model_dump()

    return effective


def merge_configs(
    framework: FrameworkConfig,
    user: UserConfig | None = None,
) -> EffectiveConfig:
    """Merge framework and user configurations into effective config.

    Args:
        framework: Framework configuration
        user: User configuration (optional)

    Returns:
        Merged EffectiveConfig ready for use
    """
    # Start with framework metadata
    effective = EffectiveConfig(
        framework_name=framework.metadata.name,
        framework_version=framework.metadata.version,
        spec_version=framework.metadata.spec_version,
        _framework_config=framework,
        _user_config=user,
    )

    # Merge adapters (framework first, then user overrides)
    effective.adapters = dict(framework.adapters)
    if user:
        for name, adapter in user.adapters.items():
            effective.adapters[name] = adapter

    # Apply user settings
    if user:
        effective.cache_results = user.settings.cache_results
        effective.cache_ttl = user.settings.cache_ttl
        effective.timeout = user.settings.timeout

    # Collect all control IDs
    all_control_ids: set[str] = set(framework.controls.keys())
    if user:
        all_control_ids.update(user.controls.keys())

    # Merge each control
    for control_id in all_control_ids:
        framework_control = framework.controls.get(control_id)
        user_override = user.get_control_override(control_id) if user else None

        # Handle custom controls (user-defined, not in framework)
        if not framework_control and user:
            user_control = user.controls.get(control_id)
            if isinstance(user_control, dict):
                # Check if this is a custom control definition
                if all(k in user_control for k in ("name", "level", "domain")):
                    # Create a ControlConfig from user definition
                    framework_control = ControlConfig(**user_control)

        effective.controls[control_id] = merge_control(
            control_id=control_id,
            framework_control=framework_control,
            user_override=user_override,
            defaults=framework.defaults,
        )

    return effective


# =============================================================================
# Loading Functions
# =============================================================================


def load_framework_config(path: Path) -> FrameworkConfig:
    """Load framework configuration from TOML file.

    Args:
        path: Path to framework TOML file

    Returns:
        Parsed FrameworkConfig

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Framework config not found: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    return FrameworkConfig(**data)


def load_user_config(repo_path: Path) -> UserConfig | None:
    """Load user configuration from repository.

    Searches for .baseline.toml in the repository root.

    Args:
        repo_path: Path to repository

    Returns:
        Parsed UserConfig or None if not found
    """
    config_path = Path(repo_path) / ".baseline.toml"

    if not config_path.exists():
        return None

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    return UserConfig(**data)


def load_effective_config(
    framework_path: Path,
    repo_path: Path | None = None,
) -> EffectiveConfig:
    """Load and merge framework and user configurations.

    Args:
        framework_path: Path to framework TOML file
        repo_path: Path to repository (for .baseline.toml)

    Returns:
        Merged EffectiveConfig
    """
    framework = load_framework_config(framework_path)

    user = None
    if repo_path:
        user = load_user_config(repo_path)

    return merge_configs(framework, user)


# =============================================================================
# Framework Name Resolution (via PluginRegistry)
# =============================================================================


def resolve_framework_path(name_or_path: str) -> Path | None:
    """Resolve a framework name or path to an actual path.

    Resolution order:
    1. If contains "/" or ends with ".toml", treat as path
    2. Otherwise, look up via PluginRegistry entry points

    Args:
        name_or_path: Framework name (e.g., "openssf-baseline") or path

    Returns:
        Resolved Path or None if not found

    Example:
        >>> path = resolve_framework_path("openssf-baseline")
        >>> if path:
        ...     config = load_framework_config(path)

        >>> path = resolve_framework_path("./custom.toml")
        >>> # Returns Path("./custom.toml")
    """
    # Check if it looks like a path
    if "/" in name_or_path or name_or_path.endswith(".toml"):
        return Path(name_or_path)

    # Try to resolve via PluginRegistry
    try:
        from darnit.core.registry import get_plugin_registry

        registry = get_plugin_registry()
        return registry.get_framework_path(name_or_path)
    except ImportError:
        return None


def load_framework_by_name(name: str) -> FrameworkConfig:
    """Load a framework configuration by name.

    Resolves the framework name via PluginRegistry entry points.

    Args:
        name: Framework identifier (e.g., "openssf-baseline")

    Returns:
        Parsed FrameworkConfig

    Raises:
        ValueError: If framework not found

    Example:
        >>> framework = load_framework_by_name("openssf-baseline")
        >>> print(f"Loaded {len(framework.controls)} controls")
    """
    path = resolve_framework_path(name)

    if path is None:
        raise ValueError(
            f"Framework '{name}' not found. "
            f"Ensure the framework package is installed and registers "
            f"a 'darnit.frameworks' entry point."
        )

    if not path.exists():
        raise FileNotFoundError(
            f"Framework '{name}' resolved to {path}, but file not found"
        )

    return load_framework_config(path)


def list_available_frameworks() -> list[str]:
    """List all available framework names.

    Discovers frameworks via PluginRegistry entry points.

    Returns:
        Sorted list of framework names

    Example:
        >>> for name in list_available_frameworks():
        ...     print(f"Available: {name}")
    """
    try:
        from darnit.core.registry import get_plugin_registry

        registry = get_plugin_registry()
        return registry.list_frameworks()
    except ImportError:
        return []


def load_effective_config_by_name(
    framework_name: str,
    repo_path: Path | None = None,
) -> EffectiveConfig:
    """Load and merge framework (by name) and user configurations.

    This is a convenience function that combines framework name resolution
    with config loading and merging.

    Args:
        framework_name: Framework identifier (e.g., "openssf-baseline")
        repo_path: Path to repository (for .baseline.toml)

    Returns:
        Merged EffectiveConfig

    Raises:
        ValueError: If framework not found

    Example:
        >>> effective = load_effective_config_by_name(
        ...     "openssf-baseline",
        ...     Path("/path/to/repo"),
        ... )
        >>> print(f"Loaded {len(effective.controls)} controls")
    """
    framework = load_framework_by_name(framework_name)

    user = None
    if repo_path:
        user = load_user_config(repo_path)

    return merge_configs(framework, user)


def load_effective_config_auto(
    repo_path: Path,
    framework_path: Path | None = None,
    framework_name: str | None = None,
) -> EffectiveConfig:
    """Load effective config with automatic framework resolution.

    Resolution order:
    1. Explicit framework_path if provided
    2. Explicit framework_name if provided
    3. ``extends`` field from user's .baseline.toml
    4. Default to "openssf-baseline"

    Args:
        repo_path: Path to repository
        framework_path: Explicit path to framework TOML (optional)
        framework_name: Explicit framework name (optional)

    Returns:
        Merged EffectiveConfig

    Raises:
        ValueError: If framework cannot be resolved

    Example:
        >>> # Uses framework specified in .baseline.toml
        >>> effective = load_effective_config_auto(Path("/path/to/repo"))

        >>> # Override with specific framework
        >>> effective = load_effective_config_auto(
        ...     Path("/path/to/repo"),
        ...     framework_name="testchecks",
        ... )
    """
    # Load user config first to check for extends
    user = load_user_config(repo_path)

    # Determine framework
    if framework_path:
        framework = load_framework_config(framework_path)
    elif framework_name:
        framework = load_framework_by_name(framework_name)
    elif user and user.extends:
        # Resolve from user config's extends field
        path = resolve_framework_path(user.extends)
        if path is None:
            raise ValueError(
                f"Framework '{user.extends}' specified in .baseline.toml "
                f"not found. Ensure the framework package is installed."
            )
        framework = load_framework_config(path)
    else:
        # Default to openssf-baseline
        try:
            framework = load_framework_by_name("openssf-baseline")
        except ValueError:
            raise ValueError(
                "No framework specified and 'openssf-baseline' not found. "
                "Please install darnit-baseline or specify a framework."
            ) from None

    return merge_configs(framework, user)


# =============================================================================
# Validation Functions
# =============================================================================


def validate_framework_config(config: FrameworkConfig) -> list[str]:
    """Validate framework configuration for common issues.

    Args:
        config: Framework configuration to validate

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check metadata
    if not config.metadata.name:
        errors.append("Framework name is required")
    if not config.metadata.display_name:
        errors.append("Framework display_name is required")

    # Check controls
    for control_id, control in config.controls.items():
        if not control.name:
            errors.append(f"Control {control_id} missing name")
        # Level and domain are optional - only validate if present
        if control.level is not None and control.level not in (1, 2, 3):
            errors.append(f"Control {control_id} has invalid level: {control.level}")

        # Check adapter references exist
        if control.check and control.check.adapter != "builtin":
            if control.check.adapter not in config.adapters:
                errors.append(
                    f"Control {control_id} references unknown adapter: "
                    f"{control.check.adapter}"
                )

    return errors


def validate_user_config(
    user: UserConfig,
    framework: FrameworkConfig | None = None,
) -> list[str]:
    """Validate user configuration for common issues.

    Args:
        user: User configuration to validate
        framework: Framework to validate against (optional)

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check adapter references
    for control_id, override in user.controls.items():
        if isinstance(override, dict):
            check = override.get("check", {})
            adapter = check.get("adapter") if isinstance(check, dict) else None
        elif isinstance(override, ControlOverride) and override.check:
            adapter = override.check.adapter
        else:
            adapter = None

        if adapter and adapter != "builtin":
            if adapter not in user.adapters:
                # Check framework adapters too
                if not framework or adapter not in framework.adapters:
                    errors.append(
                        f"Control {control_id} references unknown adapter: {adapter}"
                    )

    # Check control groups reference valid controls
    if framework:
        framework_controls = set(framework.controls.keys())
        for _group_name, group in user.control_groups.items():
            for control_id in group.controls:
                if control_id not in framework_controls:
                    # Could be a custom control, so just warn
                    pass

    return errors
