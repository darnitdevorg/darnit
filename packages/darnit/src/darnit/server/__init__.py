"""MCP server utilities for darnit framework.

This module provides the server infrastructure for building MCP-based
compliance audit servers with declarative TOML configuration.

Key components:
- ToolSpec: Data class for tool specifications
- ToolRegistry: Registry for auto-discovering tools from TOML
- create_server: Factory function for creating FastMCP servers
"""

from .factory import create_server, create_server_from_dict
from .registry import ToolRegistry, ToolSpec

__all__ = [
    "ToolSpec",
    "ToolRegistry",
    "create_server",
    "create_server_from_dict",
]
