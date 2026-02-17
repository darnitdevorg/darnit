"""OpenSSF Baseline implementation for darnit.

This module provides the OSPSBaselineImplementation class that implements
the darnit ComplianceImplementation protocol for OpenSSF Baseline (OSPS v2025.10.10).
"""

from pathlib import Path
from typing import Any

from darnit.core.plugin import ControlSpec


class OSPSBaselineImplementation:
    """OpenSSF Baseline (OSPS v2025.10.10) implementation for darnit.

    This implementation provides 62 controls across 3 maturity levels:
    - Level 1: 24 controls (basic security hygiene)
    - Level 2: 19 controls (intermediate security)
    - Level 3: 19 controls (advanced security)
    """

    @property
    def name(self) -> str:
        return "openssf-baseline"

    @property
    def display_name(self) -> str:
        return "OpenSSF Baseline"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "OSPS v2025.10.10"

    def get_all_controls(self) -> list[ControlSpec]:
        """Get all OSPS controls."""
        controls = []
        for level in [1, 2, 3]:
            controls.extend(self.get_controls_by_level(level))
        return controls

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        """Get controls for a specific maturity level."""
        from .rules.catalog import OSPS_RULES

        controls = []
        for rule_id, rule in OSPS_RULES.items():
            if rule.get("level") == level:
                controls.append(ControlSpec(
                    control_id=rule_id,
                    name=rule.get("name", rule_id),
                    description=rule.get("shortDescription", {}).get("text", ""),
                    level=level,
                    domain=rule_id.split("-")[1] if "-" in rule_id else "UNKNOWN",
                    metadata={
                        "full": rule.get("fullDescription", {}).get("text", ""),
                        "help_uri": rule.get("helpUri", ""),
                    }
                ))
        return controls

    def get_rules_catalog(self) -> dict[str, Any]:
        """Get the rules catalog for SARIF output."""
        from .rules.catalog import OSPS_RULES
        return OSPS_RULES

    def get_remediation_registry(self) -> dict[str, Any]:
        """Get remediation metadata derived from TOML.

        Returns a dict mapping control IDs to their remediation metadata
        (safe, requires_api, handler types).  This replaces the former
        hardcoded REMEDIATION_CATEGORIES dict.
        """
        registry: dict[str, Any] = {}
        try:
            import tomllib

            toml_path = self.get_framework_config_path()
            if not toml_path or not toml_path.exists():
                return registry

            with open(toml_path, "rb") as f:
                data = tomllib.load(f)

            from darnit.config.framework_schema import FrameworkConfig

            fw = FrameworkConfig(**data)
            for cid, control in fw.controls.items():
                if control.remediation and control.remediation.handlers:
                    handler_types = [h.handler for h in control.remediation.handlers]
                    registry[cid] = {
                        "description": control.description or cid,
                        "safe": control.remediation.safe,
                        "requires_api": control.remediation.requires_api,
                        "handler_types": handler_types,
                    }
        except Exception:
            pass  # Best-effort
        return registry

    def get_framework_config_path(self) -> Path | None:
        """Get path to the OpenSSF Baseline framework TOML file.

        Returns:
            Path to openssf-baseline.toml in the package root.
        """
        # Navigate from implementation.py to package root:
        # implementation.py -> darnit_baseline -> src -> darnit-baseline -> openssf-baseline.toml
        return Path(__file__).parent.parent.parent / "openssf-baseline.toml"

    def register_controls(self) -> None:
        """No-op. Control definitions come exclusively from TOML.

        This method exists for ComplianceImplementation protocol compatibility.
        All control definitions are loaded from openssf-baseline.toml by the
        framework's TOML control loader. Plugins should use register_handlers()
        to add custom sieve/remediation handlers.
        """
        pass

    def register_handlers(self) -> None:
        """Register handlers with the handler registry.

        This explicitly registers all tool handlers with the registry.
        The handlers are then available by short name in TOML configurations.

        This method can be called multiple times (e.g., after clearing the registry
        in tests) to re-register handlers.
        """
        from darnit.core.handlers import get_handler_registry

        from . import tools

        # Set plugin context so handlers know which plugin registered them
        registry = get_handler_registry()
        registry.set_plugin_context(self.name)

        # Explicitly register each handler
        # This allows re-registration after registry.clear() in tests
        handlers = [
            ("audit_openssf_baseline", tools.audit_openssf_baseline),
            ("list_available_checks", tools.list_available_checks),
            ("get_project_config", tools.get_project_config),
            ("create_security_policy", tools.create_security_policy),
            ("enable_branch_protection", tools.enable_branch_protection),
            ("init_project_config", tools.init_project_config),
            ("confirm_project_context", tools.confirm_project_context),
            ("get_pending_context", tools.get_pending_context),
            ("generate_threat_model", tools.generate_threat_model),
            ("generate_attestation", tools.generate_attestation),
            ("remediate_audit_findings", tools.remediate_audit_findings),
            ("create_remediation_branch", tools.create_remediation_branch),
            ("commit_remediation_changes", tools.commit_remediation_changes),
            ("create_remediation_pr", tools.create_remediation_pr),
            ("get_remediation_status", tools.get_remediation_status),
            ("create_test_repository", tools.create_test_repository),
        ]

        for name, handler in handlers:
            registry.register_handler(name, handler)

        # Clear plugin context
        registry.set_plugin_context(None)


__all__ = ["OSPSBaselineImplementation"]
