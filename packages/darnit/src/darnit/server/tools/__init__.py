"""MCP tool implementations for the darnit server.

This module provides tool implementations that can be registered with an MCP server.
Each tool is implemented as a standalone function that can be decorated with @mcp.tool().
"""

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

__all__ = [
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
