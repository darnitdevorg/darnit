"""MCP tool implementations for the darnit server.

This module provides tool implementations that can be registered with an MCP server.
Each tool is implemented as a standalone function that can be decorated with @mcp.tool().

Built-in tools (audit, list_controls) are generic implementations that
work with any TOML-defined framework. They can be referenced in TOML as:

    [mcp.tools.audit]
    builtin = "audit"
"""

from .builtin_audit import builtin_audit
from .builtin_list import builtin_list_controls
from .git_operations import (
    commit_remediation_changes_impl,
    create_remediation_branch_impl,
    create_remediation_pr_impl,
    get_remediation_status_impl,
)
from .project_context import (
    confirm_project_context_impl,
)
from .test_repository import (
    create_test_repository_impl,
)

# Registry of built-in tool implementations.
# Keys are the names used in TOML: builtin = "<key>"
BUILTIN_TOOLS = {
    "audit": builtin_audit,
    "list_controls": builtin_list_controls,
}

__all__ = [
    # Built-in tools
    "BUILTIN_TOOLS",
    "builtin_audit",
    "builtin_list_controls",
    # Git operations
    "create_remediation_branch_impl",
    "commit_remediation_changes_impl",
    "create_remediation_pr_impl",
    "get_remediation_status_impl",
    # Test repository
    "create_test_repository_impl",
    # Project context
    "confirm_project_context_impl",
]
