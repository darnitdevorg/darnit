"""MCP tool implementations for the darnit compliance audit framework.

This module provides the implementation layer for MCP tools. It includes:
- Server factory for creating MCP instances
- Tool helper functions for common operations
- Audit tool implementations

Usage:
    from darnit.tools import (
        # Server
        create_server,
        get_server,
        SERVER_NAME,
        # Helpers
        validate_and_resolve_repo,
        format_error,
        format_success,
        write_file_safely,
        # Audit
        prepare_audit,
        run_checks,
        calculate_compliance,
        summarize_results,
        list_available_checks,
    )

    # Create a server
    mcp = create_server()

    # Or use the default server
    mcp = get_server()
"""

# Server factory
# Audit tools
from .audit import (
    AuditOptions,
    calculate_compliance,
    format_results_markdown,
    list_available_checks,
    prepare_audit,
    run_checks,
    summarize_results,
)

# Tool helpers
from .helpers import (
    ensure_directory,
    format_audit_summary,
    format_error,
    format_success,
    validate_and_resolve_repo,
    write_file_safely,
)
from .server import (
    SERVER_NAME,
    SERVER_VERSION,
    create_server,
    get_server,
    register_tool,
    register_tools,
)

__all__ = [
    # Server
    "SERVER_NAME",
    "SERVER_VERSION",
    "create_server",
    "get_server",
    "register_tool",
    "register_tools",
    # Helpers
    "validate_and_resolve_repo",
    "format_error",
    "format_success",
    "format_audit_summary",
    "ensure_directory",
    "write_file_safely",
    # Audit
    "AuditOptions",
    "prepare_audit",
    "run_checks",
    "calculate_compliance",
    "summarize_results",
    "format_results_markdown",
    "list_available_checks",
]
