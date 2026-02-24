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
from pathlib import Path
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
    """Detect primary language from manifest files at the repo root.

    Only checks the root directory — nested manifests (e.g. in monorepo
    service directories) are not scanned.  Check order favours more specific
    indicators (go.mod, Cargo.toml) over common ones (package.json).

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


# Shared manifest-to-language mapping used by both detection functions
_MANIFEST_CHECKS: list[tuple[str, str]] = [
    ("go.mod", "go"),
    ("Cargo.toml", "rust"),
    ("pyproject.toml", "python"),
    ("setup.py", "python"),
    ("setup.cfg", "python"),
    ("pom.xml", "java"),
    ("build.gradle", "java"),
    ("build.gradle.kts", "java"),
    ("package.json", "javascript"),  # May be refined to typescript
]


def detect_languages(local_path: str) -> list[str]:
    """Detect all programming languages present in the repository.

    Unlike ``detect_primary_language()`` which stops at the first match,
    this scans all manifest files and returns every detected language.
    Deduplicates results (e.g., pyproject.toml and setup.py both → "python").

    Returns:
        List of language strings, e.g. ``["go", "typescript"]``. Empty if none found.
    """
    seen: set[str] = set()
    languages: list[str] = []

    for filename, language in _MANIFEST_CHECKS:
        if os.path.isfile(os.path.join(local_path, filename)):
            # TypeScript refinement
            if language == "javascript" and os.path.isfile(
                os.path.join(local_path, "tsconfig.json")
            ):
                language = "typescript"

            if language not in seen:
                seen.add(language)
                languages.append(language)

    return languages


def detect_license_type(local_path: str) -> str | None:
    """Detect license type from LICENSE file content.

    Reads the first 1000 characters of the LICENSE file and pattern-matches
    against known license headers.

    Returns:
        "apache-2.0", "mit", "bsd-3-clause", "gpl", "isc", "mpl-2.0",
        "lgpl", "unlicense", or None if unknown.
    """
    license_path = Path(local_path) / "LICENSE"
    if not license_path.is_file():
        # Also check LICENSE.md, LICENSE.txt
        for alt in ("LICENSE.md", "LICENSE.txt"):
            alt_path = Path(local_path) / alt
            if alt_path.is_file():
                license_path = alt_path
                break
        else:
            return None

    try:
        content = license_path.read_text(encoding="utf-8", errors="replace")[:1000]
    except OSError:
        return None

    content_lower = content.lower()
    if "apache license" in content_lower:
        return "apache-2.0"
    if "mit license" in content_lower or "permission is hereby granted, free of charge" in content_lower:
        return "mit"
    if "bsd 3-clause" in content_lower or "bsd-3-clause" in content_lower:
        return "bsd-3-clause"
    if "isc license" in content_lower:
        return "isc"
    if "mozilla public license" in content_lower:
        return "mpl-2.0"
    if "gnu lesser general public license" in content_lower:
        return "lgpl"
    if "gnu general public license" in content_lower:
        return "gpl"
    if "the unlicense" in content_lower or "this is free and unencumbered software" in content_lower:
        return "unlicense"

    return None


# Map primary_language to ecosystem names used in TOML when clauses
_LANGUAGE_TO_ECOSYSTEM: dict[str, str] = {
    "python": "python",
    "javascript": "node",
    "typescript": "node",
    "go": "go",
    "rust": "rust",
    "java": "java",
    "ruby": "ruby",
}


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
        # Derive ecosystem from primary language
        ecosystem = _LANGUAGE_TO_ECOSYSTEM.get(primary_language)
        if ecosystem:
            context["detected_ecosystem"] = ecosystem

    languages = detect_languages(local_path)
    # Always include languages (even empty list) so when clauses can evaluate
    context["languages"] = languages

    license_type = detect_license_type(local_path)
    if license_type:
        context["license_type"] = license_type

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
