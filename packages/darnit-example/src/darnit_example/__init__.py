"""darnit-example - Example 'Project Hygiene Standard' implementation for darnit.

This package demonstrates how to build a darnit compliance plugin using the
modern ComplianceImplementation protocol. It implements a simple "Project
Hygiene Standard" with 8 controls across 2 maturity levels.

See packages/darnit-example/README.md and docs/IMPLEMENTATION_GUIDE.md for
a walkthrough of how this package is structured.

Usage:
    # Automatic registration via entry points
    from darnit.core.discovery import discover_implementations
    implementations = discover_implementations()
    hygiene = implementations.get("example-hygiene")

    # Direct access
    from darnit_example import register
    implementation = register()

    # Framework path for declarative config system
    from darnit_example import get_framework_path
    path = get_framework_path()  # Returns Path to example-hygiene.toml
"""

__version__ = "0.1.0"

from pathlib import Path


def get_framework_path() -> Path | None:
    """Get the path to the example hygiene framework TOML file.

    Returns:
        Path: Absolute path to example-hygiene.toml, or None if not found.
    """
    from .implementation import ExampleHygieneImplementation

    return ExampleHygieneImplementation().get_framework_config_path()


def register():
    """Register the Example Hygiene implementation with darnit.

    This function is called by darnit's plugin discovery system via entry points.

    Returns:
        ExampleHygieneImplementation: The registered implementation instance.
    """
    from .implementation import ExampleHygieneImplementation

    return ExampleHygieneImplementation()
