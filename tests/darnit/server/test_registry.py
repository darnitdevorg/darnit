"""Tests for darnit.server.registry module."""

import pytest
from darnit.server.registry import ToolSpec, ToolRegistry


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
        spec = ToolSpec(
            name="test",
            handler="json:dumps",  # json.dumps is a real function
            description="Test",
        )
        registry = ToolRegistry()
        handler = registry.load_handler(spec)
        assert callable(handler)
        # Verify it's actually json.dumps
        assert handler([1, 2, 3]) == "[1, 2, 3]"

    def test_load_handler_invalid_format(self):
        """Test loading handler with invalid format raises ValueError."""
        spec = ToolSpec(
            name="test",
            handler="no_colon_here",
            description="Test",
        )
        registry = ToolRegistry()
        with pytest.raises(ValueError, match="Invalid handler format"):
            registry.load_handler(spec)

    def test_load_handler_module_not_found(self):
        """Test loading handler from non-existent module raises ImportError."""
        spec = ToolSpec(
            name="test",
            handler="nonexistent_module_xyz:func",
            description="Test",
        )
        registry = ToolRegistry()
        with pytest.raises(ImportError):
            registry.load_handler(spec)

    def test_load_handler_function_not_found(self):
        """Test loading non-existent function raises AttributeError."""
        spec = ToolSpec(
            name="test",
            handler="json:nonexistent_function_xyz",
            description="Test",
        )
        registry = ToolRegistry()
        with pytest.raises(AttributeError):
            registry.load_handler(spec)
