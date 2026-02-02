"""Pydantic models for user customization configuration (.baseline.toml).

This module defines the schema for user-facing configuration files that allow
customization of compliance framework behavior for a specific repository.

Schema Structure:
    - version: Config schema version
    - extends: Framework to inherit from
    - settings: Global settings (cache, timeout)
    - adapters: Custom adapter definitions
    - controls: Control overrides and customizations
    - control_groups: Batch configuration for multiple controls

Example:
    ```toml
    # .baseline.toml
    version = "1.0"
    extends = "openssf-baseline"

    [settings]
    cache_results = true
    timeout = 300

    [adapters.kusari]
    type = "command"
    command = "kusari"

    [controls."OSPS-VM-05.02"]
    check = { adapter = "kusari" }

    [controls."OSPS-BR-02.01"]
    status = "n/a"
    reason = "Pre-release project"
    ```
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .framework_schema import (
    AdapterConfig,
    CheckConfig,
    ControlConfig,
    PassesConfig,
    RemediationConfig,
)

# =============================================================================
# Enums
# =============================================================================


class ControlStatus(str, Enum):
    """Override status values for controls."""
    NA = "n/a"           # Not applicable
    ENABLED = "enabled"  # Explicitly enabled
    DISABLED = "disabled"  # Explicitly disabled (skip)


# =============================================================================
# User Settings
# =============================================================================


class UserSettings(BaseModel):
    """Global settings for the user configuration."""
    # Caching
    cache_results: bool = True
    cache_ttl: int = 300  # seconds

    # Timeouts
    timeout: int = 300  # default timeout for operations

    # Behavior
    fail_on_error: bool = False  # Fail audit if any check errors
    parallel_checks: bool = True  # Run independent checks in parallel
    max_parallel: int = 5  # Maximum parallel operations

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Control Override
# =============================================================================


class ControlOverride(BaseModel):
    """User override for a specific control.

    Can override:
    - status: Mark as n/a or disabled
    - check: Use different adapter
    - remediation: Use different remediation
    - passes: Override verification passes
    - Any control metadata

    Example:
        ```toml
        [controls."OSPS-VM-05.02"]
        check = { adapter = "kusari" }

        [controls."OSPS-BR-02.01"]
        status = "n/a"
        reason = "No releases yet"
        ```
    """
    # Override status
    status: ControlStatus | None = None
    reason: str | None = None  # Required if status is n/a

    # Override check routing
    check: CheckConfig | None = None

    # Override remediation routing
    remediation: RemediationConfig | None = None

    # Override verification passes (advanced)
    passes: PassesConfig | None = None

    # Additional config passed to adapter
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Control Group
# =============================================================================


class ControlGroup(BaseModel):
    """Batch configuration for multiple controls.

    Allows applying the same configuration to multiple controls at once.

    Example:
        ```toml
        [control_groups.vulnerability-management]
        controls = ["OSPS-VM-05.02", "OSPS-VM-05.03"]
        check = { adapter = "kusari" }
        ```
    """
    controls: list[str]  # List of control IDs
    check: CheckConfig | None = None
    remediation: RemediationConfig | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Custom Control (User-Defined)
# =============================================================================


class CustomControl(ControlConfig):
    """User-defined custom control.

    Extends ControlConfig to allow users to add their own controls
    beyond what the framework defines.

    Example:
        ```toml
        [controls."CUSTOM-SEC-01"]
        name = "InternalSecurityReview"
        level = 1
        domain = "SA"
        description = "Require internal security review"
        check = { adapter = "custom_script" }
        ```
    """
    # Inherit everything from ControlConfig
    # Additional fields for custom controls:
    custom: bool = True  # Marker that this is user-defined

    model_config = ConfigDict(extra="allow")


# =============================================================================
# User Configuration
# =============================================================================


class UserConfig(BaseModel):
    """User customization configuration loaded from .baseline.toml.

    This is the root model for user configuration files in repository roots.

    Provides:
    - Framework inheritance (extends)
    - Control overrides and customizations
    - Custom adapter definitions
    - Custom control definitions
    - Batch configuration via control groups

    Example:
        ```toml
        version = "1.0"
        extends = "openssf-baseline"

        [settings]
        cache_results = true
        timeout = 300

        [adapters.kusari]
        type = "command"
        command = "kusari"
        output_format = "json"

        [adapters.custom_script]
        type = "script"
        command = "./scripts/check-compliance.sh"

        [controls."OSPS-VM-05.02"]
        check = { adapter = "kusari" }

        [controls."OSPS-VM-05.03"]
        check = { adapter = "kusari" }

        [controls."OSPS-BR-02.01"]
        status = "n/a"
        reason = "Pre-1.0 project, no releases yet"

        [control_groups.vulnerability-management]
        controls = ["OSPS-VM-05.02", "OSPS-VM-05.03"]
        check = { adapter = "kusari" }

        # Custom control
        [controls."CUSTOM-SEC-01"]
        name = "InternalSecurityReview"
        level = 1
        domain = "SA"
        description = "Require internal security review sign-off"
        check = { adapter = "custom_script" }
        ```
    """
    # Schema version
    version: str = "1.0"

    # Framework to inherit from
    extends: str | None = None  # e.g., "openssf-baseline"

    # Global settings
    settings: UserSettings = Field(default_factory=UserSettings)

    # Custom adapter definitions
    adapters: dict[str, AdapterConfig] = Field(default_factory=dict)

    # Control overrides and custom controls
    # Values can be ControlOverride (for overrides) or CustomControl (for new controls)
    controls: dict[str, ControlOverride | CustomControl | dict[str, Any]] = Field(
        default_factory=dict
    )

    # Control groups for batch configuration
    control_groups: dict[str, ControlGroup] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def get_control_override(self, control_id: str) -> ControlOverride | None:
        """Get override for a specific control, including from groups."""
        # Check direct override first
        override = self.controls.get(control_id)
        if override:
            if isinstance(override, ControlOverride):
                return override
            elif isinstance(override, dict):
                return ControlOverride(**override)

        # Check control groups
        for group in self.control_groups.values():
            if control_id in group.controls:
                return ControlOverride(
                    check=group.check,
                    remediation=group.remediation,
                    config=group.config,
                )

        return None

    def is_control_applicable(self, control_id: str) -> tuple:
        """Check if control is applicable (not marked n/a or disabled).

        Returns:
            Tuple of (is_applicable, reason_if_not)
        """
        override = self.get_control_override(control_id)
        if override and override.status in (ControlStatus.NA, ControlStatus.DISABLED):
            return False, override.reason
        return True, None

    def get_check_adapter(self, control_id: str) -> str | None:
        """Get the adapter name for checking a control, if overridden."""
        override = self.get_control_override(control_id)
        if override and override.check:
            return override.check.adapter
        return None

    def get_custom_controls(self) -> dict[str, CustomControl]:
        """Get all user-defined custom controls."""
        custom = {}
        for control_id, control in self.controls.items():
            # Custom controls have required fields like name, level, domain
            if isinstance(control, dict):
                if all(k in control for k in ("name", "level", "domain")):
                    custom[control_id] = CustomControl(**control)
            elif isinstance(control, CustomControl):
                custom[control_id] = control
        return custom

    def get_adapter_config(self, name: str) -> AdapterConfig | None:
        """Get adapter configuration by name."""
        return self.adapters.get(name)

    def get_all_adapter_names(self) -> list[str]:
        """Get names of all defined adapters."""
        return list(self.adapters.keys())


# =============================================================================
# Factory Functions
# =============================================================================


def create_user_config(
    extends: str | None = "openssf-baseline",
) -> UserConfig:
    """Create a minimal user configuration.

    Args:
        extends: Framework to inherit from

    Returns:
        Minimal UserConfig instance
    """
    return UserConfig(
        version="1.0",
        extends=extends,
        settings=UserSettings(),
    )


def create_user_config_with_kusari(
    controls: list[str] | None = None,
) -> UserConfig:
    """Create a user configuration with Kusari adapter for specified controls.

    Args:
        controls: List of control IDs to use Kusari for
            (defaults to VM-05 controls)

    Returns:
        UserConfig with Kusari adapter configured
    """
    if controls is None:
        controls = ["OSPS-VM-05.02", "OSPS-VM-05.03"]

    config = UserConfig(
        version="1.0",
        extends="openssf-baseline",
        adapters={
            "kusari": {
                "type": "command",
                "command": "kusari",
                "output_format": "json",
            }
        },
        control_groups={
            "kusari-controls": ControlGroup(
                controls=controls,
                check=CheckConfig(adapter="kusari"),
            )
        },
    )
    return config
