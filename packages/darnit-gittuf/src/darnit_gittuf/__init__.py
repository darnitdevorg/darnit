"""Gittuf plugin for darnit."""

from pathlib import Path

from .implementation import GittufImplementation


def register() -> GittufImplementation:
    """Entry point called by darnit plugin discovery."""
    impl = GittufImplementation()
    impl.register_controls()
    impl.register_sieve_handlers()
    return impl


def get_framework_path() -> Path:
    """Entry point for framework TOML discovery.

    Delegates to ``GittufImplementation.get_framework_config_path()`` so both
    the ``darnit.frameworks`` and ``darnit.implementations`` entry points
    resolve the TOML via ``importlib.resources`` (works under wheel installs,
    not just editable checkouts).
    """
    return GittufImplementation().get_framework_config_path()


__all__ = ["GittufImplementation", "register", "get_framework_path"]
