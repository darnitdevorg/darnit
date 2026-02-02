"""darnit-baseline - OpenSSF Baseline (OSPS v2025.10.10) implementation for darnit.

This package provides the OpenSSF Baseline compliance checks as a darnit plugin.
It registers automatically via Python entry points when installed.

Usage:
    # Automatic registration via entry points
    from darnit.core.discovery import discover_implementations
    implementations = discover_implementations()
    baseline = implementations.get("openssf-baseline")

    # Direct access
    from darnit_baseline import register
    implementation = register()

    # Framework path for declarative config system
    from darnit_baseline import get_framework_path
    path = get_framework_path()  # Returns Path to openssf-baseline.toml
"""

__version__ = "0.1.0"

from pathlib import Path


def get_framework_path() -> Path | None:
    """Get the path to the OpenSSF Baseline framework TOML file.

    This delegates to the implementation's get_framework_config_path() method
    to avoid duplicate path logic.

    Returns:
        Path: Absolute path to openssf-baseline.toml, or None if not found.
    """
    from .implementation import OSPSBaselineImplementation
    return OSPSBaselineImplementation().get_framework_config_path()


def register():
    """Register the OpenSSF Baseline implementation with darnit.

    This function is called by darnit's plugin discovery system via entry points.

    Returns:
        OSPSBaselineImplementation: The registered implementation instance.
    """
    from .implementation import OSPSBaselineImplementation
    return OSPSBaselineImplementation()
