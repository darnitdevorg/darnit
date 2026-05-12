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
from typing import Any


class HelloImplementation:
    """A single-control compliance implementation for documentation purposes.

    The framework discovers this class via the `register()` entry point in
    `__init__.py`. At audit time, the framework calls `register_controls()`
    (which is a no-op here because controls live in TOML), then queries the
    `get_*` methods to enumerate controls and run them.
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

    def register_controls(self) -> None:
        """Register Python-defined controls (none here).

        Implementations with complex pass logic that doesn't fit the built-in
        sieve handlers can register Python control functions here via
        decorators. This minimal example has no Python controls — the single
        control is fully defined in `hello.toml`.
        """
        # No-op: this example has no Python-registered controls.
        return None

    def get_all_controls(self) -> list[Any]:
        """Return all controls. TOML-defined controls are surfaced by the
        framework via the framework config path, not by this method, so the
        list here can be empty for TOML-only plugins."""
        return []

    def get_controls_by_level(self, level: int) -> list[Any]:
        """Same convention as get_all_controls — TOML controls are loaded by
        the framework, not enumerated by the plugin's Python code."""
        return []

    def get_rules_catalog(self) -> dict[str, Any]:
        """Return the SARIF rules catalog. Empty here; the framework derives
        SARIF rules from the TOML config automatically."""
        return {}

    def get_remediation_registry(self) -> dict[str, Any]:
        """Return the remediation handler registry. Empty here; this example
        has no remediations."""
        return {}
