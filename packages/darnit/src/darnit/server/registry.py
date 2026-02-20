"""Tool registry for MCP server configuration.

This module provides data classes for representing MCP tools and a registry
that can load tool definitions from TOML configuration files.

Supports three handler resolution modes:
1. builtin = "audit" — uses framework-provided generic tool
2. handler = "short_name" — looks up in handler registry
3. handler = "module.path:function_name" — imports directly
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
        handler: Import path in format "module.path:function_name" (or empty for builtins)
        description: Human-readable description of what the tool does
        parameters: Optional parameter overrides or metadata
        builtin: Built-in tool name (e.g., "audit", "remediate", "list_controls")
    """

    name: str
    handler: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    builtin: str | None = None


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
        is a tool name and the value contains handler or builtin.

        Example TOML:
            [mcp]
            name = "my-server"

            # Custom handler tool
            [mcp.tools.my_tool]
            handler = "mypackage.tools:my_function"
            description = "Does something useful"

            # Built-in tool (no Python code needed)
            [mcp.tools.audit]
            builtin = "audit"
            description = "Run compliance audit"

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

            builtin = spec.get("builtin")
            handler = spec.get("handler", "")

            # Must have either builtin or handler
            if not builtin and not handler:
                continue

            # Capture extra TOML keys as tool config (beyond reserved keys)
            reserved_keys = {"handler", "description", "builtin", "parameters"}
            extra_config = {k: v for k, v in spec.items() if k not in reserved_keys}
            # Merge explicit [parameters] sub-table with top-level extras
            parameters = spec.get("parameters", {})
            parameters.update(extra_config)

            registry.tools[name] = ToolSpec(
                name=name,
                handler=handler,
                description=spec.get("description", ""),
                parameters=parameters,
                builtin=builtin,
            )

        return registry

    def load_handler(
        self, spec: ToolSpec, framework_name: str | None = None
    ) -> Callable[..., Any]:
        """Dynamically import and return the handler function.

        Supports three formats:
        1. Built-in: builtin = "audit" - uses framework-provided generic tool
        2. Short name: "audit_openssf_baseline" - looks up in handler registry
        3. Module path: "module.path:function_name" - imports directly

        Args:
            spec: Tool specification containing the handler name or import path
            framework_name: Framework name for built-in tool binding

        Returns:
            The imported function

        Raises:
            ValueError: If handler cannot be resolved
            ImportError: If module cannot be imported
            AttributeError: If function doesn't exist in module
        """
        # Built-in tool resolution
        if spec.builtin:
            return self._load_builtin(spec, framework_name)

        # If no colon, try to resolve from handler registry
        if ":" not in spec.handler:
            from darnit.core.handlers import get_handler_registry

            registry = get_handler_registry()
            handler = registry.get_handler(spec.handler)
            if handler is not None:
                return handler

            raise ValueError(
                f"Handler '{spec.handler}' not found in registry. "
                "Either register it via register_handlers() or use "
                "full module path 'module.path:function_name'"
            )

        # Full module path format
        module_path, func_name = spec.handler.rsplit(":", 1)
        module = importlib.import_module(module_path)
        return getattr(module, func_name)

    def _load_builtin(
        self, spec: ToolSpec, framework_name: str | None
    ) -> Callable[..., Any]:
        """Load a built-in tool and bind it to a framework.

        Built-in tools receive the framework name as a bound parameter
        so they know which TOML config to load.

        Args:
            spec: Tool specification with builtin field
            framework_name: Framework name to bind

        Returns:
            Callable with framework_name pre-bound

        Raises:
            ValueError: If builtin name is not recognized
        """
        import functools

        from darnit.server.tools import BUILTIN_TOOLS

        builtin_name = spec.builtin
        if builtin_name not in BUILTIN_TOOLS:
            available = ", ".join(sorted(BUILTIN_TOOLS.keys()))
            raise ValueError(
                f"Unknown builtin tool '{builtin_name}'. "
                f"Available builtins: {available}"
            )

        base_fn = BUILTIN_TOOLS[builtin_name]

        if not framework_name:
            raise ValueError(
                f"Built-in tool '{builtin_name}' requires a framework name. "
                "Ensure [metadata] name is set in the TOML config."
            )

        # Create a wrapper that injects _framework_name
        @functools.wraps(base_fn)
        async def bound_handler(**kwargs):
            kwargs["_framework_name"] = framework_name
            return await base_fn(**kwargs)

        return bound_handler

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
