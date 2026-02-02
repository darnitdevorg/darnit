"""Common helpers for MCP tool implementations.

This module provides shared utilities used across multiple MCP tools,
particularly for input validation, error formatting, and response building.
"""

import json
import os
from typing import Any

from darnit.core.logging import get_logger
from darnit.core.utils import detect_repo_from_git, validate_local_path

logger = get_logger("tools.helpers")


def validate_and_resolve_repo(
    owner: str | None,
    repo: str | None,
    local_path: str
) -> tuple[str | None, str | None, str, str | None]:
    """Validate inputs and resolve owner/repo from git if needed.

    Args:
        owner: GitHub org/user (optional, auto-detected if not provided)
        repo: Repository name (optional, auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Tuple of (owner, repo, resolved_path, error_message)
        If error_message is not None, validation failed.
    """
    # Validate local path
    resolved_path, error = validate_local_path(local_path, owner, repo)
    if error:
        return None, None, resolved_path, error

    # Auto-detect owner/repo if not provided
    if not owner or not repo:
        detected = detect_repo_from_git(resolved_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            return None, None, resolved_path, (
                "Could not auto-detect owner/repo. "
                "Please provide owner and repo parameters."
            )

    return owner, repo, resolved_path, None


def format_error(message: str, details: dict[str, Any] | None = None) -> str:
    """Format an error response as JSON.

    Args:
        message: Error message
        details: Optional additional details

    Returns:
        JSON-formatted error string
    """
    response = {"error": message}
    if details:
        response.update(details)
    return json.dumps(response, indent=2)


def format_success(message: str, data: dict[str, Any] | None = None) -> str:
    """Format a success response as JSON.

    Args:
        message: Success message
        data: Optional additional data

    Returns:
        JSON-formatted success string
    """
    response = {"success": True, "message": message}
    if data:
        response.update(data)
    return json.dumps(response, indent=2)


def format_audit_summary(
    owner: str,
    repo: str,
    level: int,
    results: list[dict[str, Any]],
    compliance: dict[int, bool]
) -> str:
    """Format audit results as a summary string.

    Args:
        owner: Repository owner
        repo: Repository name
        level: Maximum level checked
        results: List of check results
        compliance: Dict mapping level to compliance status

    Returns:
        Formatted summary string
    """
    # Count by status
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 0}
    for r in results:
        status = r.get("status", "ERROR")
        counts[status] = counts.get(status, 0) + 1

    # Build summary
    lines = [
        f"# OpenSSF Baseline Audit: {owner}/{repo}",
        "",
        "## Summary",
        f"- Total controls checked: {len(results)}",
        f"- Passed: {counts['PASS']}",
        f"- Failed: {counts['FAIL']}",
        f"- Warnings: {counts['WARN']}",
        f"- Not Applicable: {counts['N/A']}",
        f"- Errors: {counts['ERROR']}",
        "",
        "## Level Compliance",
    ]

    for lvl in range(1, level + 1):
        status = "✅ Compliant" if compliance.get(lvl, False) else "❌ Not Compliant"
        lines.append(f"- Level {lvl}: {status}")

    return "\n".join(lines)


def ensure_directory(path: str) -> bool:
    """Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to ensure exists

    Returns:
        True if directory exists or was created, False on error
    """
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def write_file_safely(
    filepath: str,
    content: str,
    overwrite: bool = False
) -> tuple[bool, str]:
    """Write content to a file with safety checks.

    Args:
        filepath: Path to write to
        content: Content to write
        overwrite: Whether to overwrite existing files

    Returns:
        Tuple of (success, message)
    """
    # Check if file exists
    if os.path.exists(filepath) and not overwrite:
        return False, f"File already exists: {filepath}"

    # Ensure directory exists
    dir_path = os.path.dirname(filepath)
    if dir_path and not ensure_directory(dir_path):
        return False, f"Could not create directory: {dir_path}"

    # Write file
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, f"Successfully wrote: {filepath}"
    except OSError as e:
        return False, f"Failed to write {filepath}: {e}"


__all__ = [
    "validate_and_resolve_repo",
    "format_error",
    "format_success",
    "format_audit_summary",
    "ensure_directory",
    "write_file_safely",
]
