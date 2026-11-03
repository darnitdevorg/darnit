"""Org repository helpers for the ``list_org_repos`` and ``audit_org`` MCP tools.

Enumerates repositories in a GitHub org, and clones one repository to a
temporary directory and runs the single-repo audit pipeline against it.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def enumerate_org_repos(
    owner: str,
    *,
    include_archived: bool = False,
    repos: list[str] | None = None,
) -> tuple[list[str], str | None]:
    """Enumerate repositories in a GitHub org via ``gh repo list``.

    Args:
        owner: GitHub org or user (e.g., "kusari-oss")
        include_archived: Include archived repositories. Default: False
        repos: Optional list of specific repo names to validate and return

    Returns:
        Tuple of (repo_names, error_message).
        If error_message is not None, enumeration failed.
    """
    if not owner:
        return [], "owner is required for org-wide audit"

    # Check gh availability
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return [], "gh CLI is not authenticated. Run 'gh auth login' first."
    except FileNotFoundError:
        return [], "gh CLI is required for org-wide audits but was not found."
    except subprocess.TimeoutExpired:
        return [], "gh CLI timed out checking auth status."

    # Enumerate repos
    try:
        result = subprocess.run(
            [
                "gh", "repo", "list", owner,
                "--json", "name,isArchived",
                "--limit", "500",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return [], f"Failed to list repos for {owner}: {result.stderr.strip()}"

        all_repos = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return [], f"Timed out listing repos for {owner}"
    except json.JSONDecodeError as e:
        return [], f"Failed to parse repo list for {owner}: {e}"

    # Filter archived repos
    if not include_archived:
        all_repos = [r for r in all_repos if not r.get("isArchived", False)]

    all_repo_names = [r["name"] for r in all_repos]

    # Apply repo name filter if specified
    if repos is not None:
        available = set(all_repo_names)
        filtered = []
        for name in repos:
            if name in available:
                filtered.append(name)
            else:
                logger.warning("Requested repo '%s' not found in org '%s'", name, owner)
        return filtered, None

    return all_repo_names, None


def clone_repo(owner: str, repo: str, target_dir: str) -> bool:
    """Clone a repo to a target directory using shallow clone.

    Args:
        owner: GitHub org or user
        repo: Repository name
        target_dir: Directory to clone into

    Returns:
        True if clone succeeded, False otherwise
    """
    try:
        result = subprocess.run(
            ["gh", "repo", "clone", f"{owner}/{repo}", target_dir, "--", "--depth", "1"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning(
                "Failed to clone %s/%s: %s", owner, repo, result.stderr.strip()
            )
            return False
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("Failed to clone %s/%s: %s", owner, repo, e)
        return False


def _audit_single_repo(
    owner: str,
    repo: str,
    level: int,
    tags: list[str] | None,
    framework_name: str | None = None,
) -> dict[str, Any]:
    """Clone and audit a single repo, returning structured results."""
    with tempfile.TemporaryDirectory(prefix=f"darnit-org-{repo}-") as tmpdir:
        clone_path = str(Path(tmpdir) / repo)

        # Clone
        if not clone_repo(owner, repo, clone_path):
            return {
                "repo": repo,
                "status": "ERROR",
                "error": f"Failed to clone {owner}/{repo}",
                "results": [],
                "summary": {},
            }

        # Detect default branch
        default_branch = _detect_default_branch(clone_path)

        # Run audit
        try:
            from darnit.config.operator.loader import resolve_operator_config
            from darnit.tools.audit import audit_report_metadata, run_sieve_audit
            from darnit.trust.decision import target_from_owner_repo

            operator_config = resolve_operator_config(clone_path)
            target = target_from_owner_repo(owner, repo)
            results, summary = run_sieve_audit(
                owner=owner,
                repo=repo,
                local_path=clone_path,
                default_branch=default_branch,
                level=level,
                tags=tags,
                stop_on_llm=True,
                framework_name=framework_name,
                operator_config=operator_config,
                target=target,
            )
            return {
                "repo": repo,
                "status": "OK",
                "error": None,
                "results": results,
                "summary": summary,
                **audit_report_metadata(operator_config, clone_path, target, framework_name),
            }
        except Exception as e:
            logger.warning("Audit failed for %s/%s: %s", owner, repo, e)
            return {
                "repo": repo,
                "status": "ERROR",
                "error": str(e),
                "results": [],
                "summary": {},
            }


def _detect_default_branch(repo_path: str) -> str:
    """Detect the default branch name from a cloned repo."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().split("/")[-1]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "main"
