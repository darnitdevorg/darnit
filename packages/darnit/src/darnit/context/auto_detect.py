"""Auto-detection of factual project context from the filesystem.

Detects platform (github/gitlab/bitbucket), CI provider, and primary language
by inspecting git remotes and checking for manifest/config files. No API calls,
no subprocess calls other than `git remote get-url`.

These are factual, non-sensitive values safe to auto-detect without user
confirmation. They feed into `when` clause evaluation so the right checks
run in the right environments.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("context.auto_detect")


def detect_platform(local_path: str) -> str | None:
    """Detect hosting platform from git remote URL.

    Checks upstream remote first, then origin.

    Returns:
        "github", "gitlab", "bitbucket", or None if unknown.
    """
    for remote in ("upstream", "origin"):
        url = _get_remote_url(remote, local_path)
        if not url:
            continue

        hostname = _extract_hostname(url)
        if not hostname:
            continue

        if "github.com" in hostname:
            return "github"
        if "gitlab.com" in hostname or "gitlab" in hostname:
            return "gitlab"
        if "bitbucket.org" in hostname or "bitbucket" in hostname:
            return "bitbucket"

    return None


def detect_ci_provider(local_path: str) -> str | None:
    """Detect CI provider from config file presence.

    Returns:
        "github", "gitlab", "jenkins", "circleci", "azure", "travis", or None.
    """
    checks: list[tuple[str, str]] = [
        (".github/workflows", "github"),
        (".gitlab-ci.yml", "gitlab"),
        ("Jenkinsfile", "jenkins"),
        (".circleci/config.yml", "circleci"),
        (".circleci/config.yaml", "circleci"),
        ("azure-pipelines.yml", "azure"),
        ("azure-pipelines.yaml", "azure"),
        (".travis.yml", "travis"),
    ]

    for path_fragment, provider in checks:
        full_path = os.path.join(local_path, path_fragment)
        if os.path.exists(full_path):
            # For directories (e.g. .github/workflows), check it has files
            if os.path.isdir(full_path):
                try:
                    entries = os.listdir(full_path)
                    if any(
                        e.endswith((".yml", ".yaml")) for e in entries
                    ):
                        return provider
                except OSError:
                    continue
            else:
                return provider

    return None


def detect_primary_language(local_path: str) -> str | None:
    """Detect primary language from manifest files.

    Returns:
        "python", "go", "rust", "javascript", "typescript", "java", or None.
    """
    # Order matters: check more specific indicators first
    checks: list[tuple[str, str]] = [
        ("go.mod", "go"),
        ("Cargo.toml", "rust"),
        ("pyproject.toml", "python"),
        ("setup.py", "python"),
        ("setup.cfg", "python"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
        ("build.gradle.kts", "java"),
        ("package.json", "javascript"),  # May be overridden by tsconfig
    ]

    detected = None
    for filename, language in checks:
        if os.path.isfile(os.path.join(local_path, filename)):
            detected = language
            break

    # Refine: if package.json detected, check for TypeScript
    if detected == "javascript" and os.path.isfile(
        os.path.join(local_path, "tsconfig.json")
    ):
        detected = "typescript"

    return detected


def collect_auto_context(local_path: str) -> dict[str, Any]:
    """Collect all auto-detectable context. Returns flat dict with bare keys.

    Only includes keys where detection succeeded. Keys use the same names
    as ``when`` clause keys (e.g. ``platform``, ``ci_provider``).
    """
    context: dict[str, Any] = {}

    platform = detect_platform(local_path)
    if platform:
        context["platform"] = platform

    ci_provider = detect_ci_provider(local_path)
    if ci_provider:
        context["ci_provider"] = ci_provider

    primary_language = detect_primary_language(local_path)
    if primary_language:
        context["primary_language"] = primary_language

    if context:
        logger.debug("Auto-detected context: %s", context)

    return context


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


def _extract_hostname(url: str) -> str | None:
    """Extract hostname from a git remote URL (HTTPS or SSH)."""
    # HTTPS: https://github.com/owner/repo.git
    https_match = re.match(r"https?://([^/]+)", url)
    if https_match:
        return https_match.group(1).lower()

    # SSH: git@github.com:owner/repo.git
    ssh_match = re.match(r"[^@]+@([^:]+):", url)
    if ssh_match:
        return ssh_match.group(1).lower()

    return None
