"""Example Hygiene implementation for darnit.

This module provides the ExampleHygieneImplementation class that implements
the darnit ComplianceImplementation protocol for a simple "Project Hygiene
Standard" with 8 controls across 2 maturity levels.
"""

from pathlib import Path
from typing import Any

from darnit.core.plugin import ControlSpec

# Simple rules catalog for SARIF output
_RULES: dict[str, dict[str, Any]] = {
    "PH-DOC-01": {
        "name": "ReadmeExists",
        "level": 1,
        "shortDescription": {"text": "Project has a README file"},
    },
    "PH-DOC-02": {
        "name": "LicenseExists",
        "level": 1,
        "shortDescription": {"text": "Project has a LICENSE file"},
    },
    "PH-DOC-03": {
        "name": "ReadmeHasDescription",
        "level": 1,
        "shortDescription": {"text": "README contains a project description"},
    },
    "PH-SEC-01": {
        "name": "SecurityPolicyExists",
        "level": 1,
        "shortDescription": {"text": "Project has a security policy"},
    },
    "PH-CFG-01": {
        "name": "GitignoreExists",
        "level": 1,
        "shortDescription": {"text": "Project has a .gitignore file"},
    },
    "PH-CFG-02": {
        "name": "EditorConfigExists",
        "level": 1,
        "shortDescription": {"text": "Project has an .editorconfig file"},
    },
    "PH-QA-01": {
        "name": "ContributingGuideExists",
        "level": 2,
        "shortDescription": {"text": "Project has a CONTRIBUTING guide"},
    },
    "PH-CI-01": {
        "name": "CIConfigExists",
        "level": 2,
        "shortDescription": {"text": "Project has CI/CD configuration"},
    },
}


class ExampleHygieneImplementation:
    """Example 'Project Hygiene Standard' implementation for darnit.

    This implementation provides 8 controls across 2 maturity levels:
    - Level 1: 6 controls (basic project setup)
    - Level 2: 2 controls (quality practices)
    """

    @property
    def name(self) -> str:
        return "example-hygiene"

    @property
    def display_name(self) -> str:
        return "Project Hygiene Standard (Example)"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "PH v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        """Get all Project Hygiene controls."""
        controls = []
        for level in [1, 2]:
            controls.extend(self.get_controls_by_level(level))
        return controls

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        """Get controls for a specific maturity level."""
        controls = []
        for rule_id, rule in _RULES.items():
            if rule.get("level") == level:
                controls.append(
                    ControlSpec(
                        control_id=rule_id,
                        name=rule.get("name", rule_id),
                        description=rule.get("shortDescription", {}).get("text", ""),
                        level=level,
                        domain=rule_id.split("-")[1] if "-" in rule_id else "UNKNOWN",
                        metadata={},
                    )
                )
        return controls

    def get_rules_catalog(self) -> dict[str, Any]:
        """Get the rules catalog for SARIF output."""
        return _RULES

    def get_remediation_registry(self) -> dict[str, Any]:
        """Get the remediation registry for auto-fixes."""
        from .remediation.registry import REMEDIATION_REGISTRY

        return REMEDIATION_REGISTRY

    def get_framework_config_path(self) -> Path | None:
        """Get path to the example hygiene framework TOML file.

        Returns:
            Path to example-hygiene.toml in the package root.
        """
        # Navigate from implementation.py -> darnit_example -> src -> darnit-example -> toml
        return Path(__file__).parent.parent.parent / "example-hygiene.toml"

    def register_controls(self) -> None:
        """Register Python-defined controls with the sieve registry.

        No-op: all controls are now defined in TOML with handler references.
        """

    def register_sieve_handlers(self) -> None:
        """Register custom sieve handlers for verification passes."""
        from darnit.sieve.handler_registry import get_sieve_handler_registry

        from . import handlers

        registry = get_sieve_handler_registry()
        registry.set_plugin_context(self.name)

        registry.register(
            "readme_description",
            phase="deterministic",
            handler_fn=handlers.readme_description_handler,
            description="Check README has substantive content",
        )
        registry.register(
            "readme_quality",
            phase="pattern",
            handler_fn=handlers.readme_quality_handler,
            description="Heuristic check for common README sections",
        )
        registry.register(
            "ci_config",
            phase="deterministic",
            handler_fn=handlers.ci_config_handler,
            description="Glob-based search for CI/CD configuration files",
        )

        registry.set_plugin_context(None)

    def register_handlers(self) -> None:
        """Register handlers with the handler registry."""
        from darnit.core.handlers import get_handler_registry

        from . import tools

        registry = get_handler_registry()
        registry.set_plugin_context(self.name)

        registry.register_handler("example_hygiene_check", tools.example_hygiene_check)
        registry.register_handler("remediate_hygiene", tools.remediate_hygiene)

        registry.set_plugin_context(None)


__all__ = ["ExampleHygieneImplementation"]
