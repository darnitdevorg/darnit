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
from typing import TYPE_CHECKING, Any

from darnit.core.logging import get_logger

if TYPE_CHECKING:
    from darnit.config.context_schema import ContextValue

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


def detect_governance_model(local_path: str) -> str | None:
    """Heuristic: infer governance model from file patterns.

    Returns:
        "maintainer-council", "bdfl", "community", or None.
    """
    p = Path(local_path)
    has_governance = any(
        (p / name).is_file()
        for name in ("GOVERNANCE.md", "governance.md", ".github/GOVERNANCE.md")
    )
    has_codeowners = any(
        (p / name).is_file()
        for name in ("CODEOWNERS", ".github/CODEOWNERS")
    )
    has_contributing = any(
        (p / name).is_file()
        for name in ("CONTRIBUTING.md", "contributing.md", ".github/CONTRIBUTING.md")
    )

    if has_governance:
        return "maintainer-council"
    if has_codeowners and has_contributing:
        return "maintainer-council"
    if has_codeowners:
        return "bdfl"
    return None


def detect_project_type(local_path: str) -> str | None:
    """Heuristic: infer project type from file patterns.

    Returns:
        "library", "application", "framework", "cli", or None.
    """
    p = Path(local_path)

    # CLI indicators
    cli_indicators = ["setup.cfg", "pyproject.toml", "Cargo.toml"]
    for name in cli_indicators:
        f = p / name
        if f.is_file():
            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:2000]
                if "[project.scripts]" in content or "[[bin]]" in content:
                    return "cli"
            except OSError:
                pass

    # Library indicators (has package manifest but no main entry)
    manifest_names = [
        "setup.py", "pyproject.toml", "package.json", "Cargo.toml",
        "go.mod", "Gemfile", "pom.xml",
    ]
    has_manifest = any((p / name).is_file() for name in manifest_names)

    # Application indicators
    app_indicators = [
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "Procfile", "app.py", "main.py", "server.py",
    ]
    has_app = any((p / name).is_file() for name in app_indicators)

    if has_app:
        return "application"
    if has_manifest:
        return "library"
    return None


def detect_has_subprojects(local_path: str) -> bool | None:
    """Heuristic: detect monorepo/subproject structure.

    Returns:
        True if subprojects detected, False if single project, None if uncertain.
    """
    p = Path(local_path)

    # Common monorepo patterns
    monorepo_indicators = [
        "lerna.json", "pnpm-workspace.yaml", "rush.json",
    ]
    if any((p / name).is_file() for name in monorepo_indicators):
        return True

    # Check for packages/ or apps/ directories with multiple children
    for dirname in ("packages", "apps", "services", "modules", "crates"):
        d = p / dirname
        if d.is_dir():
            try:
                children = [
                    c for c in d.iterdir()
                    if c.is_dir() and not c.name.startswith(".")
                ]
                if len(children) >= 2:
                    return True
            except OSError:
                pass

    return False


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


def collect_auto_context_with_confidence(
    local_path: str,
    auto_accept_threshold: float = 0.8,
) -> dict[str, ContextValue]:
    """Collect auto-detectable context with confidence scoring.

    Returns ContextValue objects with confidence levels and auto_accepted flags.
    Canonical-source detections (file-based, deterministic) get high confidence (0.9+).
    Heuristic inferences get lower confidence (0.5-0.7).

    Args:
        local_path: Path to the repository root.
        auto_accept_threshold: Confidence threshold for auto-acceptance.

    Returns:
        Dict of context key -> ContextValue with confidence metadata.
    """
    from darnit.config.context_schema import ContextValue

    context: dict[str, ContextValue] = {}

    # Platform detection — canonical (from git remote URL)
    platform = detect_platform(local_path)
    if platform:
        context["platform"] = ContextValue.auto_detected(
            value=platform,
            method="git_remote_url",
            confidence=0.95,
            auto_accept_threshold=auto_accept_threshold,
        )

    # CI provider — canonical (config file presence)
    ci_provider = detect_ci_provider(local_path)
    if ci_provider:
        context["ci_provider"] = ContextValue.auto_detected(
            value=ci_provider,
            method="ci_config_file",
            confidence=0.95,
            auto_accept_threshold=auto_accept_threshold,
        )

    # Primary language — canonical (manifest file presence)
    primary_language = detect_primary_language(local_path)
    if primary_language:
        context["primary_language"] = ContextValue.auto_detected(
            value=primary_language,
            method="manifest_file",
            confidence=0.9,
            auto_accept_threshold=auto_accept_threshold,
        )
        # Derived ecosystem — heuristic (inferred from language)
        ecosystem = _LANGUAGE_TO_ECOSYSTEM.get(primary_language)
        if ecosystem:
            context["detected_ecosystem"] = ContextValue.auto_detected(
                value=ecosystem,
                method="language_to_ecosystem_mapping",
                confidence=0.85,
                auto_accept_threshold=auto_accept_threshold,
            )

    # Languages — canonical (manifest file presence)
    languages = detect_languages(local_path)
    context["languages"] = ContextValue.auto_detected(
        value=languages,
        method="manifest_files",
        confidence=0.9 if languages else 0.5,
        auto_accept_threshold=auto_accept_threshold,
    )

    # License type — canonical (LICENSE file content)
    license_type = detect_license_type(local_path)
    if license_type:
        context["license_type"] = ContextValue.auto_detected(
            value=license_type,
            method="license_file_content",
            confidence=0.9,
            auto_accept_threshold=auto_accept_threshold,
        )

    # Governance model — heuristic (inferred from file patterns)
    governance_model = detect_governance_model(local_path)
    if governance_model:
        context["governance_model"] = ContextValue.auto_detected(
            value=governance_model,
            method="file_pattern_heuristic",
            confidence=0.5,
            auto_accept_threshold=auto_accept_threshold,
        )

    # Project type — heuristic (inferred from file patterns)
    project_type = detect_project_type(local_path)
    if project_type:
        context["project_type"] = ContextValue.auto_detected(
            value=project_type,
            method="file_pattern_heuristic",
            confidence=0.6,
            auto_accept_threshold=auto_accept_threshold,
        )

    # Has subprojects — heuristic (directory structure analysis)
    has_subprojects = detect_has_subprojects(local_path)
    if has_subprojects is not None:
        context["has_subprojects"] = ContextValue.auto_detected(
            value=has_subprojects,
            method="directory_structure_heuristic",
            confidence=0.7 if has_subprojects else 0.6,
            auto_accept_threshold=auto_accept_threshold,
        )

    if context:
        logger.debug(
            "Auto-detected context with confidence: %s",
            {k: f"{v.value} ({v.confidence:.0%})" for k, v in context.items()},
        )

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
