"""Tests for darnit.server.registry module."""

import re

import pytest

from darnit.core.handlers import HandlerImportRefused
from darnit.server.registry import ToolRegistry, ToolSpec


class TestToolSpec:
    """Tests for ToolSpec dataclass."""

    def test_create_minimal(self):
        """Test creating a ToolSpec with minimal fields."""
        spec = ToolSpec(
            name="test_tool",
            handler="mymodule:my_function",
            description="A test tool",
        )
        assert spec.name == "test_tool"
        assert spec.handler == "mymodule:my_function"
        assert spec.description == "A test tool"
        assert spec.parameters == {}

    def test_create_with_parameters(self):
        """Test creating a ToolSpec with parameters."""
        spec = ToolSpec(
            name="test_tool",
            handler="mymodule:my_function",
            description="A test tool",
            parameters={"arg1": "string", "arg2": "int"},
        )
        assert spec.parameters == {"arg1": "string", "arg2": "int"}


class TestToolRegistry:
    """Tests for ToolRegistry class."""

    def test_create_empty(self):
        """Test creating an empty registry."""
        registry = ToolRegistry()
        assert registry.tools == {}
        assert registry.list_tools() == []

    def test_from_toml_empty(self):
        """Test loading from config with no tools."""
        config = {}
        registry = ToolRegistry.from_toml(config)
        assert registry.tools == {}

    def test_from_toml_no_mcp_section(self):
        """Test loading from config with no [mcp] section."""
        config = {"metadata": {"name": "test"}}
        registry = ToolRegistry.from_toml(config)
        assert registry.tools == {}

    def test_from_toml_no_tools_section(self):
        """Test loading from config with [mcp] but no [mcp.tools]."""
        config = {"mcp": {"name": "test-server"}}
        registry = ToolRegistry.from_toml(config)
        assert registry.tools == {}

    def test_from_toml_with_tools(self):
        """Test loading tools from config."""
        config = {
            "mcp": {
                "name": "test-server",
                "tools": {
                    "tool1": {
                        "handler": "mymodule:func1",
                        "description": "First tool",
                    },
                    "tool2": {
                        "handler": "mymodule:func2",
                        "description": "Second tool",
                    },
                },
            },
        }
        registry = ToolRegistry.from_toml(config)
        assert len(registry.tools) == 2
        assert "tool1" in registry.tools
        assert "tool2" in registry.tools
        assert registry.tools["tool1"].handler == "mymodule:func1"
        assert registry.tools["tool2"].description == "Second tool"

    def test_from_toml_skips_invalid(self):
        """Test that invalid tool specs are skipped."""
        config = {
            "mcp": {
                "tools": {
                    "valid": {
                        "handler": "mymodule:func",
                        "description": "Valid tool",
                    },
                    "no_handler": {
                        "description": "Missing handler",
                    },
                    "not_dict": "invalid",
                },
            },
        }
        registry = ToolRegistry.from_toml(config)
        assert len(registry.tools) == 1
        assert "valid" in registry.tools
        assert "no_handler" not in registry.tools
        assert "not_dict" not in registry.tools

    def test_from_toml_with_parameters(self):
        """Test loading tools with parameters."""
        config = {
            "mcp": {
                "tools": {
                    "tool_with_params": {
                        "handler": "mymodule:func",
                        "description": "Tool with params",
                        "parameters": {"required": ["arg1"]},
                    },
                },
            },
        }
        registry = ToolRegistry.from_toml(config)
        tool = registry.tools["tool_with_params"]
        assert tool.parameters == {"required": ["arg1"]}

    def test_get_tool_exists(self):
        """Test getting an existing tool."""
        registry = ToolRegistry()
        registry.tools["my_tool"] = ToolSpec(
            name="my_tool",
            handler="mod:func",
            description="Test",
        )
        tool = registry.get_tool("my_tool")
        assert tool is not None
        assert tool.name == "my_tool"

    def test_get_tool_not_exists(self):
        """Test getting a non-existent tool returns None."""
        registry = ToolRegistry()
        assert registry.get_tool("nonexistent") is None

    def test_list_tools(self):
        """Test listing registered tools."""
        registry = ToolRegistry()
        registry.tools["tool_a"] = ToolSpec(name="tool_a", handler="a:a", description="A")
        registry.tools["tool_b"] = ToolSpec(name="tool_b", handler="b:b", description="B")
        tools = registry.list_tools()
        assert set(tools) == {"tool_a", "tool_b"}

    def test_load_handler_success(self):
        """Test successfully loading a handler function."""
        from darnit.core.logging import get_logger

        spec = ToolSpec(
            name="test",
            handler="darnit.core.logging:get_logger",
            description="Test",
        )
        registry = ToolRegistry()
        assert registry.load_handler(spec) is get_logger

    def test_load_handler_from_installed_implementation(self):
        """The shipped community-spec tool names a module of its own package."""
        from darnit_csl.mcp_tools import remediate_community_spec

        spec = ToolSpec(
            name="remediate_community_spec",
            handler="darnit_csl.mcp_tools:remediate_community_spec",
            description="Test",
        )
        assert ToolRegistry().load_handler(spec) is remediate_community_spec

    @pytest.mark.parametrize(
        "handler",
        ["os:system", "subprocess:run", "json:dumps", "darnit_not_installed_xyz.tools:run"],
    )
    def test_load_handler_refuses_module_outside_policy(self, handler):
        """A module path outside darnit and the installed implementations is never imported."""
        spec = ToolSpec(name="test", handler=handler, description="Test")
        with pytest.raises(HandlerImportRefused, match=re.escape(handler)):
            ToolRegistry().load_handler(spec)

    def test_load_handler_invalid_format(self):
        """Test loading handler with invalid format raises ValueError."""
        spec = ToolSpec(
            name="test",
            handler="no_colon_here",
            description="Test",
        )
        registry = ToolRegistry()
        with pytest.raises(ValueError, match="not found in registry"):
            registry.load_handler(spec)

    def test_load_handler_module_not_found(self):
        """Test loading handler from non-existent module raises ImportError."""
        spec = ToolSpec(
            name="test",
            handler="darnit.nonexistent_module_xyz:func",
            description="Test",
        )
        registry = ToolRegistry()
        with pytest.raises(ImportError):
            registry.load_handler(spec)

    def test_load_handler_function_not_found(self):
        """Test loading non-existent function raises AttributeError."""
        spec = ToolSpec(
            name="test",
            handler="darnit.core.logging:nonexistent_function_xyz",
            description="Test",
        )
        registry = ToolRegistry()
        with pytest.raises(AttributeError):
            registry.load_handler(spec)


class TestBuiltinSignatureStripping:
    """The bound builtin must not expose the injected _framework_name.

    functools.wraps makes inspect.signature follow __wrapped__ back to the
    base function, which still declares _framework_name. FastMCP rejects
    tool parameters starting with '_', so registry._load_builtin strips it
    from the exposed signature.
    """

    def test_framework_name_absent_from_exposed_signature(self):
        import inspect

        from darnit.server.tools import BUILTIN_TOOLS

        assert "_framework_name" in inspect.signature(BUILTIN_TOOLS["audit"]).parameters

        registry = ToolRegistry()
        spec = ToolSpec(
            name="audit",
            handler="",
            description="Audit tool",
            builtin="audit",
        )
        bound = registry._load_builtin(spec, "openssf-baseline")

        params = inspect.signature(bound).parameters
        assert "_framework_name" not in params
        assert not any(name.startswith("_") for name in params)

    def test_other_parameters_are_preserved(self):
        import inspect

        from darnit.server.tools import BUILTIN_TOOLS

        base_params = [
            name for name in inspect.signature(BUILTIN_TOOLS["audit"]).parameters if name != "_framework_name"
        ]

        registry = ToolRegistry()
        spec = ToolSpec(name="audit", handler="", description="Audit tool", builtin="audit")
        bound = registry._load_builtin(spec, "openssf-baseline")

        assert list(inspect.signature(bound).parameters) == base_params
