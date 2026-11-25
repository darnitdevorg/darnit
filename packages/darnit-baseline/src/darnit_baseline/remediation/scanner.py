"""Repository scanner for context-aware remediation.

Scans a repository's filesystem to collect context (languages, CI tools,
directory structure, existing docs) that feeds into template rendering
via the ``${scan.*}`` substitution namespace.

All scan functions handle missing files gracefully — they return None or
empty collections, never raise on missing data.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from darnit.core.logging import get_logger
from darnit.core.repo_files import read_repository_text

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
    maintainers_path: str | None = None
    codeowners_path: str | None = None
    contributing_path: str | None = None
    readme_path: str | None = None
    license_path: str | None = None
    docs_dir: str | None = None
    sca_workflow_path: str | None = None
    sca_workflow_on_pull_request: bool = False
    sast_workflow_path: str | None = None
    dependency_config_path: str | None = None
    #: ``.github/workflows`` when a pull-request job executes a test command.
    ci_pr_test_workflows: str | None = None
    #: ``.github/workflows`` when a test command runs, but not on pull_request.
    ci_test_workflows_without_pull_request: str | None = None
    node_coverage_command: str | None = None
    node_watch_command: str | None = None
    node_package_manager: str | None = None
    node_has_lockfile: bool = False
    inconsistencies: list[str] = field(default_factory=list)
    github_apps: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Static Mappings
# =============================================================================

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

_JS_MANAGERS = {"npm", "yarn", "pnpm", "bun"}

_MAINTAINERS_CANDIDATES = ("MAINTAINERS.md", "MAINTAINERS", "docs/MAINTAINERS.md", ".github/MAINTAINERS.md")
_CODEOWNERS_CANDIDATES = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
_CONTRIBUTING_CANDIDATES = ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md")
_README_CANDIDATES = ("README.md", "README.rst", "README.txt", "README", ".github/README.md", "docs/README.md")
_LICENSE_CANDIDATES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md")
_CODE_OF_CONDUCT_CANDIDATES = (
    "CODE_OF_CONDUCT.md",
    "CODE_OF_CONDUCT",
    ".github/CODE_OF_CONDUCT.md",
    "docs/CODE_OF_CONDUCT.md",
)
_SECURITY_CANDIDATES = ("SECURITY.md", "SECURITY", ".github/SECURITY.md", "docs/SECURITY.md")
_SCA_WORKFLOW_CANDIDATES = (".github/workflows/sca.yml", ".github/workflows/sca.yaml")
_SAST_WORKFLOW_CANDIDATES = (".github/workflows/sast.yml", ".github/workflows/sast.yaml")
_DEPENDABOT_CANDIDATES = (".github/dependabot.yml", ".github/dependabot.yaml")
_RENOVATE_CANDIDATES = (".github/renovate.json", "renovate.json", ".renovaterc", ".renovaterc.json")

_PYTEST_SECTION = re.compile(r"(?m)^\[(?:tool:)?pytest\]")
_MAKE_TEST_TARGET = re.compile(r"(?m)^test\s*:")
_RUN_STEP = re.compile(r"^(\s*)(?:-\s*)?run:\s*(.*)$")
_TEST_COMMAND_LINE = re.compile(
    r"(?im)^\s*(?:npm test|npm run test\b|pnpm(?: run)? test\b|yarn test\b|bun test\b|"
    r"pytest\b|go test\b|cargo test\b|mvn(?:w)? test\b|(?:\./)?gradlew test\b|gradle test\b|make test\b)"
)


def _normalize_repo_path(path: str) -> str:
    """Repository-relative path with forward slashes and no ``./`` prefix."""
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def _scheduled_set(scheduled_paths: Collection[str] | None) -> set[str]:
    return {_normalize_repo_path(path) for path in (scheduled_paths or ()) if path and path.strip()}


def _path_available(local_path: str, relative: str, scheduled: set[str]) -> bool:
    """True when ``relative`` exists in the tree or is scheduled for this run."""
    norm = _normalize_repo_path(relative)
    if norm in scheduled:
        return True
    return os.path.isfile(os.path.join(local_path, *norm.split("/")))


def _first_available(local_path: str, candidates: tuple[str, ...], scheduled: set[str]) -> str | None:
    for candidate in candidates:
        if _path_available(local_path, candidate, scheduled):
            return _normalize_repo_path(candidate)
    return None


def _read_text(local_path: str, relative: str) -> str | None:
    full = os.path.join(local_path, *(_normalize_repo_path(relative).split("/")))
    if not os.path.isfile(full):
        return None
    try:
        return read_repository_text(local_path, full, errors="replace")
    except OSError:
        return None


def _markdown_link(label: str, path: str) -> str:
    return f"[{label}]({path})"


def _docs_dir_available(local_path: str, scheduled: set[str]) -> str | None:
    """``docs`` when that directory exists or this run will write a file inside it."""
    if os.path.isdir(os.path.join(local_path, "docs")):
        return "docs"
    if any(path == "docs" or path.startswith("docs/") for path in scheduled):
        return "docs"
    return None


def _link_target_from(path: str, from_dir: str) -> str:
    """``path`` as a Markdown target from a document written in ``from_dir``."""
    prefix = from_dir.strip("/") + "/"
    if path.startswith(prefix):
        return path[len(prefix) :]
    return "../" + path


# =============================================================================
# Scan Functions
# =============================================================================


def scan_repository(local_path: str, scheduled_paths: Collection[str] | None = None) -> RepoScanContext:
    """Scan a repository for context-aware template rendering.

    Collects languages, CI tools, directory structure, existing docs,
    cross-references, and idiomatic commands.

    Returns a :class:`RepoScanContext` with all scan results.  Missing
    data results in ``None`` or empty fields — never raises on missing files.

    ``scheduled_paths`` are repository-relative files this remediation run
    will create. They count as present for documentation links, because a
    link to a file the same run is writing is not a broken link.
    """
    scheduled = _scheduled_set(scheduled_paths)
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

    # Phase 5 (US1): dependency update tool, including files this run will create
    ctx.dependency_update_tool, ctx.dependency_config_path = _resolve_dependency_config(local_path, scheduled)
    ctx.node_coverage_command, ctx.node_watch_command = _node_auxiliary_commands(local_path)
    ctx.node_package_manager, ctx.node_has_lockfile = _node_package_manager(local_path, ctx.package_manager)

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

    # Links are emitted only for files that exist or that this run will create.
    ctx.code_of_conduct_path = _first_available(local_path, _CODE_OF_CONDUCT_CANDIDATES, scheduled)
    ctx.security_policy_path = _first_available(local_path, _SECURITY_CANDIDATES, scheduled)
    ctx.maintainers_path = _first_available(local_path, _MAINTAINERS_CANDIDATES, scheduled)
    ctx.codeowners_path = _first_available(local_path, _CODEOWNERS_CANDIDATES, scheduled)
    ctx.contributing_path = _first_available(local_path, _CONTRIBUTING_CANDIDATES, scheduled)
    ctx.readme_path = _first_available(local_path, _README_CANDIDATES, scheduled)
    ctx.license_path = _first_available(local_path, _LICENSE_CANDIDATES, scheduled)
    ctx.docs_dir = _docs_dir_available(local_path, scheduled)
    ctx.sca_workflow_path = _first_available(local_path, _SCA_WORKFLOW_CANDIDATES, scheduled)
    ctx.sca_workflow_on_pull_request = _workflow_on_pull_request(local_path, ctx.sca_workflow_path)
    ctx.sast_workflow_path = _first_available(local_path, _SAST_WORKFLOW_CANDIDATES, scheduled)
    ctx.ci_pr_test_workflows, ctx.ci_test_workflows_without_pull_request = _ci_test_workflow_evidence(local_path)

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


def _read_package_json(local_path: str) -> dict[str, Any] | None:
    """Parse ``package.json``. Invalid or missing files yield ``None``."""
    text = _read_text(local_path, "package.json")
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _script_body(scripts: object, name: str) -> str | None:
    """Return a non-empty ``scripts.<name>`` string, if the package defines one."""
    if not isinstance(scripts, dict):
        return None
    value = scripts.get(name)
    if not isinstance(value, str):
        return None
    body = value.strip()
    return body or None


def _js_manager(package: dict[str, Any] | None, detected: str | None) -> str:
    """npm, yarn, pnpm, or bun. Lockfiles win over the ``packageManager`` field."""
    if detected in _JS_MANAGERS:
        return detected
    if package is not None:
        raw = package.get("packageManager")
        if isinstance(raw, str):
            name = raw.split("@", 1)[0].strip().lower()
            if name in _JS_MANAGERS:
                return name
    return "npm"


def _js_test_invocation(manager: str) -> str:
    if manager == "yarn":
        return "yarn test"
    if manager == "pnpm":
        return "pnpm test"
    if manager == "bun":
        return "bun test"
    return "npm test"


def _js_run_invocation(manager: str, script: str) -> str:
    if manager == "yarn":
        return f"yarn {script}"
    if manager == "pnpm":
        return f"pnpm run {script}"
    if manager == "bun":
        return f"bun run {script}"
    return f"npm run {script}"


def _node_script_commands(local_path: str) -> tuple[str | None, str | None, str | None]:
    """Test, coverage, and watch invocations backed by ``package.json`` scripts.

    Coverage and watch are returned only when those scripts exist. They are
    never invented from the presence of a ``test`` script.
    """
    package = _read_package_json(local_path)
    if package is None:
        return None, None, None
    scripts = package.get("scripts")
    manager = _js_manager(package, _scan_package_manager(local_path))
    test_command = _js_test_invocation(manager) if _script_body(scripts, "test") else None
    coverage_name = next(
        (name for name in ("test:coverage", "coverage") if _script_body(scripts, name)),
        None,
    )
    watch_name = "test:watch" if _script_body(scripts, "test:watch") else None
    coverage = _js_run_invocation(manager, coverage_name) if coverage_name else None
    watch = _js_run_invocation(manager, watch_name) if watch_name else None
    return test_command, coverage, watch


def _node_auxiliary_commands(local_path: str) -> tuple[str | None, str | None]:
    _test, coverage, watch = _node_script_commands(local_path)
    return coverage, watch


def _node_package_manager(local_path: str, detected: str | None) -> tuple[str | None, bool]:
    """JS package manager and whether a lockfile selected it.

    ``packageManager`` in package.json counts when no JS lockfile exists, so
    test commands and install instructions name the same tool. A lockfile is
    required before an install command may use ``--frozen-lockfile`` or ``npm ci``.
    """
    package = _read_package_json(local_path)
    has_lockfile = detected in _JS_MANAGERS
    if package is None and not has_lockfile:
        return None, False
    return _js_manager(package, detected), has_lockfile


def _makefile_test_command(local_path: str) -> str | None:
    """``make test`` when a Makefile defines a ``test`` target. No other targets are parsed."""
    for name in ("Makefile", "makefile", "GNUmakefile"):
        text = _read_text(local_path, name)
        if text is not None and _MAKE_TEST_TARGET.search(text):
            return "make test"
    return None


def _python_prefix(package_manager: str | None) -> str:
    if package_manager == "uv":
        return "uv run "
    if package_manager == "poetry":
        return "poetry run "
    return ""


def _requirement_names(text: str) -> set[str]:
    """Package names from requirement lines, ignoring comments and prose.

    A line counts when it is a package specifier (``pytest>=8``) or a single
    assignment (``deps = pytest``). ``description = We do not use pytest``
    does not, because the value is a sentence.
    """
    names: set[str] = set()
    specifier = re.compile(
        r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?(?:\s*(?:[<>=!~]=|[;]|$))"
    )
    assignment = re.compile(r"^[A-Za-z0-9_.-]+\s*=\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*$")
    for raw in text.splitlines():
        line = _strip_hash_comment(raw).strip()
        if not line or line.startswith(("-", "[", "#")):
            continue
        matched = specifier.match(line)
        if matched and " " not in line.split("=", 1)[0]:
            names.add(matched.group(1).lower())
            continue
        assigned = assignment.match(line)
        if assigned:
            names.add(assigned.group(1).lower())
    return names


def _dependency_names(value: object) -> set[str]:
    """Names declared by a PEP 621 list or a Poetry-style dependency table."""
    names: set[str] = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                names |= _requirement_names(item)
    elif isinstance(value, dict):
        for key, spec in value.items():
            if not isinstance(key, str):
                continue
            if isinstance(spec, dict) and "dependencies" in spec and "version" not in spec:
                names |= _dependency_names(spec.get("dependencies"))
                continue
            if key.lower() != "python":
                names.add(key.lower())
    return names


def _pyproject_packages(text: str) -> tuple[set[str], bool, bool]:
    """Declared packages plus whether pytest or ruff has a tool table.

    Invalid TOML contributes neither dependencies nor tool tables. A
    description that mentions pytest is not a dependency.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set(), False, False
    if not isinstance(data, dict):
        return set(), False, False
    names: set[str] = set()
    project = data.get("project")
    if isinstance(project, dict):
        names |= _dependency_names(project.get("dependencies"))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                names |= _dependency_names(group)
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group in groups.values():
            names |= _dependency_names(group)
    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        names |= _dependency_names(poetry.get("dependencies"))
        names |= _dependency_names(poetry.get("dev-dependencies"))
        names |= _dependency_names(poetry.get("group"))
    pytest_table = isinstance(tool, dict) and isinstance(tool.get("pytest"), dict)
    ruff_table = isinstance(tool, dict) and isinstance(tool.get("ruff"), dict)
    return names, pytest_table, ruff_table


def _python_has_pytest(local_path: str) -> bool:
    for name in ("pytest.ini", "pytest.toml", "conftest.py", os.path.join("tests", "conftest.py")):
        if os.path.isfile(os.path.join(local_path, name)):
            return True
    pyproject = _read_text(local_path, "pyproject.toml")
    if pyproject:
        packages, pytest_table, _ruff_table = _pyproject_packages(pyproject)
        if pytest_table or "pytest" in packages:
            return True
    for name in ("tox.ini", "setup.cfg"):
        text = _read_text(local_path, name)
        if text and (_PYTEST_SECTION.search(text) or "pytest" in _requirement_names(text)):
            return True
    try:
        entries = os.listdir(local_path)
    except OSError:
        entries = []
    for entry in entries:
        if entry.startswith("requirements") and entry.endswith((".txt", ".in")):
            text = _read_text(local_path, entry)
            if text and "pytest" in _requirement_names(text):
                return True
    return False


def _python_has_ruff(local_path: str) -> bool:
    for name in ("ruff.toml", ".ruff.toml"):
        if os.path.isfile(os.path.join(local_path, name)):
            return True
    pyproject = _read_text(local_path, "pyproject.toml")
    if not pyproject:
        return False
    packages, _pytest_table, ruff_table = _pyproject_packages(pyproject)
    return ruff_table or "ruff" in packages


def _verified_test_command(
    language: str,
    local_path: str,
    package_manager: str | None,
    node_test: str | None,
    makefile_test: str | None,
) -> str | None:
    """A test command for ``language`` that the repository actually supports."""
    if language == "python":
        if _python_has_pytest(local_path):
            return f"{_python_prefix(package_manager)}pytest"
        return makefile_test
    if language in {"javascript", "typescript"}:
        return node_test or makefile_test
    if language == "go" and os.path.isfile(os.path.join(local_path, "go.mod")):
        return "go test ./..."
    if language == "rust" and os.path.isfile(os.path.join(local_path, "Cargo.toml")):
        return "cargo test"
    if language == "java":
        if os.path.isfile(os.path.join(local_path, "pom.xml")):
            if os.path.isfile(os.path.join(local_path, "mvnw")) or os.path.isfile(os.path.join(local_path, "mvnw.cmd")):
                return "./mvnw test"
            return "mvn test"
        if os.path.isfile(os.path.join(local_path, "build.gradle")) or os.path.isfile(
            os.path.join(local_path, "build.gradle.kts")
        ):
            if os.path.isfile(os.path.join(local_path, "gradlew")) or os.path.isfile(
                os.path.join(local_path, "gradlew.bat")
            ):
                return "./gradlew test"
            return "gradle test"
    return makefile_test


def _verified_lint_command(language: str, local_path: str, package_manager: str | None) -> str | None:
    """A lint command backed by configuration, not by the language name alone."""
    if language == "python" and _python_has_ruff(local_path):
        return f"{_python_prefix(package_manager)}ruff check ."
    if language == "go" and any(
        os.path.isfile(os.path.join(local_path, name))
        for name in (".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json")
    ):
        return "golangci-lint run"
    if language in {"javascript", "typescript"}:
        package = _read_package_json(local_path)
        scripts = package.get("scripts") if package else None
        if _script_body(scripts, "lint"):
            manager = _js_manager(package, package_manager if package_manager in _JS_MANAGERS else None)
            return _js_run_invocation(manager, "lint")
    if language == "rust":
        cargo = _read_text(local_path, "Cargo.toml")
        if cargo and re.search(r"(?i)(?<![A-Za-z0-9_])clippy(?![A-Za-z0-9_])", cargo):
            return "cargo clippy"
        if os.path.isfile(os.path.join(local_path, "clippy.toml")):
            return "cargo clippy"
    return None


def _verified_build_command(language: str, local_path: str, package_manager: str | None) -> str | None:
    """A build command backed by a manifest or script. Unknown builds are omitted."""
    if language == "python":
        if package_manager == "uv":
            return "uv build"
        if package_manager == "poetry":
            return "poetry build"
        pyproject = _read_text(local_path, "pyproject.toml")
        if pyproject and re.search(r"(?m)^\[build-system\]", pyproject):
            return "python -m build"
        return None
    if language in {"javascript", "typescript"}:
        package = _read_package_json(local_path)
        scripts = package.get("scripts") if package else None
        if _script_body(scripts, "build"):
            manager = _js_manager(package, package_manager if package_manager in _JS_MANAGERS else None)
            return _js_run_invocation(manager, "build")
        return None
    if language == "go" and os.path.isfile(os.path.join(local_path, "go.mod")):
        return "go build ./..."
    if language == "rust" and os.path.isfile(os.path.join(local_path, "Cargo.toml")):
        return "cargo build --release"
    if language == "java" and os.path.isfile(os.path.join(local_path, "pom.xml")):
        return "mvn package"
    return None


def _scan_languages_and_commands(
    local_path: str,
) -> tuple[list[str], dict[str, str], dict[str, str], dict[str, str]]:
    """Detect languages and the test, lint, and build commands the repo supports.

    JavaScript and TypeScript test commands require a usable
    ``scripts.test``. Python requires pytest configuration or a declared
    pytest dependency. Go, Rust, and Java use the toolchain command that
    belongs to their manifest. A Makefile ``test`` target is used when the
    ecosystem itself does not show a test command.
    """
    try:
        from darnit.context.auto_detect import detect_languages

        languages = detect_languages(local_path)
    except Exception:
        languages = []

    package_manager = _scan_package_manager(local_path)
    node_test, _coverage, _watch = _node_script_commands(local_path)
    makefile_test = _makefile_test_command(local_path)

    test_cmds: dict[str, str] = {}
    lint_cmds: dict[str, str] = {}
    build_cmds: dict[str, str] = {}

    for lang in languages:
        test_command = _verified_test_command(lang, local_path, package_manager, node_test, makefile_test)
        if test_command:
            test_cmds[lang] = test_command
        lint_command = _verified_lint_command(lang, local_path, package_manager)
        if lint_command:
            lint_cmds[lang] = lint_command
        build_command = _verified_build_command(lang, local_path, package_manager)
        if build_command:
            build_cmds[lang] = build_command

    if not test_cmds and makefile_test:
        test_cmds["project"] = makefile_test

    return languages, test_cmds, lint_cmds, build_cmds


def _resolve_dependency_config(local_path: str, scheduled: set[str]) -> tuple[str | None, str | None]:
    """Return ``(tool name, config path)`` for Dependabot or Renovate.

    The path is the file that exists, or the file this remediation run will
    create. The link target is that path, not a hard-coded sibling.
    """
    for path in _DEPENDABOT_CANDIDATES:
        if _path_available(local_path, path, scheduled):
            return "Dependabot", _normalize_repo_path(path)
    for path in _RENOVATE_CANDIDATES:
        if _path_available(local_path, path, scheduled):
            return "Renovate", _normalize_repo_path(path)
    return None, None


def _scan_dependency_tool(local_path: str) -> str | None:
    """Detect dependency update tool from config file presence."""
    tool, _path = _resolve_dependency_config(local_path, set())
    return tool


def _strip_hash_comment(line: str) -> str:
    """Drop a YAML ``#`` comment that is not inside quotes."""
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def _workflow_code(text: str) -> str:
    """Workflow text with comments removed, so a commented command is not a step."""
    kept: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        kept.append(_strip_hash_comment(line))
    return "\n".join(kept)


def _indent_width(line: str) -> int:
    return len(line[: len(line) - len(line.lstrip(" \t"))].replace("\t", "  "))


def _triggers_pull_request(text: str) -> bool:
    """Whether the workflow ``on:`` block includes a pull-request trigger."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^on:\s*(.*)$", line)
        if not match:
            continue
        inline = match.group(1).strip()
        if inline:
            return re.search(r"(?<![\w-])pull_request(?:_target)?(?![\w-])", inline) is not None
        for follower in lines[index + 1 :]:
            if follower.strip() and _indent_width(follower) == 0:
                break
            if re.search(r"(?<![\w-])pull_request(?:_target)?(?![\w-])", follower):
                return True
        return False
    return False


def _executed_run_scripts(text: str) -> list[str]:
    """Shell bodies of ``run:`` steps, including literal block scalars."""
    lines = text.splitlines()
    scripts: list[str] = []
    index = 0
    while index < len(lines):
        match = _RUN_STEP.match(lines[index])
        if not match:
            index += 1
            continue
        indent = _indent_width(match.group(1))
        rest = match.group(2).strip().strip("'\"")
        index += 1
        if rest in {"|", ">", "|-", ">-", "|+", ">+"}:
            block: list[str] = []
            while index < len(lines):
                follower = lines[index]
                if follower.strip() and _indent_width(follower) <= indent:
                    break
                block.append(follower)
                index += 1
            scripts.append("\n".join(block))
            continue
        scripts.append(rest)
    return scripts


def _script_runs_tests(script: str) -> bool:
    return any(_TEST_COMMAND_LINE.match(line) for line in script.splitlines())


def _ci_test_workflow_evidence(local_path: str) -> tuple[str | None, str | None]:
    """``(pull_request dir, other dir)`` when an executed step runs tests.

    Comments are ignored. A push-only workflow does not establish that pull
    requests are tested. The directory is ``.github/workflows`` or ``None``.
    """
    workflows = os.path.join(local_path, ".github", "workflows")
    if not os.path.isdir(workflows):
        return None, None
    try:
        names = os.listdir(workflows)
    except OSError:
        return None, None
    pull_request = False
    other = False
    for name in names:
        if not name.endswith((".yml", ".yaml")):
            continue
        text = _read_text(local_path, f".github/workflows/{name}")
        if not text:
            continue
        code = _workflow_code(text)
        if not any(_script_runs_tests(script) for script in _executed_run_scripts(code)):
            continue
        if _triggers_pull_request(code):
            pull_request = True
        else:
            other = True
    directory = ".github/workflows"
    return (directory if pull_request else None, directory if other and not pull_request else None)


_USES_STEP = re.compile(r"(?m)^[ \t]*(?:-[ \t]*)?uses:[ \t]*['\"]?([^@\s'\"]+)")


def _workflow_on_pull_request(local_path: str, relative: str | None) -> bool:
    """Whether the workflow file itself declares a pull-request trigger."""
    if not relative:
        return False
    text = _read_text(local_path, relative)
    if not text:
        return False
    return _triggers_pull_request(_workflow_code(text))


def _scan_ci_workflows(local_path: str) -> dict[str, list[str]]:
    """Parse GitHub Actions workflows for tool identification.

    Only a real ``uses:`` step is an action. Comments are removed first, and
    ``uses:`` inside other text, such as a ``run:`` command, is ignored.
    Known actions are mapped via :data:`ACTION_TOOL_MAP`.
    """
    workflows_dir = os.path.join(local_path, ".github", "workflows")
    if not os.path.isdir(workflows_dir):
        return {}

    tools: dict[str, list[str]] = {}

    try:
        names = os.listdir(workflows_dir)
    except OSError:
        return tools

    for filename in names:
        if not filename.endswith((".yml", ".yaml")):
            continue
        content = _read_text(local_path, f".github/workflows/{filename}")
        if not content:
            continue
        for match in _USES_STEP.finditer(_workflow_code(content)):
            action_ref = match.group(1)
            for prefix, (tool_name, category) in ACTION_TOOL_MAP.items():
                if action_ref.startswith(prefix):
                    tools.setdefault(category, [])
                    if tool_name not in tools[category]:
                        tools[category].append(tool_name)
                    break

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
            content = read_repository_text(local_path, doc_path, errors="replace")[
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
            content = read_repository_text(local_path, pyproject_path, errors="replace")
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

    # Primary language commands. Absent when the repository did not evidence them.
    if ctx.primary_language and ctx.primary_language in ctx.test_commands:
        result["scan.test_command"] = ctx.test_commands[ctx.primary_language]
    elif "project" in ctx.test_commands:
        result["scan.test_command"] = ctx.test_commands["project"]
    if ctx.primary_language and ctx.primary_language in ctx.lint_commands:
        result["scan.lint_command"] = ctx.lint_commands[ctx.primary_language]
    for lang in ("javascript", "typescript"):
        if lang in ctx.test_commands:
            result["scan.node_test_command"] = ctx.test_commands[lang]
            break
    for lang, key in (
        ("python", "scan.python_test_command"),
        ("go", "scan.go_test_command"),
        ("rust", "scan.rust_test_command"),
        ("java", "scan.java_test_command"),
    ):
        if lang in ctx.test_commands:
            result[key] = ctx.test_commands[lang]
    if ctx.node_coverage_command:
        result["scan.node_coverage_command"] = ctx.node_coverage_command
    if ctx.node_watch_command:
        result["scan.node_watch_command"] = ctx.node_watch_command

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
    if ctx.dependency_config_path:
        result["scan.dependency_config_path"] = ctx.dependency_config_path
    if ctx.sca_workflow_path:
        result["scan.sca_workflow_path"] = ctx.sca_workflow_path
    if ctx.sca_workflow_on_pull_request:
        result["scan.sca_workflow_on_pull_request"] = "true"
    if ctx.sast_workflow_path:
        result["scan.sast_workflow_path"] = ctx.sast_workflow_path
    if ctx.ci_pr_test_workflows:
        result["scan.ci_pr_test_workflows"] = ctx.ci_pr_test_workflows
    if ctx.ci_test_workflows_without_pull_request:
        result["scan.ci_test_workflows_without_pull_request"] = ctx.ci_test_workflows_without_pull_request
    if ctx.node_package_manager:
        result["scan.node_package_manager"] = ctx.node_package_manager
    if ctx.node_has_lockfile:
        result["scan.node_has_lockfile"] = "true"

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
        result["scan.code_of_conduct_link"] = _markdown_link("Code of Conduct", ctx.code_of_conduct_path)
    if ctx.security_policy_path:
        result["scan.security_policy_link"] = _markdown_link("Security Policy", ctx.security_policy_path)
    if ctx.maintainers_path:
        result["scan.maintainers_path"] = ctx.maintainers_path
        result["scan.maintainers_link"] = _markdown_link("MAINTAINERS.md", ctx.maintainers_path)
    if ctx.codeowners_path:
        result["scan.codeowners_path"] = ctx.codeowners_path
        result["scan.codeowners_link"] = _markdown_link("CODEOWNERS", ctx.codeowners_path)
    if ctx.contributing_path:
        result["scan.contributing_link"] = _markdown_link("Contributing Guide", ctx.contributing_path)
    if ctx.readme_path:
        result["scan.readme_link"] = _markdown_link("README", ctx.readme_path)
    if ctx.license_path:
        result["scan.license_link"] = _markdown_link("LICENSE", ctx.license_path)
    if ctx.docs_dir:
        result["scan.docs_link"] = _markdown_link("docs/", f"{ctx.docs_dir}/")
    if ctx.security_policy_path:
        result["scan.security_policy_link_from_docs"] = _markdown_link(
            "Security Policy", _link_target_from(ctx.security_policy_path, "docs")
        )

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
