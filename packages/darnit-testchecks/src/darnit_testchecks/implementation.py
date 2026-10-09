"""The testchecks-steps implementation: a test plugin with its own step types.

The trivial ``testchecks`` framework uses only built-in step types and needs
no implementation. ``testchecks-steps`` is the fixture for a plugin that
registers custom sieve step types through ``register_handlers()``.
"""

from importlib.resources import files
from pathlib import Path


class CustomStepsImplementation:
    """Two controls built on three plugin step types."""

    @property
    def name(self) -> str:
        return "testchecks-steps"

    @property
    def display_name(self) -> str:
        return "Test Checks: Plugin Step Types"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "test-steps-v1"

    def get_framework_config_path(self) -> Path | None:
        path = Path(str(files(__package__) / "testchecks-steps.toml"))
        if not path.is_file():
            raise FileNotFoundError(f"testchecks-steps.toml not found in the installed darnit_testchecks package at {path}")
        return path

    def register_handlers(self) -> None:
        """Register the plugin's sieve step types."""
        from darnit.sieve.handler_registry import get_sieve_handler_registry

        from . import handlers

        registry = get_sieve_handler_registry()
        registry.set_plugin_context(self.name)

        registry.register(
            "testchecks_readme_description",
            phase="deterministic",
            handler_fn=handlers.readme_description_handler,
            description="Check README has substantive content",
            settings={"readme_names"},
        )
        registry.register(
            "testchecks_readme_quality",
            phase="pattern",
            handler_fn=handlers.readme_quality_handler,
            description="Heuristic check for common README sections",
            settings={"sections", "min_sections"},
        )
        registry.register(
            "testchecks_ci_config",
            phase="deterministic",
            handler_fn=handlers.ci_config_handler,
            description="Glob-based search for CI/CD configuration files",
            settings={"patterns"},
        )

        registry.set_plugin_context(None)


__all__ = ["CustomStepsImplementation"]
