"""Org-wide audit orchestration.

Enumerates repositories in a GitHub org, clones each to a temporary
directory, runs the single-repo audit pipeline against each, and
aggregates results into a combined report.

Example:
    from darnit.tools.audit_org import run_org_audit

    report = run_org_audit("my-org", level=1)
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


def run_org_audit(
    owner: str,
    *,
    level: int = 3,
    tags: list[str] | None = None,
    repos: list[str] | None = None,
    include_archived: bool = False,
    output_format: str = "markdown",
) -> str:
    """Run audits across all repos in a GitHub org.

    Enumerates repos, clones each to a temp directory, runs the single-repo
    audit pipeline, and aggregates results into a combined report.

    Args:
        owner: GitHub org or user
        level: Maximum OSPS level to check (1, 2, or 3). Default: 3
        tags: Optional tag filters for controls
        repos: Optional list of specific repo names to audit
        include_archived: Include archived repos. Default: False
        output_format: "markdown" or "json". Default: "markdown"

    Returns:
        Aggregated audit report (markdown or JSON string)
    """
    # Enumerate repos
    repo_names, error = enumerate_org_repos(
        owner, include_archived=include_archived, repos=repos
    )
    if error:
        return f"❌ Error: {error}"

    if not repo_names:
        return f"No repositories found in org '{owner}'."

    logger.info("Auditing %d repos in org '%s'", len(repo_names), owner)

    # Audit each repo sequentially
    repo_results: list[dict[str, Any]] = []
    for repo_name in repo_names:
        logger.info("Auditing %s/%s (%d/%d)", owner, repo_name, len(repo_results) + 1, len(repo_names))
        result = _audit_single_repo(owner, repo_name, level, tags)
        repo_results.append(result)

    # Aggregate and format
    if output_format == "json":
        return format_org_results_json(owner, repo_results, level)
    else:
        return format_org_results_markdown(owner, repo_results, level)


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
            from darnit.tools.audit import run_sieve_audit

            results, summary = run_sieve_audit(
                owner=owner,
                repo=repo,
                local_path=clone_path,
                default_branch=default_branch,
                level=level,
                tags=tags,
                apply_user_config=True,
                stop_on_llm=True,
                framework_name=framework_name,
            )
            return {
                "repo": repo,
                "status": "OK",
                "error": None,
                "results": results,
                "summary": summary,
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


def aggregate_org_results(
    owner: str,
    repo_results: list[dict[str, Any]],
    level: int,
) -> dict[str, Any]:
    """Build an org-level summary from per-repo audit results.

    Args:
        owner: GitHub org/user
        repo_results: List of per-repo result dicts from _audit_single_repo
        level: Audit level

    Returns:
        Summary dict with per-repo compliance data
    """
    org_summary: dict[str, Any] = {
        "owner": owner,
        "level": level,
        "total_repos": len(repo_results),
        "compliant_repos": 0,
        "non_compliant_repos": 0,
        "error_repos": 0,
        "repos": [],
    }

    for result in repo_results:
        repo_name = result["repo"]
        summary = result.get("summary", {})

        if result["status"] == "ERROR":
            org_summary["error_repos"] += 1
            org_summary["repos"].append({
                "repo": repo_name,
                "status": "ERROR",
                "error": result.get("error", "Unknown error"),
            })
            continue

        pass_count = summary.get("PASS", 0)
        fail_count = summary.get("FAIL", 0)
        warn_count = summary.get("WARN", 0)
        total = summary.get("total", 0)

        # A repo is compliant only if all non-N/A controls pass
        na_count = summary.get("N/A", 0)
        is_compliant = fail_count == 0 and warn_count == 0 and (pass_count + na_count == total)

        if is_compliant:
            org_summary["compliant_repos"] += 1
        else:
            org_summary["non_compliant_repos"] += 1

        org_summary["repos"].append({
            "repo": repo_name,
            "status": "COMPLIANT" if is_compliant else "NON_COMPLIANT",
            "pass": pass_count,
            "fail": fail_count,
            "warn": warn_count,
            "total": total,
        })

    return org_summary


def format_org_results_markdown(
    owner: str,
    repo_results: list[dict[str, Any]],
    level: int,
) -> str:
    """Format org-wide audit results as markdown.

    Args:
        owner: GitHub org/user
        repo_results: Per-repo result dicts
        level: Audit level

    Returns:
        Markdown report string
    """
    from darnit.tools.audit import calculate_compliance, format_results_markdown

    org_summary = aggregate_org_results(owner, repo_results, level)
    lines: list[str] = []

    # Header
    lines.append(f"# Org-Wide Audit Report: {owner}")
    lines.append("")
    lines.append(f"**Level:** {level} | "
                 f"**Repos:** {org_summary['total_repos']} | "
                 f"**Compliant:** {org_summary['compliant_repos']} | "
                 f"**Non-Compliant:** {org_summary['non_compliant_repos']} | "
                 f"**Errors:** {org_summary['error_repos']}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Repository | PASS | FAIL | WARN | Status |")
    lines.append("|---|---|---|---|---|")

    for repo_info in org_summary["repos"]:
        if repo_info["status"] == "ERROR":
            lines.append(
                f"| {repo_info['repo']} | - | - | - | ERROR: {repo_info.get('error', '')} |"
            )
        else:
            status_icon = "PASS" if repo_info["status"] == "COMPLIANT" else "FAIL"
            lines.append(
                f"| {repo_info['repo']} | {repo_info['pass']} | {repo_info['fail']} "
                f"| {repo_info['warn']} | {status_icon} |"
            )

    lines.append("")

    # Per-repo details
    lines.append("## Per-Repository Details")
    lines.append("")

    for result in repo_results:
        repo_name = result["repo"]
        lines.append(f"### {owner}/{repo_name}")
        lines.append("")

        if result["status"] == "ERROR":
            lines.append(f"**Error:** {result.get('error', 'Unknown error')}")
            lines.append("")
            continue

        results = result["results"]
        summary = result["summary"]

        if results:
            compliance = calculate_compliance(results, level)
            report = format_results_markdown(
                owner=owner,
                repo=repo_name,
                results=results,
                summary=summary,
                compliance=compliance,
                level=level,
            )
            lines.append(report)
        else:
            lines.append("No results available.")

        lines.append("")

    return "\n".join(lines)


def format_org_results_json(
    owner: str,
    repo_results: list[dict[str, Any]],
    level: int,
) -> str:
    """Format org-wide audit results as JSON.

    Args:
        owner: GitHub org/user
        repo_results: Per-repo result dicts
        level: Audit level

    Returns:
        JSON string
    """
    org_summary = aggregate_org_results(owner, repo_results, level)
    return json.dumps(
        {
            "org_summary": org_summary,
            "repo_results": repo_results,
        },
        indent=2,
    )


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
