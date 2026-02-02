"""Git helpers for attestation generation.

This module provides functions to extract git information
needed for building attestation subjects and predicates.
"""

import subprocess

from darnit.core.logging import get_logger

logger = get_logger("attestation.git")


def get_git_commit(local_path: str) -> str | None:
    """Get the current git commit SHA.

    Args:
        local_path: Path to the git repository

    Returns:
        The full commit SHA or None if not a git repository
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=local_path,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


def get_git_ref(local_path: str) -> str | None:
    """Get the current git ref (branch or tag).

    Args:
        local_path: Path to the git repository

    Returns:
        The branch name, tag name, or None if in detached HEAD
    """
    try:
        # Try to get branch name
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=local_path,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            if ref != "HEAD":  # Not in detached HEAD state
                return ref

        # Try to get tag if in detached HEAD
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=local_path,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


__all__ = [
    "get_git_commit",
    "get_git_ref",
]
