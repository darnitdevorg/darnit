"""Adapter implementations for darnit-plugins.

This module provides reusable check adapters that can be used by
any darnit-compatible compliance framework.

Available Adapters:
    - :class:`KusariCheckAdapter`: Wrapper for Kusari SBOM/SCA tool
    - :class:`EchoCheckAdapter`: Simple echo adapter for testing

These adapters are registered via entry points and can be referenced
by name in framework TOML configurations::

    [controls."CTRL-001"]
    check = { adapter = "kusari" }

See Also:
    - :mod:`darnit.core.adapters` for adapter base classes
"""

from .echo import EchoCheckAdapter
from .kusari import KusariCheckAdapter

__all__ = [
    "KusariCheckAdapter",
    "EchoCheckAdapter",
]
