"""HelloImplementation — minimal ComplianceImplementation example.

This is the smallest implementation that satisfies the
`darnit.core.plugin.ComplianceImplementation` protocol. It defines a single
control via the bundled TOML config (the TOML-First Architecture principle
from the project constitution) and does not register any Python-defined
controls or remediation handlers.

Copy this file as a starting point for your own implementation. Replace
the names, descriptions, and TOML reference; add Python control modules
and handlers as your scope grows.
"""

from __future__ import annotations

from pathlib import Path


class HelloImplementation:
    """A single-control compliance implementation for documentation purposes.

    The framework discovers this class via the `register()` entry point in
    `__init__.py`. At audit time, it loads the controls from the TOML file
    that `get_framework_config_path()` returns and runs them.
    """

    # ---- Required identity properties ---------------------------------------

    @property
    def name(self) -> str:
        """Unique slug for this plugin. Must match the key in pyproject.toml's
        [project.entry-points."darnit.implementations"] table."""
        return "hello"

    @property
    def display_name(self) -> str:
        return "Hello — Minimal Darnit Plugin"

    @property
    def version(self) -> str:
        """Your plugin's version. Independent of the darnit framework version."""
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        """Version of the compliance specification this plugin implements.
        For real plugins this would track an external spec
        (e.g., "OSPS v2025.10.10"); for this example it's just a marker."""
        return "hello v0.1"

    # ---- Required protocol methods ------------------------------------------

    def get_framework_config_path(self) -> Path | None:
        """Return the absolute path to the bundled TOML config.

        The framework loads this file at audit time to discover controls,
        their pass logic, and their metadata. TOML is the source of truth
        (see CLAUDE.md "TOML-First Architecture").
        """
        return Path(__file__).parent / "hello.toml"

    # ---- Optional handler hook ----------------------------------------------

    def register_handlers(self) -> None:
        """Register this plugin's Python handlers (none here).

        The framework calls this before it loads or audits the `hello`
        framework. A plugin with custom checks registers its step types here
        with `darnit.sieve.handler_registry.get_sieve_handler_registry()`, and
        its MCP tool handlers with `darnit.core.handlers.get_handler_registry()`;
        see docs/packaging-plugins.md. Registering at module import instead
        works, but the framework cannot see it. This example's single control
        uses only built-in step types, so there is nothing to register.
        """
        return None
