"""Tool registry for MCP server configuration.

This module provides data classes for representing MCP tools and a registry
that can load tool definitions from TOML configuration files.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    """Specification for an MCP tool.

    Attributes:
        name: The tool name as it will appear in MCP
        handler: Import path in format "module.path:function_name"
        description: Human-readable description of what the tool does
        parameters: Optional parameter overrides or metadata
    """

    name: str
    handler: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolRegistry:
    """Registry of discovered MCP tools.

    The registry can be populated from TOML configuration files and provides
    methods for loading tool handlers dynamically.
    """

    tools: dict[str, ToolSpec] = field(default_factory=dict)

    @classmethod
    def from_toml(cls, config: dict[str, Any]) -> ToolRegistry:
        """Load tools from a parsed TOML config dict.

        Expects config to have an [mcp.tools] section where each key
        is a tool name and the value contains handler and description.

        Example TOML:
            [mcp]
            name = "my-server"

            [mcp.tools.my_tool]
            handler = "mypackage.tools:my_function"
            description = "Does something useful"

        Args:
            config: Parsed TOML configuration dictionary

        Returns:
            ToolRegistry populated with discovered tools
        """
        registry = cls()
        mcp_config = config.get("mcp", {})
        tools_config = mcp_config.get("tools", {})

        for name, spec in tools_config.items():
            if not isinstance(spec, dict):
                continue

            handler = spec.get("handler")
            if not handler:
                continue

            registry.tools[name] = ToolSpec(
                name=name,
                handler=handler,
                description=spec.get("description", ""),
                parameters=spec.get("parameters", {}),
            )

        return registry

    def load_handler(self, spec: ToolSpec) -> Callable[..., Any]:
        """Dynamically import and return the handler function.

        Args:
            spec: Tool specification containing the handler import path

        Returns:
            The imported function

        Raises:
            ValueError: If handler path is invalid format
            ImportError: If module cannot be imported
            AttributeError: If function doesn't exist in module
        """
        if ":" not in spec.handler:
            raise ValueError(
                f"Invalid handler format '{spec.handler}'. "
                "Expected 'module.path:function_name'"
            )

        module_path, func_name = spec.handler.rsplit(":", 1)
        module = importlib.import_module(module_path)
        return getattr(module, func_name)

    def get_tool(self, name: str) -> ToolSpec | None:
        """Get a tool spec by name.

        Args:
            name: Tool name to look up

        Returns:
            ToolSpec if found, None otherwise
        """
        return self.tools.get(name)

    def list_tools(self) -> list[str]:
        """Get list of all registered tool names.

        Returns:
            List of tool names
        """
        return list(self.tools.keys())
