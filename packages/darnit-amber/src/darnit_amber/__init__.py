"""Scientific reproducibility plugin for darnit."""

from pathlib import Path

from .implementation import AmberImplementation


def register() -> AmberImplementation:
    """Entry point called by darnit plugin discovery."""
    impl = AmberImplementation()
    impl.register_controls()
    impl.register_sieve_handlers()
    return impl


def get_framework_path() -> Path:
    # Required by the 'darnit.frameworks' entry point: the framework registry
    # (config/merger.py) resolves framework TOMLs via this path for `darnit list`
    # and name lookup. The 'darnit.implementations' get_framework_config_path()
    # feeds the audit path instead; both entry points are required. Delegating
    # here ensures both paths use the same importlib.resources resolver.
    return AmberImplementation().get_framework_config_path()


__all__ = ["AmberImplementation", "register", "get_framework_path"]
