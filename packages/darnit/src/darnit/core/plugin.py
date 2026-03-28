"""Plugin system for darnit compliance implementations.

This module defines the protocol that compliance implementations must follow
to be discovered and used by the darnit framework.

Implementations register via Python entry points under 'darnit.implementations'.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class ControlSpec:
    """Specification for a compliance control.

    This is a framework-level definition that implementations provide.

    Level and domain are regular fields for backward compatibility, but are
    also copied into the tags dict for uniform filtering. This allows frameworks
    to filter on any tag key (including level and domain) uniformly.

    The tags dict can hold additional key-value pairs beyond level/domain,
    enabling flexible filtering like --tags severity>=7.0 or --tags category=auth.
    """
    control_id: str
    name: str
    description: str
    level: int | None  # Maturity level (1, 2, 3) - None if framework doesn't use levels
    domain: str | None  # Domain code (e.g., "AC", "VM") - None if not applicable
    metadata: dict[str, Any]
    tags: dict[str, Any] = field(default_factory=dict)  # Additional tags for filtering

    def __post_init__(self):
        """Copy level/domain to tags for uniform filtering."""
        if self.level is not None:
            self.tags["level"] = self.level
        if self.domain is not None:
            self.tags["domain"] = self.domain


@runtime_checkable
class ComplianceImplementation(Protocol):
    """Protocol for compliance check implementations.

    Implementations must provide this interface to be discoverable
    by the darnit framework.

    Example:
        class OSPSBaselineImplementation:
            name = "openssf-baseline"
            display_name = "OpenSSF Baseline"
            version = "0.1.0"
            spec_version = "OSPS v2025.10.10"

            def get_all_controls(self) -> List[ControlSpec]:
                ...
    """

    @property
    def name(self) -> str:
        """Unique identifier for this implementation (e.g., 'openssf-baseline')."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable name (e.g., 'OpenSSF Baseline')."""
        ...

    @property
    def version(self) -> str:
        """Implementation version (e.g., '0.1.0')."""
        ...

    @property
    def spec_version(self) -> str:
        """Specification version this implements (e.g., 'OSPS v2025.10.10')."""
        ...

    def get_all_controls(self) -> list[ControlSpec]:
        """Get all controls defined by this implementation."""
        ...

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        """Get controls for a specific maturity level."""
        ...

    def get_rules_catalog(self) -> dict[str, Any]:
        """Get the rules catalog for SARIF output."""
        ...

    def get_remediation_registry(self) -> dict[str, Any]:
        """Get the remediation registry for auto-fixes."""
        ...

    def get_framework_config_path(self) -> Path | None:
        """Get path to the framework configuration file (e.g., TOML).

        This method enables the framework to locate implementation-specific
        configuration files without hardcoding paths or importing implementation
        packages directly.

        Returns:
            Path to the framework config file, or None if not applicable.

        Example:
            # In openssf-baseline implementation:
            def get_framework_config_path(self) -> Path | None:
                return Path(__file__).parent.parent.parent / "openssf-baseline.toml"
        """
        ...

    def register_controls(self) -> None:
            """Register this implementation's Python-defined controls.

            Implementations should import their control modules here to trigger
            registration via decorators (e.g., @register_control). This allows
            the framework to load controls without knowing implementation-specific
            module paths.

            Example:
                # In openssf-baseline implementation:
                def register_controls(self) -> None:
                    from .controls import level1, level2, level3  # noqa: F401
            """
            ...

    # -------------------------------------------------------------------------
    # Optional action handlers
    # Plugins implement these to participate in the three main actions.
    # The framework checks with hasattr() before calling them, so a plugin
    # that only does checks doesn't need to implement the other two.
    # -------------------------------------------------------------------------

    def get_check_handlers(self) -> dict[str, Any]:
            """Return custom handlers for the Checks action.

            Keys are handler names (referenced in TOML via handler = "my_handler").
            Values are callables that accept a CheckContext and return a PassResult.

            Example:
                def get_check_handlers(self):
                    return {
                        "gittuf_policy_check": self._check_policy,
                        "gittuf_verify": self._verify_attestations,
                    }
            """
            return {}

    def get_context_handlers(self) -> dict[str, Any]:
            """Return custom handlers for the Collect Context action.

            Keys are handler names. Values are callables that accept a local_path
            and project_context dict, and return a dict of discovered values.

            Example:
                def get_context_handlers(self):
                    return {
                        "gittuf_collect_policy": self._collect_policy_context,
                    }
            """
            return {}

    def get_remediation_handlers(self) -> dict[str, Any]:
            """Return custom handlers for the Remediate action.

            Keys are handler names (referenced in TOML via handler = "my_fix").
            Values are callables that accept a local_path and context dict,
            and return a string describing what was done.

            Example:
                def get_remediation_handlers(self):
                    return {
                        "gittuf_init_policy": self._init_policy,
                    }
            """
            return {}


__all__ = [
    "ControlSpec",
    "ComplianceImplementation",
]
