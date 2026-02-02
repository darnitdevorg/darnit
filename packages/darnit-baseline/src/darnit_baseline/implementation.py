"""OpenSSF Baseline implementation for darnit.

This module provides the OSPSBaselineImplementation class that implements
the darnit ComplianceImplementation protocol for OpenSSF Baseline (OSPS v2025.10.10).
"""

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

    def get_check_functions(self) -> dict[str, Any]:
        """Get the check functions for running audits."""
        from .checks import (
            run_level1_checks,
            run_level2_checks,
            run_level3_checks,
        )
        return {
            "level1": run_level1_checks,
            "level2": run_level2_checks,
            "level3": run_level3_checks,
        }

    def get_rules_catalog(self) -> dict[str, Any]:
        """Get the rules catalog for SARIF output."""
        from .rules.catalog import OSPS_RULES
        return OSPS_RULES

    def get_remediation_registry(self) -> dict[str, Any]:
        """Get the remediation registry for auto-fixes."""
        from .remediation.registry import REMEDIATION_REGISTRY
        return REMEDIATION_REGISTRY


__all__ = ["OSPSBaselineImplementation"]
