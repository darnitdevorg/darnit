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


def _get_remote_url(remote_name: str, cwd: str) -> str | None:
    """Get the URL of a named git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote_name],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def _parse_github_url(url: str) -> tuple[str, str] | None:
    """Parse owner/repo from a GitHub remote URL."""
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
    if match:
        return match.group(1), match.group(2)
    return None


def detect_repo_from_git(
    local_path: str,
    *,
    prefer_upstream: bool = True,
    owner: str | None = None,
    repo: str | None = None,
) -> dict[str, str] | None:
    """Canonical repo identity detection — single source of truth.

    Resolves the repository owner, name, and metadata. This is the ONLY
    function in the codebase that should parse git remotes or call external
    tools for owner/repo detection.

    Resolution order:
    1. If both owner and repo are provided explicitly, return immediately.
    2. Check git remotes (upstream first, then origin) for owner/repo.
    3. Enrich with metadata from gh CLI if available.

    Args:
        local_path: Path to the git repository.
        prefer_upstream: If True (default), check 'upstream' remote before
            'origin'. Set to False to prefer origin (rare).
        owner: Explicit owner override. Skips detection if both owner and
            repo are provided.
        repo: Explicit repo override. Skips detection if both owner and
            repo are provided.

    Returns:
        Dict with owner, repo, url, is_private, default_branch,
        resolved_path, and source — or None if detection fails entirely.
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return None

    # Short-circuit: both explicitly provided
    if owner and repo:
        return {
            "owner": owner,
            "repo": repo,
            "url": "",
            "is_private": False,
            "default_branch": "main",
            "resolved_path": resolved_path,
            "source": "explicit",
        }

    # Detect from git remotes
    remotes = ["upstream", "origin"] if prefer_upstream else ["origin", "upstream"]
    detected_owner = None
    detected_repo = None
    source = None

    for remote in remotes:
        url = _get_remote_url(remote, resolved_path)
        if url:
            parsed = _parse_github_url(url)
            if parsed:
                detected_owner, detected_repo = parsed
                source = remote
                break

    # Apply explicit overrides for partial specification
    final_owner = owner or detected_owner
    final_repo = repo or detected_repo

    if not final_owner or not final_repo:
        return None

    if (owner and not repo) or (repo and not owner):
        source = source or "explicit"

    # Enrich with gh metadata
    metadata = _gh_enrich(final_owner, final_repo, resolved_path)

    return {
        "owner": final_owner,
        "repo": final_repo,
        "url": metadata.get("url", ""),
        "is_private": metadata.get("is_private", False),
        "default_branch": metadata.get("default_branch", "main"),
        "resolved_path": resolved_path,
        "source": source or "fallback",
    }


def _gh_enrich(owner: str, repo: str, cwd: str) -> dict[str, Any]:
    """Fetch enriched metadata from gh CLI for a specific owner/repo."""
    try:
        result = subprocess.run(
            [
                "gh", "repo", "view", f"{owner}/{repo}",
                "--json", "url,isPrivate,defaultBranchRef",
            ],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        return {
            "url": data.get("url", ""),
            "is_private": data.get("isPrivate", False),
            "default_branch": data.get("defaultBranchRef", {}).get("name", "main"),
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError,
            OSError, subprocess.SubprocessError) as e:
        logger.debug(f"gh enrichment failed for {owner}/{repo}: {type(e).__name__}: {e}")
        return {}


def detect_owner_repo(
    local_path: str,
    *,
    prefer_upstream: bool = True,
    owner: str | None = None,
    repo: str | None = None,
) -> tuple[str, str]:
    """Convenience wrapper returning (owner, repo) tuple.

    Delegates to detect_repo_from_git() and extracts the owner/repo.
    Returns ("", directory_name) if detection fails.
    """
    info = detect_repo_from_git(
        local_path,
        prefer_upstream=prefer_upstream,
        owner=owner,
        repo=repo,
    )
    if info:
        return info["owner"], info["repo"]
    path_name = os.path.basename(os.path.abspath(local_path))
    return "", path_name


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
