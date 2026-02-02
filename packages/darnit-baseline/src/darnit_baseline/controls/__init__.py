"""OSPS control implementations for the sieve verification pipeline.

This module imports all control definitions which register themselves
with the global control registry in darnit.sieve.registry.

To get controls, use the registry:
    from darnit.sieve.registry import get_control_registry
    registry = get_control_registry()
    level1_controls = registry.get_specs_by_level(1)
"""

# Import control modules to trigger registration with global registry
from darnit.sieve.registry import get_control_registry

from . import (
    level1,  # noqa: F401
    level2,  # noqa: F401
    level3,  # noqa: F401
)


def get_level1_controls():
    """Get all Level 1 control specifications."""
    return get_control_registry().get_specs_by_level(1)


def get_level2_controls():
    """Get all Level 2 control specifications."""
    return get_control_registry().get_specs_by_level(2)


def get_level3_controls():
    """Get all Level 3 control specifications."""
    return get_control_registry().get_specs_by_level(3)


def get_all_controls():
    """Get all control specifications."""
    return get_control_registry().get_all_specs()


__all__ = [
    "get_level1_controls",
    "get_level2_controls",
    "get_level3_controls",
    "get_all_controls",
]
