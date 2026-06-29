"""Repository scanner for context-aware remediation.

Scans a repository's filesystem to collect context (languages, CI tools,
directory structure, existing docs) that feeds into template rendering
via the ``${scan.*}`` substitution namespace.

All scan functions handle missing files gracefully — they return None or
empty collections, never raise on missing data.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("remediation.scanner")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DocInfo:
    """Metadata about an existing documentation file."""

    path: str
    exists: bool = False
    links: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    governance_mentions: list[str] = field(default_factory=list)


@dataclass
class DirectoryTree:
    """Structure of the repo's source code directories."""

    top_level: list[str] = field(default_factory=list)
    source_dirs: dict[str, list[str]] = field(default_factory=dict)

    @property
    def formatted(self) -> str:
        """Pre-formatted markdown components table from real paths."""
        if not self.top_level and not self.source_dirs:
            return ""

        lines = [
            "| Component | Path |",
            "|-----------|------|",
        ]

        if self.source_dirs:
            for dir_path, subdirs in sorted(self.source_dirs.items()):
                lines.append(f"| {dir_path.rstrip('/')} | `{dir_path}` |")
                for sub in sorted(subdirs):
                    full = f"{dir_path}{sub}"
                    lines.append(f"| &nbsp;&nbsp;{sub.rstrip('/')} | `{full}` |")
        else:
            for d in sorted(self.top_level):
                lines.append(f"| {d.rstrip('/')} | `{d}` |")

        return "\n".join(lines)


@dataclass
class RepoScanContext:
    """Collected context from scanning a repository."""

    languages: list[str] = field(default_factory=list)
    primary_language: str | None = None
    package_manager: str | None = None
    test_commands: dict[str, str] = field(default_factory=dict)
    lint_commands: dict[str, str] = field(default_factory=dict)
    build_commands: dict[str, str] = field(default_factory=dict)
    ci_tools: dict[str, list[str]] = field(default_factory=dict)
    dependency_update_tool: str | None = None
    directory_tree: DirectoryTree = field(default_factory=DirectoryTree)
    existing_docs: dict[str, DocInfo] = field(default_factory=dict)
    doc_links: list[str] = field(default_factory=list)
    governance_context: str | None = None
    code_of_conduct_path: str | None = None
    security_policy_path: str | None = None
    inconsistencies: list[str] = field(default_factory=list)
    github_apps: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Static Mappings
# =============================================================================

LANGUAGE_DEFAULTS: dict[str, dict[str, str]] = {
    "python": {
        "test": "pytest",
        "lint": "ruff check .",
        "build": "python -m build",
        "ecosystem": "pip",
    },
    "go": {
        "test": "go test ./...",
        "lint": "golangci-lint run",
        "build": "go build ./...",
        "ecosystem": "gomod",
    },
    "rust": {
        "test": "cargo test",
        "lint": "cargo clippy",
        "build": "cargo build --release",
        "ecosystem": "cargo",
    },
    "javascript": {
        "test": "npm test",
        "lint": "npm run lint",
        "build": "npm run build",
        "ecosystem": "npm",
    },
    "typescript": {
        "test": "npm test",
        "lint": "npm run lint",
        "build": "npm run build",
        "ecosystem": "npm",
    },
    "java": {
        "test": "mvn test",
        "lint": "mvn checkstyle:check",
        "build": "mvn package",
        "ecosystem": "maven",
    },
}

#: Map GitHub Action owner/name prefixes to friendly tool names and categories.
ACTION_TOOL_MAP: dict[str, tuple[str, str]] = {
    # SAST
    "github/codeql-action": ("CodeQL", "sast"),
    "returntocorp/semgrep-action": ("Semgrep", "sast"),
    "SonarSource/sonarcloud-github-action": ("SonarCloud", "sast"),
    "golangci/golangci-lint-action": ("golangci-lint", "sast"),
    # SCA
    "actions/dependency-review-action": ("GitHub Dependency Review", "sca"),
    "snyk/actions": ("Snyk", "sca"),
    "aquasecurity/trivy-action": ("Trivy", "sca"),
    # SBOM
    "anchore/sbom-action": ("Syft (Anchore)", "sbom"),
    "CycloneDX/gh-python-generate-sbom": ("CycloneDX", "sbom"),
    # Signing
    "sigstore/cosign-installer": ("Cosign", "signing"),
    "actions/attest-build-provenance": ("GitHub Attestation", "signing"),
    # Provenance
    "slsa-framework/slsa-github-generator": ("SLSA Provenance", "provenance"),
}

#: Map known GitHub App slugs to capabilities they provide.
#: Each entry is (display_name, list_of_capability_categories).
APP_CAPABILITY_MAP: dict[str, tuple[str, list[str]]] = {
    "kusari-inspector": ("Kusari Inspector", ["sast", "sca", "secrets", "license"]),
    "gittuf-app-beta": ("gittuf", ["signing"]),
    "snyk": ("Snyk", ["sca", "sast"]),
    "sonarcloud": ("SonarCloud", ["sast"]),
    "codecov": ("Codecov", ["coverage"]),
    "renovate": ("Renovate", ["dependency_updates"]),
    "dependabot": ("Dependabot", ["dependency_updates", "sca"]),
    "codesee-app": ("CodeSee", ["architecture"]),
    "socket-security": ("Socket", ["sca"]),
    "step-security": ("StepSecurity", ["supply_chain"]),
    "fossa": ("FOSSA", ["license", "sca"]),
    "whitesource-bolt": ("Mend", ["sca", "license"]),
}

#: Package manager detection from lockfile presence.
_LOCKFILE_TO_MANAGER: list[tuple[str, str]] = [
    ("uv.lock", "uv"),
    ("poetry.lock", "poetry"),
    ("Pipfile.lock", "pipenv"),
    ("yarn.lock", "yarn"),
    ("pnpm-lock.yaml", "pnpm"),
    ("package-lock.json", "npm"),
    ("Cargo.lock", "cargo"),
    ("go.sum", "go"),
    ("Gemfile.lock", "bundler"),
]

#: Directories to exclude from scanning.
_EXCLUDED_DIRS: set[str] = {
    ".git",
    ".github",
    ".gitlab",
    ".vscode",
    ".idea",
    ".project",
    ".specify",
    "node_modules",
    "vendor",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".eggs",
    "dist",
    "build",
    ".venv",
    "venv",
    "env",
    "specs",
}

#: Conventional source directories to descend one level into.
_SOURCE_DIRS: set[str] = {
    "src",
    "pkg",
    "cmd",
    "packages",
    "lib",
    "internal",
    "apps",
    "services",
    "modules",
}


# =============================================================================
# Scan Functions
# =============================================================================


def scan_repository(local_path: str) -> RepoScanContext:
    """Scan a repository for context-aware template rendering.

    Collects languages, CI tools, directory structure, existing docs,
    cross-references, and idiomatic commands.

    Returns a :class:`RepoScanContext` with all scan results.  Missing
    data results in ``None`` or empty fields — never raises on missing files.
    """
    ctx = RepoScanContext()

    # Each scan function is added incrementally as user stories are implemented.
    # Phase 3 (US6): _scan_package_manager
    ctx.package_manager = _scan_package_manager(local_path)

    # Phase 4 (US2): _scan_directory_structure
    ctx.directory_tree = _scan_directory_structure(local_path)

    # Phase 5 (US1): _scan_languages_and_commands
    langs, test_cmds, lint_cmds, build_cmds = _scan_languages_and_commands(local_path)
    ctx.languages = langs
    ctx.primary_language = langs[0] if langs else None
    ctx.test_commands = test_cmds
    ctx.lint_commands = lint_cmds
    ctx.build_commands = build_cmds

    # Phase 5 (US1): _scan_dependency_tool
    ctx.dependency_update_tool = _scan_dependency_tool(local_path)

    # Phase 6 (US3): _scan_ci_workflows
    ctx.ci_tools = _scan_ci_workflows(local_path)

    # Phase 7 (US4): _scan_existing_docs
    docs = _scan_existing_docs(local_path)
    ctx.existing_docs = docs

    # Aggregate doc-level fields from scanned docs
    all_links: list[str] = []
    gov_mentions: list[str] = []
    for info in docs.values():
        all_links.extend(info.links)
        gov_mentions.extend(info.governance_mentions)
    ctx.doc_links = list(dict.fromkeys(all_links))  # dedupe, preserve order
    ctx.governance_context = gov_mentions[0] if gov_mentions else None

    # Check for well-known community files
    for name in ("CODE_OF_CONDUCT.md", "CODE_OF_CONDUCT"):
        if os.path.isfile(os.path.join(local_path, name)):
            ctx.code_of_conduct_path = name
            break
    for name in ("SECURITY.md", "SECURITY"):
        if os.path.isfile(os.path.join(local_path, name)):
            ctx.security_policy_path = name
            break

    # Phase 9 (Polish): inconsistency detection
    ctx.inconsistencies = _scan_inconsistencies(local_path)

    # Phase 10: GitHub Apps detection
    try:
        from darnit.core.utils import detect_repo_from_git

        detected = detect_repo_from_git(local_path)
        owner = detected.get("owner") if detected else None
        repo_name = detected.get("repo") if detected else None
    except Exception:
        owner = repo_name = None
    ctx.github_apps = _scan_github_apps(local_path, owner=owner, repo=repo_name)

    logger.debug(
        "Repo scan complete: %d languages, %d CI tools detected",
        len(ctx.languages),
        sum(len(v) for v in ctx.ci_tools.values()),
    )
    return ctx


def _scan_package_manager(local_path: str) -> str | None:
    """Detect package manager from lockfile presence."""
    for lockfile, manager in _LOCKFILE_TO_MANAGER:
        if os.path.isfile(os.path.join(local_path, lockfile)):
            return manager
    return None


def _scan_directory_structure(local_path: str) -> DirectoryTree:
    """Scan top-level dirs + one level deep into conventional source dirs."""
    tree = DirectoryTree()

    try:
        entries = os.listdir(local_path)
    except OSError:
        return tree

    for entry in sorted(entries):
        full = os.path.join(local_path, entry)
        if not os.path.isdir(full):
            continue
        if entry.startswith(".") or entry in _EXCLUDED_DIRS:
            continue
        tree.top_level.append(f"{entry}/")

        # Descend one level into conventional source directories
        if entry in _SOURCE_DIRS:
            try:
                subdirs = [
                    f"{sub}/"
                    for sub in sorted(os.listdir(full))
                    if os.path.isdir(os.path.join(full, sub)) and not sub.startswith(".") and sub not in _EXCLUDED_DIRS
                ]
                if subdirs:
                    tree.source_dirs[f"{entry}/"] = subdirs
            except OSError:
                pass

    return tree


def _scan_languages_and_commands(
    local_path: str,
) -> tuple[list[str], dict[str, str], dict[str, str], dict[str, str]]:
    """Detect all languages and return idiomatic commands for each.

    Uses the existing ``detect_languages()`` from the core framework and
    maps each language to defaults from :data:`LANGUAGE_DEFAULTS`.

    Also refines Python commands when ``uv.lock`` is present.
    """
    try:
        from darnit.context.auto_detect import detect_languages

        languages = detect_languages(local_path)
    except Exception:
        languages = []

    test_cmds: dict[str, str] = {}
    lint_cmds: dict[str, str] = {}
    build_cmds: dict[str, str] = {}

    for lang in languages:
        defaults = LANGUAGE_DEFAULTS.get(lang)
        if not defaults:
            continue
        test_cmds[lang] = defaults["test"]
        lint_cmds[lang] = defaults["lint"]
        build_cmds[lang] = defaults["build"]

    # Refine Python commands when uv is the package manager
    if "python" in test_cmds and os.path.isfile(os.path.join(local_path, "uv.lock")):
        test_cmds["python"] = "uv run pytest"
        lint_cmds["python"] = "uv run ruff check ."
        build_cmds["python"] = "uv build"

    # Refine Python commands when poetry is the package manager
    if "python" in test_cmds and os.path.isfile(os.path.join(local_path, "poetry.lock")):
        test_cmds["python"] = "poetry run pytest"
        lint_cmds["python"] = "poetry run ruff check ."
        build_cmds["python"] = "poetry build"

    return languages, test_cmds, lint_cmds, build_cmds


def _scan_dependency_tool(local_path: str) -> str | None:
    """Detect dependency update tool from config file presence."""
    if os.path.isfile(os.path.join(local_path, ".github", "dependabot.yml")):
        return "Dependabot"
    if os.path.isfile(os.path.join(local_path, ".github", "dependabot.yaml")):
        return "Dependabot"
    if os.path.isfile(os.path.join(local_path, ".github", "renovate.json")):
        return "Renovate"
    if os.path.isfile(os.path.join(local_path, "renovate.json")):
        return "Renovate"
    if os.path.isfile(os.path.join(local_path, ".renovaterc")):
        return "Renovate"
    if os.path.isfile(os.path.join(local_path, ".renovaterc.json")):
        return "Renovate"
    return None


def _scan_ci_workflows(local_path: str) -> dict[str, list[str]]:
    """Parse GitHub Actions workflows for tool identification.

    Scans all ``.yml``/``.yaml`` files in ``.github/workflows/``, extracts
    ``uses:`` fields, and maps them via :data:`ACTION_TOOL_MAP` to
    categorized tool names.
    """
    workflows_dir = os.path.join(local_path, ".github", "workflows")
    if not os.path.isdir(workflows_dir):
        return {}

    tools: dict[str, list[str]] = {}
    uses_pattern = re.compile(r"uses:\s*([^@\s]+)")

    try:
        for filename in os.listdir(workflows_dir):
            if not filename.endswith((".yml", ".yaml")):
                continue
            filepath = os.path.join(workflows_dir, filename)
            try:
                content = Path(filepath).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for match in uses_pattern.finditer(content):
                action_ref = match.group(1)
                # Try matching against known action prefixes
                for prefix, (tool_name, category) in ACTION_TOOL_MAP.items():
                    if action_ref.startswith(prefix):
                        tools.setdefault(category, [])
                        if tool_name not in tools[category]:
                            tools[category].append(tool_name)
                        break

    except OSError:
        pass

    return tools


def _scan_github_apps(local_path: str, owner: str | None = None, repo: str | None = None) -> list[dict[str, Any]]:
    """Detect GitHub Apps installed on the org or repo.

    Tries the org-level installations endpoint first (``/orgs/{owner}/installations``),
    which returns apps with their slugs and permissions.  Falls back gracefully
    if the ``gh`` CLI is unavailable or the user lacks permission.
    """
    if not owner:
        # Try to detect owner from git remote
        try:
            from darnit.core.utils import detect_repo_from_git

            detected = detect_repo_from_git(local_path)
            if detected:
                owner = detected.get("owner")
        except Exception:
            pass

    if not owner:
        return []

    import json
    import subprocess

    apps: list[dict[str, Any]] = []

    try:
        result = subprocess.run(
            ["gh", "api", f"/orgs/{owner}/installations", "--paginate"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.debug("GitHub Apps API returned %d: %s", result.returncode, result.stderr[:200])
            return []

        data = json.loads(result.stdout)
        installations = data.get("installations", [])

        for inst in installations:
            slug = inst.get("app_slug", "")
            app_info: dict[str, Any] = {
                "slug": slug,
                "name": slug.replace("-", " ").title(),
                "capabilities": [],
            }

            # Map known apps to capabilities
            if slug in APP_CAPABILITY_MAP:
                display_name, capabilities = APP_CAPABILITY_MAP[slug]
                app_info["name"] = display_name
                app_info["capabilities"] = capabilities

            apps.append(app_info)

    except FileNotFoundError:
        logger.debug("gh CLI not found, skipping GitHub Apps detection")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.debug("GitHub Apps detection failed: %s", e)

    return apps


def _scan_existing_docs(local_path: str) -> dict[str, DocInfo]:
    """Scan well-known documentation files for links and governance context."""
    doc_files = [
        "README.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "GOVERNANCE.md",
    ]

    results: dict[str, DocInfo] = {}
    link_pattern = re.compile(r"https?://[^\s\)>\]\"']+")
    governance_patterns = [
        re.compile(r"governed\s+by\s+[\w\s,]+", re.IGNORECASE),
        re.compile(r"maintained\s+by\s+[\w\s,]+", re.IGNORECASE),
        re.compile(r"sponsored\s+by\s+[\w\s,]+", re.IGNORECASE),
        re.compile(r"under\s+the\s+stewardship\s+of\s+[\w\s,]+", re.IGNORECASE),
    ]
    # References to other doc files
    doc_ref_pattern = re.compile(
        r"\[([^\]]+)\]\(([^)]*(?:README|CONTRIBUTING|CODE_OF_CONDUCT|"
        r"SECURITY|GOVERNANCE|SUPPORT|CHANGELOG|LICENSE)[^)]*)\)",
        re.IGNORECASE,
    )

    for doc_name in doc_files:
        doc_path = os.path.join(local_path, doc_name)
        info = DocInfo(path=doc_name)

        if not os.path.isfile(doc_path):
            results[doc_name] = info
            continue

        info.exists = True
        try:
            content = Path(doc_path).read_text(encoding="utf-8", errors="replace")[
                :10000
            ]  # Cap at 10KB to avoid huge files
        except OSError:
            results[doc_name] = info
            continue

        # Extract links (only https://, skip github.com repo links for noise)
        for link_match in link_pattern.finditer(content):
            url = link_match.group(0).rstrip(".,;:")
            # Skip common noisy links
            if "github.com/kusari-oss/darnit" not in url:
                info.links.append(url)

        # Extract governance mentions
        for gov_pat in governance_patterns:
            for gov_match in gov_pat.finditer(content):
                mention = gov_match.group(0).strip()
                if mention and mention not in info.governance_mentions:
                    info.governance_mentions.append(mention)

        # Extract references to other docs
        for ref_match in doc_ref_pattern.finditer(content):
            ref_path = ref_match.group(2)
            if ref_path not in info.references:
                info.references.append(ref_path)

        results[doc_name] = info

    return results


def _extract_governance_mentions(text: str) -> list[str]:
    """Extract governance-related mentions from text.

    Looks for patterns like "governed by X", "maintained by X", etc.
    """
    patterns = [
        re.compile(r"governed\s+by\s+[\w\s,]+", re.IGNORECASE),
        re.compile(r"maintained\s+by\s+[\w\s,]+", re.IGNORECASE),
        re.compile(r"sponsored\s+by\s+[\w\s,]+", re.IGNORECASE),
        re.compile(r"under\s+the\s+stewardship\s+of\s+[\w\s,]+", re.IGNORECASE),
    ]
    mentions: list[str] = []
    for pat in patterns:
        for match in pat.finditer(text):
            mention = match.group(0).strip()
            if mention and mention not in mentions:
                mentions.append(mention)
    return mentions


def _scan_inconsistencies(local_path: str) -> list[str]:
    """Detect inconsistencies between project files.

    Checks for license mismatches between LICENSE file and manifest files.
    """
    issues: list[str] = []

    # Detect license type from LICENSE file
    try:
        from darnit.context.auto_detect import detect_license_type

        file_license = detect_license_type(local_path)
    except Exception:
        file_license = None

    if not file_license:
        return issues

    # Check pyproject.toml license field
    pyproject_path = os.path.join(local_path, "pyproject.toml")
    if os.path.isfile(pyproject_path):
        try:
            content = Path(pyproject_path).read_text(encoding="utf-8", errors="replace")
            # Simple pattern match for license field
            license_match = re.search(r'license\s*=\s*[{"]([^"}\n]+)', content, re.IGNORECASE)
            if license_match:
                manifest_license = license_match.group(1).strip().lower()
                # Normalize for comparison
                normalized_file = file_license.replace("-", "").replace(".", "")
                normalized_manifest = manifest_license.replace("-", "").replace(".", "")
                if normalized_file not in normalized_manifest and normalized_manifest not in normalized_file:
                    issues.append(
                        f"License mismatch: LICENSE file appears to be {file_license}, "
                        f"but pyproject.toml declares '{license_match.group(1).strip()}'"
                    )
        except OSError:
            pass

    return issues


# =============================================================================
# Flattening for Template Substitution
# =============================================================================


def flatten_scan_context(ctx: RepoScanContext) -> dict[str, str]:
    """Convert :class:`RepoScanContext` to a flat dict for ``${scan.*}`` substitution.

    All values are strings.  Lists are joined with commas or formatted
    as markdown.  ``None`` values are omitted — the executor's regex
    cleanup will replace unresolved ``${scan.*}`` refs with empty strings.
    """
    result: dict[str, str] = {}

    if ctx.languages:
        result["scan.languages"] = ", ".join(ctx.languages)
    if ctx.primary_language:
        result["scan.primary_language"] = ctx.primary_language
    if ctx.package_manager:
        result["scan.package_manager"] = ctx.package_manager

    # Primary language commands
    if ctx.primary_language and ctx.primary_language in ctx.test_commands:
        result["scan.test_command"] = ctx.test_commands[ctx.primary_language]
    if ctx.primary_language and ctx.primary_language in ctx.lint_commands:
        result["scan.lint_command"] = ctx.lint_commands[ctx.primary_language]

    # All language commands formatted as markdown sections
    if ctx.test_commands:
        sections = []
        for lang, cmd in ctx.test_commands.items():
            lint_cmd = ctx.lint_commands.get(lang, "")
            section = f"### {lang.title()}\n\n```bash\n# Run tests\n{cmd}\n"
            if lint_cmd:
                section += f"\n# Run linting\n{lint_cmd}\n"
            section += "```"
            sections.append(section)
        result["scan.test_commands_all"] = "\n\n".join(sections)

    # CI tools by category
    for category in ("sast", "sca", "sbom", "signing", "provenance"):
        tools = ctx.ci_tools.get(category, [])
        if tools:
            result[f"scan.ci_{category}_tools"] = ", ".join(tools)

    if ctx.dependency_update_tool:
        result["scan.dependency_tool"] = ctx.dependency_update_tool

    # Directory tree
    if ctx.directory_tree.formatted:
        result["scan.directory_tree"] = ctx.directory_tree.formatted

    # Doc links
    if ctx.doc_links:
        formatted = "\n".join(f"- {link}" for link in ctx.doc_links[:10])
        result["scan.doc_links"] = formatted

    if ctx.governance_context:
        result["scan.governance_context"] = ctx.governance_context

    if ctx.code_of_conduct_path:
        result["scan.code_of_conduct_link"] = f"[Code of Conduct]({ctx.code_of_conduct_path})"
    if ctx.security_policy_path:
        result["scan.security_policy_link"] = f"[Security Policy]({ctx.security_policy_path})"

    if ctx.inconsistencies:
        formatted = "\n".join(f"- ⚠️ {issue}" for issue in ctx.inconsistencies)
        result["scan.inconsistencies"] = formatted

    # GitHub Apps
    if ctx.github_apps:
        app_names = [app["name"] for app in ctx.github_apps]
        result["scan.github_apps"] = ", ".join(app_names)

        # Merge app capabilities into CI tools categories
        for app in ctx.github_apps:
            for cap in app.get("capabilities", []):
                key = f"scan.ci_{cap}_tools"
                existing = result.get(key, "")
                app_name = app["name"]
                if existing and app_name not in existing:
                    result[key] = f"{existing}, {app_name}"
                elif not existing:
                    result[key] = app_name

            # Emit per-app boolean flags for when-clause matching.
            # Allows TOML when = { "scan.app_kusari_inspector" = "true" }
            # without depending on exact ci_*_tools string formatting.
            slug = app.get("slug", "")
            if slug:
                result[f"scan.app_{slug.replace('-', '_')}"] = "true"

    return result
