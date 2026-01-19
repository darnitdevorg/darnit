"""Test Checks Framework for darnit.

A simple framework with trivial checks for testing the declarative
configuration system.

This package demonstrates how to create a custom compliance framework
using the darnit declarative configuration system.

Example usage:
    ```python
    from darnit.config.merger import load_framework_config
    from pathlib import Path

    # Load the test framework
    framework = load_framework_config(get_framework_path())
    print(f"Loaded {len(framework.controls)} controls")
    ```
"""

from pathlib import Path

__version__ = "0.1.0"
__all__ = ["get_framework_path", "__version__"]


def get_framework_path() -> Path:
    """Get the path to the testchecks.toml framework definition.

    This function is used by the darnit framework discovery system
    via the entry point.

    Returns:
        Path to testchecks.toml
    """
    # Framework TOML is in the package root (parent of src/)
    package_dir = Path(__file__).parent
    # Go up: src/darnit_testchecks -> src -> darnit-testchecks
    framework_path = package_dir.parent.parent / "testchecks.toml"

    if not framework_path.exists():
        # Fallback: check if it's installed as a package
        # In that case, it might be in the package data
        alt_path = package_dir / "testchecks.toml"
        if alt_path.exists():
            return alt_path

    return framework_path
