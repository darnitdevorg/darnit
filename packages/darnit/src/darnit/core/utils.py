"""Shared utility functions for the baseline MCP server."""

import glob as glob_module
import json
import os
import re
import subprocess
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("utils")


def gh_api(endpoint: str) -> dict[str, Any]:
    """Execute a GitHub API call using the gh CLI.

    Raises:
        RuntimeError: If the API call fails or returns invalid JSON.
    """
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Unknown error"
        raise RuntimeError(f"gh api failed: {error_msg}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GitHub API returned invalid JSON for {endpoint}: {e}") from e


def gh_api_safe(endpoint: str) -> dict[str, Any] | None:
    """Execute a GitHub API call, returning None on failure."""
    try:
        return gh_api(endpoint)
    except RuntimeError as e:
        logger.debug(f"GitHub API call failed for {endpoint}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"GitHub API returned invalid JSON for {endpoint}: {e}")
        return None


def validate_local_path(
    local_path: str,
    expected_owner: str | None = None,
    expected_repo: str | None = None
) -> tuple[str, str | None]:
    """
    Validate and resolve the local_path.
    Returns (resolved_path, error_message).
    If error_message is not None, the path is invalid.

    Args:
        local_path: Path to validate
        expected_owner: If provided, used for mismatch detection
        expected_repo: If provided, used for mismatch detection
    """
    # Resolve to absolute path
    abs_path = os.path.abspath(local_path)

    # Check if path exists
    if not os.path.exists(abs_path):
        return abs_path, f"Path does not exist: {abs_path}"

    # Check if it's a directory
    if not os.path.isdir(abs_path):
        return abs_path, f"Path is not a directory: {abs_path}"

    # Check if it's a git repository
    git_dir = os.path.join(abs_path, ".git")
    if not os.path.exists(git_dir):
        # Special warning for "." since it's a common mistake with MCP servers
        if local_path == ".":
            return abs_path, (
                f"Path '{abs_path}' is not a git repository. "
                f"Note: When using MCP tools, '.' resolves to the MCP server's directory, "
                f"not your current working directory. Please provide an absolute path instead."
            )
        return abs_path, f"Path is not a git repository (no .git directory): {abs_path}"

    # If local_path is "." and we have expected owner/repo, do extra validation
    if local_path == "." and expected_owner and expected_repo:
        dir_name = os.path.basename(abs_path)
        if dir_name.lower() != expected_repo.lower():
            try:
                result = subprocess.run(
                    ["git", "-C", abs_path, "remote", "get-url", "origin"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    remote_url = result.stdout.strip()
                    match = re.search(r'[:/]([^/:]+)/([^/]+?)(?:\.git)?$', remote_url)
                    if match:
                        detected_owner, detected_repo = match.groups()
                        if detected_owner.lower() != expected_owner.lower() or detected_repo.lower() != expected_repo.lower():
                            return abs_path, (
                                f"Path mismatch detected!\n\n"
                                f"You requested audit for: {expected_owner}/{expected_repo}\n"
                                f"But local_path='.' resolved to: {abs_path}\n"
                                f"Which is actually: {detected_owner}/{detected_repo}\n\n"
                                f"When using MCP tools, '.' resolves to the MCP server's directory, "
                                f"NOT your current working directory.\n\n"
                                f"Solution: Use an absolute path:\n"
                                f"  local_path=\"/path/to/{expected_repo}\""
                            )
                else:
                    return abs_path, (
                        f"Potential path mismatch!\n\n"
                        f"You requested audit for: {expected_owner}/{expected_repo}\n"
                        f"But local_path='.' resolved to: {abs_path}\n"
                        f"Directory name '{dir_name}' doesn't match expected repo '{expected_repo}'.\n\n"
                        f"When using MCP tools, '.' resolves to the MCP server's directory, "
                        f"NOT your current working directory.\n\n"
                        f"Solution: Use an absolute path:\n"
                        f"  local_path=\"/path/to/{expected_repo}\""
                    )
            except subprocess.TimeoutExpired:
                logger.debug(f"Git command timed out checking remote for {abs_path}")
                return abs_path, (
                    f"Potential path mismatch!\n\n"
                    f"You requested audit for: {expected_owner}/{expected_repo}\n"
                    f"But local_path='.' resolved to: {abs_path}\n"
                    f"Directory name '{dir_name}' doesn't match expected repo '{expected_repo}'.\n\n"
                    f"When using MCP tools, '.' resolves to the MCP server's directory, "
                    f"NOT your current working directory.\n\n"
                    f"Solution: Use an absolute path:\n"
                    f"  local_path=\"/path/to/{expected_repo}\""
                )
            except (OSError, subprocess.SubprocessError) as e:
                logger.debug(f"Git command failed for {abs_path}: {type(e).__name__}")
                return abs_path, (
                    f"Potential path mismatch!\n\n"
                    f"You requested audit for: {expected_owner}/{expected_repo}\n"
                    f"But local_path='.' resolved to: {abs_path}\n"
                    f"Directory name '{dir_name}' doesn't match expected repo '{expected_repo}'.\n\n"
                    f"When using MCP tools, '.' resolves to the MCP server's directory, "
                    f"NOT your current working directory.\n\n"
                    f"Solution: Use an absolute path:\n"
                    f"  local_path=\"/path/to/{expected_repo}\""
                )

    return abs_path, None


def detect_repo_from_git(local_path: str) -> dict[str, str] | None:
    """Auto-detect owner and repo from git remote using gh CLI."""
    try:
        resolved_path, error = validate_local_path(local_path)
        if error:
            return None

        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner,owner,name,url,isPrivate,defaultBranchRef"],
            capture_output=True,
            text=True,
            cwd=resolved_path,
            timeout=30
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return {
            "owner": data["owner"]["login"],
            "repo": data["name"],
            "url": data.get("url", ""),
            "is_private": data.get("isPrivate", False),
            "default_branch": data.get("defaultBranchRef", {}).get("name", "main"),
            "resolved_path": resolved_path
        }
    except subprocess.TimeoutExpired:
        logger.warning(f"gh repo view timed out for {local_path}")
        return None
    except FileNotFoundError:
        logger.debug("gh CLI not found - is it installed?")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"gh repo view returned invalid JSON: {e}")
        return None
    except KeyError as e:
        logger.debug(f"Unexpected response format from gh repo view: missing {e}")
        return None
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"gh repo view failed: {type(e).__name__}: {e}")
        return None


def file_exists(local_path: str, *patterns: str) -> bool:
    """Check if any file matching the patterns exists."""
    for pattern in patterns:
        matches = glob_module.glob(os.path.join(local_path, pattern), recursive=True)
        if matches:
            return True
    return False


def file_contains(local_path: str, filename_patterns: list[str], content_pattern: str) -> bool:
    """Check if any matching file contains the content pattern."""
    for pattern in filename_patterns:
        for filepath in glob_module.glob(os.path.join(local_path, pattern), recursive=True):
            try:
                with open(filepath, encoding='utf-8', errors='ignore') as f:
                    if re.search(content_pattern, f.read(), re.IGNORECASE):
                        return True
            except OSError as e:
                logger.debug(f"Could not read {filepath}: {type(e).__name__}")
                continue
    return False


def read_file(local_path: str, filename: str) -> str | None:
    """Read a file's contents, returning None if not found."""
    filepath = os.path.join(local_path, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding='utf-8', errors='ignore') as f:
                return f.read()
        except OSError as e:
            logger.debug(f"Could not read {filepath}: {type(e).__name__}")
            return None
    return None


def make_result(control_id: str, status: str, details: str, level: int = 1) -> dict[str, Any]:
    """Create a standardized result dictionary."""
    return {"id": control_id, "status": status, "details": details, "level": level}


def get_git_commit(local_path: str) -> str | None:
    """Get the current git commit SHA."""
    try:
        result = subprocess.run(
            ["git", "-C", local_path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"git rev-parse timed out for {local_path}")
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as e:
        logger.debug(f"git rev-parse failed: {type(e).__name__}")
    return None


def get_git_ref(local_path: str) -> str | None:
    """Get the current git branch/ref."""
    try:
        result = subprocess.run(
            ["git", "-C", local_path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            if ref != "HEAD":
                return ref
        # Try to get tag
        result = subprocess.run(
            ["git", "-C", local_path, "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"git ref command timed out for {local_path}")
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as e:
        logger.debug(f"git ref command failed: {type(e).__name__}")
    return None
