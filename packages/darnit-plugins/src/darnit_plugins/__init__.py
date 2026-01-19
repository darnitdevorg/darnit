"""Darnit Plugins - Reusable adapters for darnit compliance frameworks.

This package provides check and remediation adapters that can be used
by any darnit-compatible compliance framework.

Available Check Adapters:
    - ``kusari``: Wrapper for the Kusari SBOM/SCA CLI tool
    - ``echo``: Simple echo adapter for testing and examples

Usage:
    Adapters are automatically discovered via Python entry points.
    Reference them by name in your framework TOML or user config::

        # In framework.toml or .baseline.toml
        [controls."CTRL-001"]
        check = { adapter = "kusari" }

    Or use them programmatically::

        from darnit.core import get_plugin_registry

        registry = get_plugin_registry()
        adapter = registry.get_check_adapter("kusari")

        result = adapter.check("CTRL-001", "owner", "repo", "/path", {})

Example:
    Using the echo adapter for testing::

        from darnit_plugins.adapters.echo import EchoCheckAdapter

        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", "/path", {"status": "PASS"})
        print(result.status)  # PASS

See Also:
    - :mod:`darnit.core.registry` for plugin discovery
    - :mod:`darnit.core.adapters` for adapter base classes
"""

__version__ = "0.1.0"

__all__ = [
    "__version__",
]
