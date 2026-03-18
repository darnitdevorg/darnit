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
    """Entry point for framework TOML discovery."""
    return Path(__file__).parent.parent.parent / "gittuf.toml"


__all__ = ["GittufImplementation", "register", "get_framework_path"]