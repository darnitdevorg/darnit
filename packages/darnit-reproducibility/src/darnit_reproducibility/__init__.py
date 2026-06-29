"""Scientific reproducibility plugin for darnit."""

from pathlib import Path

from .implementation import ReproducibilityImplementation


def register() -> ReproducibilityImplementation:
    """Entry point called by darnit plugin discovery."""
    impl = ReproducibilityImplementation()
    impl.register_controls()
    impl.register_sieve_handlers()
    return impl


def get_framework_path() -> Path:
    # Required by the 'darnit.frameworks' entry point: the framework registry
    # (config/merger.py) resolves framework TOMLs via this path for `darnit list`
    # and name lookup. The 'darnit.implementations' get_framework_config_path()
    # feeds the audit path instead; both entry points are required.
    return Path(__file__).parent.parent.parent / "reproducibility.toml"


__all__ = ["ReproducibilityImplementation", "register", "get_framework_path"]
