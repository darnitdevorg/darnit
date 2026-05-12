"""darnit-hello — minimal worked example of a darnit compliance plugin.

This package exists as a copy-paste starter for third parties building their
own darnit implementations. It demonstrates the smallest possible plugin
that the darnit framework will discover, audit, and report against.

For the full guide, see `docs/packaging-plugins.md` in the darnit repo.
"""

from pathlib import Path

from .implementation import HelloImplementation


def register() -> HelloImplementation:
    """Entry point called by darnit plugin discovery.

    Wired up in pyproject.toml via:

        [project.entry-points."darnit.implementations"]
        hello = "darnit_hello:register"

    Return an INSTANCE (not the class) of your ComplianceImplementation.
    """
    return HelloImplementation()


def get_framework_path() -> Path:
    """Entry point for framework TOML config discovery.

    Wired up in pyproject.toml via:

        [project.entry-points."darnit.frameworks"]
        hello = "darnit_hello:get_framework_path"

    Returns the absolute path to the bundled `hello.toml`. The framework
    uses this so tools can locate the TOML config without importing this
    package directly.
    """
    return Path(__file__).parent / "hello.toml"


__all__ = ["HelloImplementation", "register", "get_framework_path"]
