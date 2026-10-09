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

from importlib.resources import files
from pathlib import Path

__version__ = "0.1.0"
__all__ = ["get_framework_path", "get_steps_framework_path", "register", "__version__"]


def get_framework_path() -> Path:
    """Get the path to the testchecks.toml framework definition.

    This function is used by the darnit framework discovery system
    via the entry point.

    Returns:
        Path to testchecks.toml
    """
    path = Path(str(files(__package__) / "testchecks.toml"))
    if not path.is_file():
        raise FileNotFoundError(f"testchecks.toml not found in the installed darnit_testchecks package at {path}")
    return path


def get_steps_framework_path() -> Path:
    """Get the path to the testchecks-steps.toml framework definition."""
    from .implementation import CustomStepsImplementation

    return CustomStepsImplementation().get_framework_config_path()


def register():
    """Entry point for the testchecks-steps implementation, which registers plugin step types."""
    from .implementation import CustomStepsImplementation

    return CustomStepsImplementation()
