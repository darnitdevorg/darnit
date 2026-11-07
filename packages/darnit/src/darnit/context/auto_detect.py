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
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from darnit.core.logging import get_logger
from darnit.core.repo_files import read_repository_text
from darnit.core.utils import resolve_case_exact_path

if TYPE_CHECKING:
    from darnit.config.context_schema import ContextDefinition

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
                    # sorted() so a repo with multiple workflow files always
                    # scans them in the same order across runs. Determinism
                    # Tier 1 (#418).
                    entries = sorted(os.listdir(full_path))
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
    candidates = (
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        "LICENCE",
        "LICENCE.md",
        "LICENCE.txt",
        "COPYING",
        "COPYING.md",
        "COPYING.txt",
        "license",
        "license.md",
        "license.txt",
        "licence",
        "licence.md",
        "licence.txt",
        "copying",
        "copying.md",
        "copying.txt",
    )
    license_path: Path | None = None
    for candidate in candidates:
        exact = resolve_case_exact_path(candidate, local_path)
        if exact and os.path.isfile(exact):
            license_path = Path(exact)
            break
    if license_path is None:
        return None

    try:
        content = read_repository_text(local_path, license_path, errors="replace")[:1000]
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


# Package-manager support (OSPS-QA-02.01 applicability)
#
# The control only applies "when the package management system supports it",
# so a project written only in a language with no package manager (shell
# scripts) has nothing to list.  The detection below is deliberately
# conservative: it concludes "unsupported" only when it positively sees shell
# scripts and nothing from any language or manifest it recognizes.  Anything
# else, including an empty repository, an unfamiliar language, or a scan that
# hit its limits, is left undetected so the control runs and can FAIL.

# Manifests whose presence means a package manager is in use.
_PACKAGE_MANIFEST_NAMES: frozenset[str] = frozenset(
    {
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "Pipfile",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Gemfile",
        "composer.json",
        "mix.exs",
        "pubspec.yaml",
        "Package.swift",
    }
)

# Source files in languages that have a package manager.
_PACKAGE_MANAGED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs",
        ".java", ".kt", ".kts", ".scala", ".rb", ".php", ".cs", ".csproj",
        ".swift", ".dart", ".ex", ".exs",
    }
)  # fmt: skip

# Source files in languages darnit does not classify; seeing one means we
# cannot say the project has no package manager.
_OTHER_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".m", ".mm", ".pl", ".pm",
        ".lua", ".jl", ".hs", ".ml", ".zig", ".nim", ".r", ".clj", ".erl",
        ".groovy", ".v", ".sol",
    }
)  # fmt: skip

# Shell scripts: the evidence that a project is script-only.
_SCRIPT_EXTENSIONS: frozenset[str] = frozenset({".sh", ".bash", ".zsh", ".bats"})

_SKIPPED_DIRS: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "vendor", "venv", ".venv",
        "__pycache__", ".tox", "site-packages", "dist", "build", "target",
    }
)  # fmt: skip

_PACKAGE_SCAN_MAX_DEPTH = 4
_PACKAGE_SCAN_MAX_ENTRIES = 5000


def detect_package_manager_support(local_path: str) -> str | None:
    """Detect whether the project is written in something a package manager covers.

    Returns:
        ``"supported"`` if a package manifest or package-managed source file is
        present; ``"unsupported"`` if the repository holds shell scripts and no
        manifest or source file in any language darnit recognizes; ``None`` if
        uncertain (no scripts, an unclassified language, or an oversized tree).
        Only ``"unsupported"`` can make a control not applicable.
    """
    root = Path(local_path)
    if not root.is_dir():
        return None

    seen_script = False
    seen_other_source = False
    entries = 0

    for current, dirnames, filenames in os.walk(root):
        depth = len(Path(current).relative_to(root).parts)
        # Sorted so the scan, and a scan that hits the limit, is deterministic.
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIPPED_DIRS and not d.startswith(".") and depth < _PACKAGE_SCAN_MAX_DEPTH
        )
        for name in sorted(filenames):
            entries += 1
            if entries > _PACKAGE_SCAN_MAX_ENTRIES:
                return None
            if name in _PACKAGE_MANIFEST_NAMES:
                return "supported"
            suffix = Path(name).suffix.lower()
            if suffix in _PACKAGE_MANAGED_EXTENSIONS:
                return "supported"
            if suffix in _OTHER_SOURCE_EXTENSIONS:
                seen_other_source = True
            elif suffix in _SCRIPT_EXTENSIONS:
                seen_script = True

    if seen_script and not seen_other_source:
        return "unsupported"
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


def collect_auto_context(
    local_path: str,
    *,
    include_stored: bool = True,
    definitions: Mapping[str, ContextDefinition] | None = None,
) -> dict[str, Any]:
    """Collect all auto-detectable context. Returns flat dict with canonical keys.

    Only includes keys where detection succeeded. Keys use the same names
    as ``when`` clause keys (e.g. ``platform``, ``ci_provider``). A
    detection of a key its definition marks as requiring judgment
    (``auto_detect = false``) is dropped: detection never concludes such a
    key (feature 042, FR-004).

    With ``include_stored`` (the default), usable values from the context
    resolver (confirmed values) take precedence over detection. Stored
    values without a confirmation are candidates and are never returned
    (feature 042, FR-006). With ``include_stored=False`` only this run's
    detections are returned (feature 040, FR-013a).

    Args:
        local_path: Repository root.
        include_stored: Overlay the resolver's usable values.
        definitions: Context definitions (default: the framework's).
    """
    if definitions is None:
        from darnit.config.context_storage import get_context_definitions

        definitions = get_context_definitions(local_path)

    context: dict[str, Any] = {}
    if include_stored:
        from darnit.config.context_resolve import resolve_context

        context.update(resolve_context(local_path, definitions, detect=False).usable())

    detected: dict[str, Any] = {}
    platform = detect_platform(local_path)
    if platform:
        detected["platform"] = platform

    ci_provider = detect_ci_provider(local_path)
    if ci_provider:
        detected["ci_provider"] = ci_provider

    primary_language = detect_primary_language(local_path)
    if primary_language:
        detected["primary_language"] = primary_language
        ecosystem = _LANGUAGE_TO_ECOSYSTEM.get(primary_language)
        if ecosystem:
            detected["detected_ecosystem"] = ecosystem

    # Absent when uncertain: a missing key leaves controls that depend on it
    # running, so only a positive "unsupported" can mark one not applicable.
    package_manager_support = detect_package_manager_support(local_path)
    if package_manager_support:
        detected["package_manager_support"] = package_manager_support

    # Always include languages (even empty list) so when clauses can evaluate
    detected["languages"] = detect_languages(local_path)

    license_type = detect_license_type(local_path)
    if license_type:
        detected["license_type"] = license_type

    for key, value in detected.items():
        definition = definitions.get(key)
        if key not in context and (definition is None or definition.auto_detect):
            context[key] = value

    if context:
        logger.debug("Auto-detected context: %s", context)

    return context


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_remote_url(remote_name: str, cwd: str) -> str | None:
    """Get the URL of a named git remote.

    Returns None both when the remote does not exist and when git could not
    be consulted at all -- but only the second case logs. Feature 036: a
    non-zero exit here is git's legitimate answer ("no such remote"), which
    is different in kind from git timing out or not being installed. Warning
    on the former would make every single-remote repo noisy; staying silent
    on the latter is what made a broken git install invisible.
    """
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
    except subprocess.TimeoutExpired:
        logger.warning(
            "context.platform: git remote lookup for %r timed out "
            "(error_class=timeout); platform detection degraded",
            remote_name,
        )
    except FileNotFoundError:
        logger.warning(
            "context.platform: git binary not found on PATH "
            "(error_class=not_found); platform detection degraded",
        )
    except (subprocess.SubprocessError, OSError) as err:
        logger.warning(
            "context.platform: git remote lookup for %r failed "
            "(error_class=network): %s: %s; platform detection degraded",
            remote_name,
            type(err).__name__,
            err,
        )
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
