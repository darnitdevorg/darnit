"""Example Hygiene implementation for darnit.

This module provides the ExampleHygieneImplementation class that implements
the darnit ComplianceImplementation protocol for a simple "Project Hygiene
Standard" with 8 controls across 2 maturity levels.
"""

from pathlib import Path


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

    def get_framework_config_path(self) -> Path | None:
        """Get path to the example hygiene framework TOML file.

        Returns:
            Path to example-hygiene.toml in the package root.
        """
        # Navigate from implementation.py -> darnit_example -> src -> darnit-example -> toml
        return Path(__file__).parent.parent.parent / "example-hygiene.toml"

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
            settings={"readme_names"},
        )
        registry.register(
            "readme_quality",
            phase="pattern",
            handler_fn=handlers.readme_quality_handler,
            description="Heuristic check for common README sections",
            settings={"sections", "min_sections"},
        )
        registry.register(
            "ci_config",
            phase="deterministic",
            handler_fn=handlers.ci_config_handler,
            description="Glob-based search for CI/CD configuration files",
            settings={"patterns"},
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
