"""Common utilities for remediation functions.

Re-exports from core.utils and provides remediation-specific helpers.
"""

import json
import os
import subprocess
from typing import Any

from darnit.core.logging import get_logger

# Re-export from core utilities
from darnit.core.utils import (
    detect_repo_from_git,
    file_exists,
    gh_api,
    gh_api_safe,
    read_file,
    validate_local_path,
)

logger = get_logger("remediation.helpers")


def ensure_directory(path: str) -> str | None:
    """Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to create

    Returns:
        Error message if failed, None on success
    """
    try:
        os.makedirs(path, exist_ok=True)
        return None
    except OSError as e:
        return f"Failed to create directory {path}: {str(e)}"


def write_file_safe(path: str, content: str) -> tuple[bool, str]:
    """Safely write content to a file.

    Args:
        path: File path to write
        content: Content to write

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        with open(path, 'w') as f:
            f.write(content)
        return True, f"Successfully wrote {path}"
    except OSError as e:
        return False, f"Failed to write {path}: {str(e)}"


def check_file_exists(local_path: str, *patterns: str) -> list[str]:
    """Check which of the given file patterns exist.

    Args:
        local_path: Base path to check in
        patterns: File patterns to check

    Returns:
        List of patterns that exist
    """
    existing = []
    for pattern in patterns:
        if file_exists(local_path, pattern):
            existing.append(pattern)
    return existing


def get_repo_maintainers(owner: str, repo: str) -> list[str]:
    """Get repository maintainers/collaborators via GitHub API.

    Falls back to repo owner if collaborators endpoint is not accessible.

    Args:
        owner: Repository owner
        repo: Repository name

    Returns:
        List of GitHub usernames with admin/maintain permissions
    """
    maintainers = []

    # Try to get collaborators with admin/maintain permissions
    try:
        result = subprocess.run(
            ["gh", "api", f"/repos/{owner}/{repo}/collaborators", "--jq",
             '[.[] | select(.permissions.admin == true or .permissions.maintain == true) | .login] | unique'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            maintainers = json.loads(result.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    # Fallback: use repo owner
    if not maintainers:
        maintainers = [owner]

    return maintainers



def format_success(message: str, details: dict[str, Any], controls: list[str]) -> str:
    """Format a success message for remediation output.

    Args:
        message: Main success message
        details: Key-value pairs to display
        controls: List of OSPS control IDs addressed

    Returns:
        Formatted markdown string
    """
    lines = [f"✅ {message}", ""]

    if details:
        for key, value in details.items():
            lines.append(f"**{key}:** {value}")
        lines.append("")

    if controls:
        lines.append("**OSPS Controls Addressed:**")
        for control in controls:
            lines.append(f"- {control}")

    return "\n".join(lines)


def format_error(message: str) -> str:
    """Format an error message."""
    return f"❌ {message}"


def format_warning(message: str) -> str:
    """Format a warning message."""
    return f"⚠️ {message}"


__all__ = [
    # Re-exported from core
    "gh_api",
    "gh_api_safe",
    "file_exists",
    "read_file",
    "validate_local_path",
    "detect_repo_from_git",
    # Remediation-specific
    "ensure_directory",
    "write_file_safe",
    "check_file_exists",
    "get_repo_maintainers",
    "format_success",
    "format_error",
    "format_warning",
]
