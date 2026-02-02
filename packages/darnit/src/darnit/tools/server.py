"""MCP server factory for darnit compliance framework.

This module provides the MCP server instance and registration functions
for organizing tool implementations across multiple modules.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

# Server name and version
SERVER_NAME = "Darnit Compliance Framework"
SERVER_VERSION = "0.1.0"


def create_server(name: str = SERVER_NAME) -> FastMCP:
    """Create a new MCP server instance.

    Args:
        name: Server name (default: Darnit Compliance Framework)

    Returns:
        Configured FastMCP server instance
    """
    return FastMCP(name)


# Default server instance for module-level registration
_default_server: FastMCP | None = None


def get_server() -> FastMCP:
    """Get or create the default server instance.

    Returns:
        The default FastMCP server instance
    """
    global _default_server
    if _default_server is None:
        _default_server = create_server()
    return _default_server


def register_tool(server: FastMCP, func: Callable) -> Callable:
    """Register a function as an MCP tool.

    This is a convenience wrapper around server.tool() decorator.

    Args:
        server: The MCP server instance
        func: The function to register as a tool

    Returns:
        The decorated function
    """
    return server.tool()(func)


def register_tools(server: FastMCP, tools: list[Callable]) -> None:
    """Register multiple functions as MCP tools.

    Args:
        server: The MCP server instance
        tools: List of functions to register
    """
    for tool in tools:
        register_tool(server, tool)


__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "create_server",
    "get_server",
    "register_tool",
    "register_tools",
]
