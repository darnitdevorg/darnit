"""Example Framework - Full Python Implementation.

This example shows how to create a compliance framework using Python code.
This is the traditional approach before the declarative TOML system.

Compare this with the TOML-only version in ../declarative-framework/
to see the difference in complexity and code required.
"""

__version__ = "1.0.0"


def register():
    """Register the example framework with darnit.

    This function is called by darnit's plugin discovery system via entry points.

    Returns:
        ExampleFrameworkImplementation: The registered implementation instance.
    """
    from .implementation import ExampleFrameworkImplementation
    return ExampleFrameworkImplementation()
