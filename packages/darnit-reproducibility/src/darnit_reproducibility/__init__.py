"""Transitional: ``darnit_reproducibility`` is now ``darnit_amber`` (#532). Removed after one release."""

import warnings

from darnit_amber import AmberImplementation, get_framework_path, register

warnings.warn(
    "darnit_reproducibility is now darnit_amber; uninstall darnit-reproducibility and import darnit_amber",
    DeprecationWarning,
    stacklevel=2,
)

ReproducibilityImplementation = AmberImplementation

__all__ = ["AmberImplementation", "ReproducibilityImplementation", "register", "get_framework_path"]
