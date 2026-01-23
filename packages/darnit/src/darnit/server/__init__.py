"""MCP server utilities for darnit framework.

This module provides the server infrastructure for building MCP-based
compliance audit servers with declarative TOML configuration.

Key components:
- ToolSpec: Data class for tool specifications
- ToolRegistry: Registry for auto-discovering tools from TOML
- create_server: Factory function for creating FastMCP servers
- Tool implementations (_impl functions) for MCP tools
"""

from .registry import ToolSpec, ToolRegistry
from .factory import create_server, create_server_from_dict

# Re-export tool implementations for backward compatibility
from .tools import (
    create_remediation_branch_impl,
    commit_remediation_changes_impl,
    create_remediation_pr_impl,
    get_remediation_status_impl,
    create_test_repository_impl,
    confirm_project_context_impl,
)

__all__ = [
    # Registry and factory
    "ToolSpec",
    "ToolRegistry",
    "create_server",
    "create_server_from_dict",
    # Tool implementations (backward compatibility)
    "create_remediation_branch_impl",
    "commit_remediation_changes_impl",
    "create_remediation_pr_impl",
    "get_remediation_status_impl",
    "create_test_repository_impl",
    "confirm_project_context_impl",
]
