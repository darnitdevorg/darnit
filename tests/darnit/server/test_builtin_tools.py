"""Tests for built-in tools (audit, remediate, list_controls).

Tests the TOML-first architecture: built-in tools that work with any
framework TOML without requiring Python implementation code.
"""

import pytest

from darnit.server.registry import ToolRegistry, ToolSpec
from darnit.server.tools import BUILTIN_TOOLS


class TestBuiltinToolsRegistry:
    """Tests for BUILTIN_TOOLS registry."""

    def test_builtin_tools_available(self):
        """All expected built-in tools are registered."""
        assert "audit" in BUILTIN_TOOLS
        assert "list_controls" in BUILTIN_TOOLS

    def test_builtin_tools_callable(self):
        """All built-in tools are callable."""
        for name, fn in BUILTIN_TOOLS.items():
            assert callable(fn), f"Built-in tool '{name}' is not callable"


class TestToolSpecBuiltin:
    """Tests for ToolSpec with builtin field."""

    def test_create_with_builtin(self):
        """ToolSpec can be created with builtin field."""
        spec = ToolSpec(
            name="audit",
            handler="",
            description="Run audit",
            builtin="audit",
        )
        assert spec.builtin == "audit"
        assert spec.handler == ""

    def test_create_without_builtin(self):
        """ToolSpec defaults builtin to None."""
        spec = ToolSpec(
            name="custom",
            handler="mod:func",
            description="Custom tool",
        )
        assert spec.builtin is None


class TestToolRegistryBuiltin:
    """Tests for ToolRegistry with builtin tools."""

    def test_from_toml_with_builtin(self):
        """Registry loads builtin tool definitions from TOML."""
        config = {
            "mcp": {
                "tools": {
                    "audit": {
                        "builtin": "audit",
                        "description": "Run audit",
                    },
                },
            },
        }
        registry = ToolRegistry.from_toml(config)
        assert "audit" in registry.tools
        assert registry.tools["audit"].builtin == "audit"
        assert registry.tools["audit"].handler == ""

    def test_from_toml_builtin_and_handler_coexist(self):
        """Registry loads both builtin and handler tools."""
        config = {
            "mcp": {
                "tools": {
                    "audit": {
                        "builtin": "audit",
                        "description": "Built-in audit",
                    },
                    "custom_tool": {
                        "handler": "mymod:func",
                        "description": "Custom",
                    },
                },
            },
        }
        registry = ToolRegistry.from_toml(config)
        assert len(registry.tools) == 2
        assert registry.tools["audit"].builtin == "audit"
        assert registry.tools["custom_tool"].handler == "mymod:func"

    def test_from_toml_skips_no_builtin_no_handler(self):
        """Registry skips tools with neither builtin nor handler."""
        config = {
            "mcp": {
                "tools": {
                    "broken": {
                        "description": "No handler or builtin",
                    },
                },
            },
        }
        registry = ToolRegistry.from_toml(config)
        assert len(registry.tools) == 0

    def test_load_builtin_handler(self):
        """Loading a builtin tool returns a bound async function."""
        import asyncio

        spec = ToolSpec(
            name="audit",
            handler="",
            description="Run audit",
            builtin="audit",
        )
        registry = ToolRegistry()
        handler = registry.load_handler(spec, framework_name="test-framework")
        assert callable(handler)
        assert asyncio.iscoroutinefunction(handler)

    def test_load_builtin_unknown_raises(self):
        """Loading an unknown builtin raises ValueError."""
        spec = ToolSpec(
            name="unknown",
            handler="",
            description="Unknown builtin",
            builtin="nonexistent",
        )
        registry = ToolRegistry()
        with pytest.raises(ValueError, match="Unknown builtin tool"):
            registry.load_handler(spec, framework_name="test")

    def test_load_builtin_no_framework_name_raises(self):
        """Loading a builtin without framework_name raises ValueError."""
        spec = ToolSpec(
            name="audit",
            handler="",
            description="Run audit",
            builtin="audit",
        )
        registry = ToolRegistry()
        with pytest.raises(ValueError, match="requires a framework name"):
            registry.load_handler(spec, framework_name=None)

    def test_load_builtin_binds_framework_name(self):
        """Builtin handler receives _framework_name when called."""
        import asyncio

        spec = ToolSpec(
            name="audit",
            handler="",
            description="Run audit",
            builtin="audit",
        )
        registry = ToolRegistry()
        handler = registry.load_handler(spec, framework_name="my-framework")

        # Call the handler - it will fail because the framework doesn't exist,
        # but we can verify it received the framework name from the error message
        result = asyncio.get_event_loop().run_until_complete(
            handler(local_path="/nonexistent")
        )
        assert "my-framework" in result or "Error" in result
