"""Tests for the repository scanner module."""


import json

from darnit_baseline.remediation.scanner import (
    APP_CAPABILITY_MAP,
    DirectoryTree,
    RepoScanContext,
    _scan_ci_workflows,
    _scan_dependency_tool,
    _scan_directory_structure,
    _scan_existing_docs,
    _scan_languages_and_commands,
    _scan_package_manager,
    flatten_scan_context,
    scan_repository,
)

# =============================================================================
# RepoScanContext and flatten_scan_context tests (T012)
# =============================================================================


class TestRepoScanContext:
    """Tests for RepoScanContext dataclass creation."""

    def test_empty_context(self):
        ctx = RepoScanContext()
        assert ctx.languages == []
        assert ctx.primary_language is None
        assert ctx.package_manager is None
        assert ctx.test_commands == {}
        assert ctx.ci_tools == {}
        assert ctx.directory_tree.top_level == []
        assert ctx.existing_docs == {}

    def test_populated_context(self):
        ctx = RepoScanContext(
            languages=["python", "go"],
            primary_language="python",
            package_manager="uv",
            test_commands={"python": "uv run pytest", "go": "go test ./..."},
            lint_commands={"python": "uv run ruff check ."},
            ci_tools={"sast": ["CodeQL"]},
            dependency_update_tool="Dependabot",
        )
        assert ctx.languages == ["python", "go"]
        assert ctx.primary_language == "python"
        assert ctx.ci_tools["sast"] == ["CodeQL"]


class TestFlattenScanContext:
    """Tests for flatten_scan_context()."""

    def test_empty_context_returns_empty_dict(self):
        ctx = RepoScanContext()
        result = flatten_scan_context(ctx)
        assert result == {}

    def test_language_fields(self):
        ctx = RepoScanContext(
            languages=["python", "go"],
            primary_language="python",
            package_manager="uv",
            test_commands={"python": "uv run pytest"},
            lint_commands={"python": "uv run ruff check ."},
        )
        result = flatten_scan_context(ctx)
        assert result["scan.languages"] == "python, go"
        assert result["scan.primary_language"] == "python"
        assert result["scan.package_manager"] == "uv"
        assert result["scan.test_command"] == "uv run pytest"
        assert result["scan.lint_command"] == "uv run ruff check ."

    def test_ci_tools(self):
        ctx = RepoScanContext(
            ci_tools={
                "sast": ["CodeQL", "Semgrep"],
                "sca": ["GitHub Dependency Review"],
            }
        )
        result = flatten_scan_context(ctx)
        assert result["scan.ci_sast_tools"] == "CodeQL, Semgrep"
        assert result["scan.ci_sca_tools"] == "GitHub Dependency Review"
        assert "scan.ci_sbom_tools" not in result

    def test_dependency_tool(self):
        ctx = RepoScanContext(dependency_update_tool="Dependabot")
        result = flatten_scan_context(ctx)
        assert result["scan.dependency_tool"] == "Dependabot"

    def test_directory_tree(self):
        tree = DirectoryTree(
            top_level=["packages/", "tests/"],
            source_dirs={"packages/": ["darnit/", "darnit-baseline/"]},
        )
        ctx = RepoScanContext(directory_tree=tree)
        result = flatten_scan_context(ctx)
        assert "scan.directory_tree" in result
        assert "packages" in result["scan.directory_tree"]

    def test_doc_links(self):
        ctx = RepoScanContext(doc_links=["https://docs.example.com"])
        result = flatten_scan_context(ctx)
        assert "https://docs.example.com" in result["scan.doc_links"]

    def test_governance_context(self):
        ctx = RepoScanContext(governance_context="governed by Kusari, Inc")
        result = flatten_scan_context(ctx)
        assert result["scan.governance_context"] == "governed by Kusari, Inc"

    def test_community_links(self):
        ctx = RepoScanContext(
            code_of_conduct_path="CODE_OF_CONDUCT.md",
            security_policy_path="SECURITY.md",
        )
        result = flatten_scan_context(ctx)
        assert "CODE_OF_CONDUCT.md" in result["scan.code_of_conduct_link"]
        assert "SECURITY.md" in result["scan.security_policy_link"]

    def test_multi_language_test_commands(self):
        ctx = RepoScanContext(
            languages=["python", "go"],
            primary_language="python",
            test_commands={"python": "uv run pytest", "go": "go test ./..."},
            lint_commands={"python": "uv run ruff check .", "go": "golangci-lint run"},
        )
        result = flatten_scan_context(ctx)
        all_cmds = result["scan.test_commands_all"]
        assert "uv run pytest" in all_cmds
        assert "go test" in all_cmds
        assert "### Python" in all_cmds
        assert "### Go" in all_cmds


# =============================================================================
# Package manager detection tests (T016)
# =============================================================================


class TestScanPackageManager:
    """Tests for _scan_package_manager()."""

    def test_uv_lock(self, tmp_path):
        (tmp_path / "uv.lock").touch()
        assert _scan_package_manager(str(tmp_path)) == "uv"

    def test_poetry_lock(self, tmp_path):
        (tmp_path / "poetry.lock").touch()
        assert _scan_package_manager(str(tmp_path)) == "poetry"

    def test_npm_lock(self, tmp_path):
        (tmp_path / "package-lock.json").touch()
        assert _scan_package_manager(str(tmp_path)) == "npm"

    def test_yarn_lock(self, tmp_path):
        (tmp_path / "yarn.lock").touch()
        assert _scan_package_manager(str(tmp_path)) == "yarn"

    def test_cargo_lock(self, tmp_path):
        (tmp_path / "Cargo.lock").touch()
        assert _scan_package_manager(str(tmp_path)) == "cargo"

    def test_no_lockfile(self, tmp_path):
        assert _scan_package_manager(str(tmp_path)) is None

    def test_uv_takes_priority_over_npm(self, tmp_path):
        (tmp_path / "uv.lock").touch()
        (tmp_path / "package-lock.json").touch()
        assert _scan_package_manager(str(tmp_path)) == "uv"


# =============================================================================
# Directory structure scanning tests (T020)
# =============================================================================


class TestScanDirectoryStructure:
    """Tests for _scan_directory_structure()."""

    def test_monorepo(self, tmp_path):
        (tmp_path / "packages" / "darnit").mkdir(parents=True)
        (tmp_path / "packages" / "darnit-baseline").mkdir(parents=True)
        (tmp_path / "tests").mkdir()
        (tmp_path / "docs").mkdir()

        tree = _scan_directory_structure(str(tmp_path))
        assert "packages/" in tree.top_level
        assert "tests/" in tree.top_level
        assert "docs/" in tree.top_level
        assert "packages/" in tree.source_dirs
        assert "darnit/" in tree.source_dirs["packages/"]
        assert "darnit-baseline/" in tree.source_dirs["packages/"]

    def test_go_conventional(self, tmp_path):
        (tmp_path / "cmd" / "server").mkdir(parents=True)
        (tmp_path / "pkg" / "auth").mkdir(parents=True)
        (tmp_path / "internal" / "repo").mkdir(parents=True)

        tree = _scan_directory_structure(str(tmp_path))
        assert "cmd/" in tree.top_level
        assert "pkg/" in tree.top_level
        assert "internal/" in tree.top_level
        assert "cmd/" in tree.source_dirs

    def test_flat_structure(self, tmp_path):
        (tmp_path / "main.py").touch()
        (tmp_path / "utils.py").touch()

        tree = _scan_directory_structure(str(tmp_path))
        assert tree.top_level == []
        assert tree.source_dirs == {}

    def test_excludes_hidden_dirs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".github").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "src" / "main").mkdir(parents=True)

        tree = _scan_directory_structure(str(tmp_path))
        assert ".git/" not in tree.top_level
        assert ".github/" not in tree.top_level
        assert "node_modules/" not in tree.top_level
        assert "src/" in tree.top_level

    def test_formatted_output(self, tmp_path):
        (tmp_path / "packages" / "core").mkdir(parents=True)
        (tmp_path / "tests").mkdir()

        tree = _scan_directory_structure(str(tmp_path))
        formatted = tree.formatted
        assert "packages" in formatted
        assert "core" in formatted
        assert "|" in formatted  # markdown table


# =============================================================================
# Language and command detection tests (T027)
# =============================================================================


class TestScanLanguagesAndCommands:
    """Tests for _scan_languages_and_commands()."""

    def test_python_with_uv(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'demo'\nversion = '0.1.0'\n"
            "dependencies = ['pytest', 'ruff']\n"
        )
        (tmp_path / "uv.lock").touch()

        langs, test_cmds, lint_cmds, build_cmds = _scan_languages_and_commands(
            str(tmp_path)
        )
        assert "python" in langs
        assert test_cmds["python"] == "uv run pytest"
        assert lint_cmds["python"] == "uv run ruff check ."

    def test_go_project(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n")
        (tmp_path / ".golangci.yml").write_text("run:\n  timeout: 5m\n")

        langs, test_cmds, lint_cmds, _ = _scan_languages_and_commands(str(tmp_path))
        assert "go" in langs
        assert test_cmds["go"] == "go test ./..."
        assert lint_cmds["go"] == "golangci-lint run"

    def test_multi_language(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\ndependencies = ['pytest']\n")
        (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest run"}}\n')

        langs, test_cmds, _, _ = _scan_languages_and_commands(str(tmp_path))
        assert "python" in langs
        assert "javascript" in langs
        assert "python" in test_cmds
        assert "javascript" in test_cmds

    def test_no_language(self, tmp_path):
        langs, test_cmds, _, _ = _scan_languages_and_commands(str(tmp_path))
        assert langs == []
        assert test_cmds == {}

    def test_rust_project(self, tmp_path):
        (tmp_path / "Cargo.toml").touch()

        langs, test_cmds, _, _ = _scan_languages_and_commands(str(tmp_path))
        assert "rust" in langs
        assert test_cmds["rust"] == "cargo test"


# =============================================================================
# Dependency tool detection tests
# =============================================================================


class TestScanDependencyTool:
    """Tests for _scan_dependency_tool()."""

    def test_dependabot(self, tmp_path):
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "dependabot.yml").touch()
        assert _scan_dependency_tool(str(tmp_path)) == "Dependabot"

    def test_renovate(self, tmp_path):
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "renovate.json").touch()
        assert _scan_dependency_tool(str(tmp_path)) == "Renovate"

    def test_no_tool(self, tmp_path):
        assert _scan_dependency_tool(str(tmp_path)) is None


# =============================================================================
# CI workflow parsing tests (T033)
# =============================================================================


class TestScanCIWorkflows:
    """Tests for _scan_ci_workflows()."""

    def test_codeql_detection(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "sast.yml").write_text(
            "jobs:\n  analyze:\n    steps:\n"
            "      - uses: github/codeql-action/init@v3\n"
            "      - uses: github/codeql-action/analyze@v3\n"
        )

        tools = _scan_ci_workflows(str(tmp_path))
        assert "sast" in tools
        assert "CodeQL" in tools["sast"]

    def test_multiple_tools(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "security.yml").write_text(
            "jobs:\n  scan:\n    steps:\n"
            "      - uses: github/codeql-action/init@v3\n"
            "      - uses: anchore/sbom-action@v0\n"
            "      - uses: sigstore/cosign-installer@v3\n"
        )

        tools = _scan_ci_workflows(str(tmp_path))
        assert "CodeQL" in tools.get("sast", [])
        assert "Syft (Anchore)" in tools.get("sbom", [])
        assert "Cosign" in tools.get("signing", [])

    def test_unknown_actions_ignored(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(
            "jobs:\n  build:\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: custom-org/custom-action@v1\n"
        )

        tools = _scan_ci_workflows(str(tmp_path))
        # checkout and custom actions are not in ACTION_TOOL_MAP
        assert tools == {}

    def test_no_workflows_dir(self, tmp_path):
        tools = _scan_ci_workflows(str(tmp_path))
        assert tools == {}

    def test_deduplication(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "sast.yml").write_text(
            "jobs:\n  analyze:\n    steps:\n"
            "      - uses: github/codeql-action/init@v3\n"
        )
        (wf_dir / "pr.yml").write_text(
            "jobs:\n  check:\n    steps:\n"
            "      - uses: github/codeql-action/analyze@v3\n"
        )

        tools = _scan_ci_workflows(str(tmp_path))
        # CodeQL should appear only once even though found in two files
        assert tools["sast"].count("CodeQL") == 1

    def test_commented_codeql_action_is_not_detected(self, tmp_path):
        """A commented uses: entry is not an installed SAST tool."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(
            "jobs:\n  build:\n    steps:\n"
            "      # - uses: github/codeql-action/init@v3\n"
            "      - run: echo hello\n"
        )

        tools = _scan_ci_workflows(str(tmp_path))
        assert "CodeQL" not in tools.get("sast", [])
        assert tools == {}

    def test_commented_dependency_review_action_is_not_detected(self, tmp_path):
        """A commented dependency-review action is not an SCA tool."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(
            "jobs:\n  build:\n    steps:\n"
            "      # - uses: actions/dependency-review-action@v4\n"
            "      - run: echo hello\n"
        )

        tools = _scan_ci_workflows(str(tmp_path))
        assert "GitHub Dependency Review" not in tools.get("sca", [])
        assert tools == {}

    def test_real_codeql_and_dependency_review_actions_are_detected(self, tmp_path):
        """Uncommented uses: steps still identify CodeQL and dependency review."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "security.yml").write_text(
            "jobs:\n  analyze:\n    steps:\n"
            "      - uses: github/codeql-action/init@v3\n"
            "      - name: Review\n"
            "        uses: actions/dependency-review-action@v4\n"
        )

        tools = _scan_ci_workflows(str(tmp_path))
        assert "CodeQL" in tools.get("sast", [])
        assert "GitHub Dependency Review" in tools.get("sca", [])


# =============================================================================
# Existing docs scanning tests (T039)
# =============================================================================


class TestScanExistingDocs:
    """Tests for _scan_existing_docs()."""

    def test_readme_with_links(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# My Project\n\n"
            "See docs at https://docs.example.com\n"
            "Also check https://api.example.com/v1\n"
        )

        docs = _scan_existing_docs(str(tmp_path))
        assert docs["README.md"].exists
        assert "https://docs.example.com" in docs["README.md"].links
        assert "https://api.example.com/v1" in docs["README.md"].links

    def test_contributing_with_governance(self, tmp_path):
        (tmp_path / "CONTRIBUTING.md").write_text(
            "# Contributing\n\n"
            "This project is governed by Kusari, Inc\n"
        )

        docs = _scan_existing_docs(str(tmp_path))
        assert docs["CONTRIBUTING.md"].exists
        assert len(docs["CONTRIBUTING.md"].governance_mentions) > 0
        assert "governed by Kusari" in docs["CONTRIBUTING.md"].governance_mentions[0]

    def test_missing_docs(self, tmp_path):
        docs = _scan_existing_docs(str(tmp_path))
        assert not docs["README.md"].exists
        assert not docs["CONTRIBUTING.md"].exists
        assert docs["README.md"].links == []

    def test_code_of_conduct_existence(self, tmp_path):
        (tmp_path / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n")

        docs = _scan_existing_docs(str(tmp_path))
        assert docs["CODE_OF_CONDUCT.md"].exists


# =============================================================================
# Full scan_repository integration test
# =============================================================================


class TestScanRepository:
    """Integration tests for scan_repository()."""

    def test_empty_repo(self, tmp_path):
        ctx = scan_repository(str(tmp_path))
        assert ctx.languages == []
        assert ctx.primary_language is None
        assert ctx.ci_tools == {}
        assert ctx.directory_tree.top_level == []

    def test_python_repo(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\ndependencies = ['pytest']\n")
        (tmp_path / "uv.lock").touch()
        (tmp_path / "src" / "main").mkdir(parents=True)
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "dependabot.yml").touch()
        (tmp_path / "SECURITY.md").write_text("# Security\n")
        (tmp_path / "README.md").write_text(
            "# Project\nDocs: https://docs.example.com\n"
        )

        ctx = scan_repository(str(tmp_path))
        assert "python" in ctx.languages
        assert ctx.package_manager == "uv"
        assert ctx.test_commands["python"] == "uv run pytest"
        assert ctx.dependency_update_tool == "Dependabot"
        assert ctx.security_policy_path == "SECURITY.md"
        assert "https://docs.example.com" in ctx.doc_links
        assert "src/" in ctx.directory_tree.top_level


# =============================================================================
# GitHub Apps detection and capability merging (T041)
# =============================================================================


class TestGitHubAppsCapabilityMerge:
    """Tests for GitHub Apps capability merging into scan context."""

    def test_app_capability_map_has_kusari_inspector(self):
        assert "kusari-inspector" in APP_CAPABILITY_MAP
        name, caps = APP_CAPABILITY_MAP["kusari-inspector"]
        assert name == "Kusari Inspector"
        assert "sast" in caps
        assert "sca" in caps

    def test_flatten_merges_app_capabilities_into_ci_tools(self):
        """GitHub App capabilities merge into scan.ci_*_tools keys."""
        ctx = RepoScanContext(
            ci_tools={"sast": ["CodeQL"]},
            github_apps=[
                {"name": "Kusari Inspector", "slug": "kusari-inspector",
                 "capabilities": ["sast", "sca", "secrets", "license"]},
            ],
        )
        flat = flatten_scan_context(ctx)

        # SAST should contain both CodeQL (from workflows) and Kusari Inspector (from apps)
        assert "CodeQL" in flat["scan.ci_sast_tools"]
        assert "Kusari Inspector" in flat["scan.ci_sast_tools"]
        # SCA should be set from app alone (no workflow SCA detected)
        assert flat["scan.ci_sca_tools"] == "Kusari Inspector"
        # Secrets and license should be new keys
        assert flat["scan.ci_secrets_tools"] == "Kusari Inspector"
        assert flat["scan.ci_license_tools"] == "Kusari Inspector"
        # App names list
        assert flat["scan.github_apps"] == "Kusari Inspector"

    def test_flatten_no_duplicate_app_in_existing_tools(self):
        """If an app name already appears in CI tools, don't duplicate it."""
        ctx = RepoScanContext(
            ci_tools={"sast": ["Kusari Inspector"]},
            github_apps=[
                {"name": "Kusari Inspector", "slug": "kusari-inspector",
                 "capabilities": ["sast"]},
            ],
        )
        flat = flatten_scan_context(ctx)
        # Should appear once, not twice
        assert flat["scan.ci_sast_tools"].count("Kusari Inspector") == 1

    def test_flatten_empty_apps(self):
        """No github_apps produces no scan.github_apps key."""
        ctx = RepoScanContext()
        flat = flatten_scan_context(ctx)
        assert "scan.github_apps" not in flat


# =============================================================================
# Issue #751: test commands must come from the repository
# =============================================================================

# Commands the scanner currently invents for JavaScript. A Vue/Vite package
# whose scripts do not include "test" must not be reported as having any of them.
_UNVERIFIED_JS_TEST_COMMANDS = (
    "npm test",
    "npm run test",
    "make test",
    "npx jest",
    "test:coverage",
    "test:watch",
)

_VUE_VITE_SCRIPTS_WITHOUT_TESTS = {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
}


def _write_vue_vite_package_json(root, scripts: dict[str, str]) -> None:
    """Write a Vue/Vite-style package.json whose scripts are exactly ``scripts``."""
    package = {
        "name": "vue-vite-app",
        "private": True,
        "version": "0.0.0",
        "type": "module",
        "scripts": scripts,
        "dependencies": {"vue": "^3.5.13"},
        "devDependencies": {
            "@vitejs/plugin-vue": "^5.2.1",
            "vite": "^6.0.0",
        },
    }
    (root / "package.json").write_text(json.dumps(package, indent=2) + "\n")


def _javascript_test_claim(local_path: str) -> tuple[str, str]:
    """Return the JavaScript test command and every place the scan publishes it."""
    ctx = scan_repository(local_path)
    command = ctx.test_commands.get("javascript", "").strip()
    flat = flatten_scan_context(ctx)
    published = "\n".join(
        part
        for part in (
            command,
            flat.get("scan.test_command", ""),
            flat.get("scan.test_commands_all", ""),
        )
        if part
    )
    return command, published


class TestJavaScriptTestCommandAccuracy:
    """Issue #751: only report a JavaScript test command the repository defines."""

    def test_vue_vite_without_test_script_does_not_claim_a_test_command(self, tmp_path):
        """A package.json with dev, build, and preview has no verified test command."""
        _write_vue_vite_package_json(tmp_path, dict(_VUE_VITE_SCRIPTS_WITHOUT_TESTS))

        ctx = scan_repository(str(tmp_path))
        assert "javascript" in ctx.languages

        command, published = _javascript_test_claim(str(tmp_path))
        invented = [item for item in _UNVERIFIED_JS_TEST_COMMANDS if item in published or item in command]
        assert invented == [], f"scanner claimed a verified test command that package.json does not define: {invented}"

    def test_vue_vite_with_test_script_identifies_that_command(self, tmp_path):
        """scripts.test is identified for that repository and not for one without it."""
        declared = "vitest run"
        with_tests = tmp_path / "with-tests"
        without_tests = tmp_path / "without-tests"
        with_tests.mkdir()
        without_tests.mkdir()
        _write_vue_vite_package_json(
            with_tests,
            {**_VUE_VITE_SCRIPTS_WITHOUT_TESTS, "test": declared},
        )
        _write_vue_vite_package_json(without_tests, dict(_VUE_VITE_SCRIPTS_WITHOUT_TESTS))

        ctx = scan_repository(str(with_tests))
        assert "javascript" in ctx.languages
        command, published = _javascript_test_claim(str(with_tests))
        assert command, "scanner did not identify a test command"
        assert declared in command or command in {"npm test", "npm run test"}
        assert command in published

        _, absent_claim = _javascript_test_claim(str(without_tests))
        assert command not in absent_claim, (
            f"scanner reported {command!r} for a package.json with scripts.test, "
            "but that same command is also reported when no test script exists"
        )

    def test_yarn_lock_invokes_the_test_script_with_yarn(self, tmp_path):
        """A Yarn lockfile selects yarn test when scripts.test exists."""
        _write_vue_vite_package_json(tmp_path, {**_VUE_VITE_SCRIPTS_WITHOUT_TESTS, "test": "vitest run"})
        (tmp_path / "yarn.lock").touch()

        command, _published = _javascript_test_claim(str(tmp_path))
        assert command == "yarn test"

    def test_coverage_and_watch_require_their_own_scripts(self, tmp_path):
        """Coverage and watch commands are published only when those scripts exist."""
        _write_vue_vite_package_json(
            tmp_path,
            {
                **_VUE_VITE_SCRIPTS_WITHOUT_TESTS,
                "test": "vitest run",
                "test:coverage": "vitest run --coverage",
                "test:watch": "vitest",
            },
        )

        ctx = scan_repository(str(tmp_path))
        assert ctx.node_coverage_command == "npm run test:coverage"
        assert ctx.node_watch_command == "npm run test:watch"

        bare = tmp_path / "bare"
        bare.mkdir()
        _write_vue_vite_package_json(bare, {**_VUE_VITE_SCRIPTS_WITHOUT_TESTS, "test": "vitest run"})
        bare_ctx = scan_repository(str(bare))
        assert bare_ctx.test_commands.get("javascript") == "npm test"
        assert bare_ctx.node_coverage_command is None
        assert bare_ctx.node_watch_command is None

    def test_invalid_package_json_does_not_publish_a_test_command(self, tmp_path):
        """A package.json that does not parse contributes no test command."""
        (tmp_path / "package.json").write_text("{ this is not json\n")

        ctx = scan_repository(str(tmp_path))
        assert "javascript" in ctx.languages
        assert "javascript" not in ctx.test_commands
        assert ctx.node_coverage_command is None

    def test_python_without_pytest_does_not_claim_pytest(self, tmp_path):
        """uv.lock and an empty pyproject.toml are not evidence of pytest."""
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "uv.lock").touch()

        _langs, test_cmds, lint_cmds, _build = _scan_languages_and_commands(str(tmp_path))
        assert "python" not in test_cmds
        assert "python" not in lint_cmds

    def test_pyproject_prose_does_not_select_pytest_or_ruff(self, tmp_path):
        """A description that names pytest is not a dependency or a config table."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "demo"\ndescription = "We do not use pytest or ruff"\n'
        )

        _langs, test_cmds, lint_cmds, _build = _scan_languages_and_commands(str(tmp_path))
        assert "pytest" not in test_cmds.get("python", "")
        assert "python" not in lint_cmds

    def test_commented_test_command_is_not_a_ci_test(self, tmp_path):
        """npm test in a comment is not an executed step."""
        workflow = tmp_path / ".github" / "workflows" / "ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "name: docs\n"
            "on:\n"
            "  pull_request:\n"
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - run: echo hello\n"
            "# npm test\n"
        )

        ctx = scan_repository(str(tmp_path))
        assert ctx.ci_pr_test_workflows is None
        assert ctx.ci_test_workflows_without_pull_request is None

    def test_push_only_test_workflow_does_not_claim_pull_requests(self, tmp_path):
        """A test command that runs only on push is not pull-request evidence."""
        workflow = tmp_path / ".github" / "workflows" / "ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "name: test\n"
            "on:\n"
            "  push:\n"
            "    branches: [main]\n"
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - run: npm test\n"
        )

        ctx = scan_repository(str(tmp_path))
        assert ctx.ci_pr_test_workflows is None
        assert ctx.ci_test_workflows_without_pull_request == ".github/workflows"

    def test_pull_request_workflow_executes_test_command(self, tmp_path):
        """A pull_request job whose run step is npm test is pull-request evidence."""
        workflow = tmp_path / ".github" / "workflows" / "ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "name: test\n"
            "on: pull_request\n"
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - run: npm test\n"
        )

        ctx = scan_repository(str(tmp_path))
        assert ctx.ci_pr_test_workflows == ".github/workflows"
        assert ctx.ci_test_workflows_without_pull_request is None

    def test_package_manager_field_without_lockfile_selects_pnpm(self, tmp_path):
        """packageManager names the test command when no lockfile is present."""
        (tmp_path / "package.json").write_text(
            '{"packageManager": "pnpm@9.0.0", "scripts": {"test": "vitest run"}}\n'
        )

        ctx = scan_repository(str(tmp_path))
        assert ctx.test_commands["javascript"] == "pnpm test"
        assert ctx.node_package_manager == "pnpm"
        assert ctx.node_has_lockfile is False

    def test_scheduled_paths_count_as_present_for_links(self, tmp_path):
        """A file this remediation run will create may be linked before it exists."""
        ctx = scan_repository(
            str(tmp_path),
            scheduled_paths={".github/workflows/sca.yml", "MAINTAINERS.md", ".github/dependabot.yml"},
        )
        assert ctx.sca_workflow_path == ".github/workflows/sca.yml"
        assert ctx.maintainers_path == "MAINTAINERS.md"
        assert ctx.dependency_update_tool == "Dependabot"
        assert ctx.dependency_config_path == ".github/dependabot.yml"
        assert ctx.codeowners_path is None

    def test_existing_governance_files_are_recorded(self, tmp_path):
        """Links use the path that is actually in the repository."""
        (tmp_path / "MAINTAINERS.md").write_text("# Maintainers\n")
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "CODEOWNERS").write_text("* @team\n")
        (tmp_path / "renovate.json").write_text("{}\n")

        ctx = scan_repository(str(tmp_path))
        assert ctx.maintainers_path == "MAINTAINERS.md"
        assert ctx.codeowners_path == ".github/CODEOWNERS"
        assert ctx.dependency_update_tool == "Renovate"
        assert ctx.dependency_config_path == "renovate.json"
        flat = flatten_scan_context(ctx)
        assert flat["scan.maintainers_link"] == "[MAINTAINERS.md](MAINTAINERS.md)"
        assert flat["scan.codeowners_link"] == "[CODEOWNERS](.github/CODEOWNERS)"
