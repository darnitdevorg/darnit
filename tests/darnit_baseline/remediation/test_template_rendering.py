"""End-to-end tests for context-aware template rendering.

These tests verify that the full pipeline (scan → flatten → substitute)
produces templates with real project data instead of generic placeholders.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from darnit.config.framework_schema import TemplateConfig
from darnit.remediation.executor import RemediationExecutor
from darnit_baseline.remediation.scanner import (
    flatten_scan_context,
    scan_repository,
)


def _get_framework_path() -> str:
    """Get the absolute path to the openssf-baseline.toml file."""
    from darnit_baseline import get_framework_path

    p = get_framework_path()
    assert p is not None, "Framework path not found"
    return str(p)


def _load_template(template_name: str) -> dict[str, TemplateConfig]:
    """Load a single template from the framework TOML config."""
    import tomllib

    fw_path = _get_framework_path()
    with open(fw_path, "rb") as f:
        config = tomllib.load(f)

    templates_raw = config.get("templates", {})
    tmpl_data = templates_raw.get(template_name)
    if not tmpl_data:
        pytest.skip(f"Template '{template_name}' not found in framework TOML")

    return {template_name: TemplateConfig(**tmpl_data)}


def _render_template(
    template_name: str,
    tmp_path: Path,
    owner: str = "test-org",
    repo: str = "test-repo",
    scheduled_paths: set[str] | None = None,
) -> str:
    """Scan a test repo and render a template with scan context.

    Returns the rendered template content.
    """
    scan_ctx = scan_repository(str(tmp_path), scheduled_paths=scheduled_paths)
    scan_values = flatten_scan_context(scan_ctx)

    fw_path = _get_framework_path()
    templates = _load_template(template_name)

    executor = RemediationExecutor(
        local_path=str(tmp_path),
        owner=owner,
        repo=repo,
        templates=templates,
        scan_values=scan_values,
        framework_path=fw_path,
    )

    content = executor._get_template_content(template_name)
    assert content is not None, f"Template '{template_name}' content is None"
    return executor._substitute(content, "OSPS-TEST-01")


# =============================================================================
# T021: ARCHITECTURE.md e2e tests
# =============================================================================


class TestArchitectureTemplateRendering:
    """Verify ARCHITECTURE.md contains real paths, not fabricated ones."""

    def test_monorepo_real_paths(self, tmp_path):
        """Given a monorepo, ARCHITECTURE.md lists real package directories."""
        (tmp_path / "packages" / "darnit" / "src").mkdir(parents=True)
        (tmp_path / "packages" / "darnit-baseline" / "src").mkdir(parents=True)
        (tmp_path / "tests").mkdir()
        (tmp_path / "docs").mkdir()

        rendered = _render_template("architecture_template", tmp_path)

        # Real paths present
        assert "packages" in rendered
        assert "darnit" in rendered
        assert "darnit-baseline" in rendered
        assert "tests" in rendered

        # Fabricated paths absent
        assert "src/core/" not in rendered
        assert "src/api/" not in rendered
        assert "src/storage/" not in rendered
        assert "src/config/" not in rendered

    def test_go_conventional_paths(self, tmp_path):
        """Given a Go project, ARCHITECTURE.md lists cmd/pkg/internal."""
        (tmp_path / "cmd" / "server").mkdir(parents=True)
        (tmp_path / "pkg" / "auth").mkdir(parents=True)
        (tmp_path / "internal" / "repo").mkdir(parents=True)

        rendered = _render_template("architecture_template", tmp_path)

        assert "cmd" in rendered
        assert "pkg" in rendered
        assert "internal" in rendered
        assert "server" in rendered
        assert "auth" in rendered

    def test_flat_repo_no_fake_paths(self, tmp_path):
        """Given a flat repo, ARCHITECTURE.md has no fabricated directories."""
        (tmp_path / "main.py").touch()
        (tmp_path / "README.md").touch()

        rendered = _render_template("architecture_template", tmp_path)

        # Should not contain any fake paths
        assert "src/core/" not in rendered
        assert "src/api/" not in rendered
        assert "src/storage/" not in rendered


# =============================================================================
# T028: TEST-REQUIREMENTS.md and DEPENDENCIES.md e2e tests
# =============================================================================


class TestLanguageAwareTemplateRendering:
    """Verify generated docs contain language-idiomatic commands."""

    def test_python_uv_test_command(self, tmp_path):
        """Given a Python/uv project, TEST-REQUIREMENTS contains uv run pytest."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\ndependencies = ['pytest']\n")
        (tmp_path / "uv.lock").touch()

        rendered = _render_template("test_requirements_contributing", tmp_path)

        assert "uv run pytest" in rendered
        assert "make test" not in rendered

    def test_go_test_command(self, tmp_path):
        """Given a Go project, TEST-REQUIREMENTS contains go test."""
        (tmp_path / "go.mod").touch()

        rendered = _render_template("test_requirements_contributing", tmp_path)

        assert "go test" in rendered

    def test_multi_language_shows_all(self, tmp_path):
        """Given a Python+JS project, TEST-REQUIREMENTS has both commands."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\ndependencies = ['pytest']\n")
        (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest"}}\n')

        rendered = _render_template("test_requirements_contributing", tmp_path)

        assert "Python" in rendered or "python" in rendered
        assert "Javascript" in rendered or "javascript" in rendered

    def test_dependency_tool_named(self, tmp_path):
        """Given a repo with Dependabot, DEPENDENCIES.md names it."""
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "dependabot.yml").touch()

        rendered = _render_template("dependency_management_template", tmp_path)

        assert "Dependabot" in rendered
        # Should not contain generic "Dependabot or Renovate"
        assert "Dependabot or Renovate" not in rendered

    def test_renovate_named(self, tmp_path):
        """Given a repo with Renovate, DEPENDENCIES.md names it."""
        (tmp_path / "renovate.json").touch()

        rendered = _render_template("dependency_management_template", tmp_path)

        assert "Renovate" in rendered


# =============================================================================
# T034: SAST/SCA policy e2e tests
# =============================================================================


class TestCIToolPolicyRendering:
    """Verify policy docs name specific CI tools."""

    def test_sast_names_codeql(self, tmp_path):
        """Given a repo with CodeQL workflow, SAST policy names CodeQL."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "sast.yml").write_text(
            "name: SAST\njobs:\n  analyze:\n    steps:\n"
            "      - uses: github/codeql-action/init@v3\n"
            "      - uses: github/codeql-action/analyze@v3\n"
        )

        rendered = _render_template("sast_policy_template", tmp_path)

        assert "CodeQL" in rendered

    def test_sca_names_dependency_review(self, tmp_path):
        """Given a repo with dependency-review, SCA policy names it."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "sca.yml").write_text(
            "name: SCA\njobs:\n  review:\n    steps:\n"
            "      - uses: actions/dependency-review-action@v4\n"
        )

        rendered = _render_template("sca_policy_template", tmp_path)

        assert "GitHub Dependency Review" in rendered

    def test_no_ci_graceful_degradation(self, tmp_path):
        """Given no CI workflows, policy docs still render without errors."""
        rendered = _render_template("sast_policy_template", tmp_path)

        # Should render successfully (empty ${scan.*} vars cleaned up)
        assert "SAST" in rendered or "Static" in rendered
        # Should not contain raw template variables
        assert "${scan." not in rendered

    def test_sast_without_a_detected_tool_does_not_claim_codeql(self, tmp_path):
        """SAST policy does not name CodeQL when no SAST action was detected."""
        rendered = _render_template("sast_policy_template", tmp_path)

        assert "CodeQL" not in rendered
        assert "No SAST tool was detected" in rendered

    def test_sca_without_a_detected_tool_does_not_claim_dependency_review(self, tmp_path):
        """SCA policy does not name GitHub Dependency Review when it was not detected."""
        rendered = _render_template("sca_policy_template", tmp_path)

        assert "GitHub Dependency Review" not in rendered
        assert "No SCA tool was detected" in rendered
        assert "Do not describe automated alerts as configured" in rendered

    def test_sast_yaml_workflow_label_matches_the_file(self, tmp_path):
        """A .yaml SAST workflow is labeled with .yaml, not a hardcoded .yml path."""
        workflow = tmp_path / ".github" / "workflows" / "sast.yaml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "name: SAST\njobs:\n  analyze:\n    steps:\n"
            "      - uses: github/codeql-action/analyze@v3\n"
        )

        rendered = _render_template("sast_policy_template", tmp_path)

        assert "CodeQL" in rendered
        assert ".github/workflows/sast.yaml" in rendered
        assert "sast.yml" not in rendered

    def test_sca_yaml_workflow_label_matches_the_file(self, tmp_path):
        """A .yaml SCA workflow is labeled with .yaml, not a hardcoded .yml path."""
        workflow = tmp_path / ".github" / "workflows" / "sca.yaml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "name: SCA\njobs:\n  review:\n    steps:\n"
            "      - uses: actions/dependency-review-action@v4\n"
        )

        rendered = _render_template("sca_policy_template", tmp_path)

        assert "GitHub Dependency Review" in rendered
        assert ".github/workflows/sca.yaml" in rendered
        assert "sca.yml" not in rendered


# =============================================================================
# T040: SUPPORT.md and GOVERNANCE.md cross-reference e2e tests
# =============================================================================


class TestDocCrossReferenceRendering:
    """Verify generated docs link to existing documentation."""

    def test_support_includes_canonical_doc_references(self, tmp_path):
        """SUPPORT.md links to a README that exists and does not invent the other files."""
        (tmp_path / "README.md").write_text("# My Project\n")

        rendered = _render_template("support_template", tmp_path)

        assert "[README](README.md)" in rendered
        assert "](docs/)" not in rendered
        assert not _links_to_file(rendered, "CONTRIBUTING.md")
        assert "TODO: No docs/ directory was found" in rendered
        assert "TODO: No CONTRIBUTING.md was found" in rendered

    def test_governance_includes_governance_context(self, tmp_path):
        """Given CONTRIBUTING.md with governance, GOVERNANCE.md references it."""
        (tmp_path / "CONTRIBUTING.md").write_text(
            "# Contributing\n\nThis project is governed by Acme Corp\n"
        )

        rendered = _render_template("governance_template", tmp_path)

        assert "governed by Acme Corp" in rendered

    def test_governance_links_code_of_conduct(self, tmp_path):
        """Given CODE_OF_CONDUCT.md exists, GOVERNANCE.md links to it."""
        (tmp_path / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\nBe nice.\n")

        rendered = _render_template("governance_template", tmp_path)

        assert "CODE_OF_CONDUCT.md" in rendered

    def test_governance_links_security_policy(self, tmp_path):
        """Given SECURITY.md exists, GOVERNANCE.md links to it."""
        (tmp_path / "SECURITY.md").write_text("# Security Policy\nReport bugs.\n")

        rendered = _render_template("governance_template", tmp_path)

        assert "SECURITY.md" in rendered

    def test_no_docs_graceful_degradation(self, tmp_path):
        """Given no existing docs, templates still render cleanly."""
        rendered = _render_template("support_template", tmp_path)

        # Should render without errors
        assert "Support" in rendered or "Getting Help" in rendered
        # Should not contain raw template variables
        assert "${scan." not in rendered

        rendered_gov = _render_template("governance_template", tmp_path)
        assert "Governance" in rendered_gov
        assert "${scan." not in rendered_gov


# =============================================================================
# T044/T045: LLM enhancement tests
# =============================================================================


class TestLLMEnhancement:
    """Verify LLM enhancement behavior."""

    def test_without_llm_still_has_real_paths(self, tmp_path):
        """enhance_with_llm=False produces ARCHITECTURE.md with real paths."""
        (tmp_path / "packages" / "core" / "src").mkdir(parents=True)
        (tmp_path / "packages" / "plugin" / "src").mkdir(parents=True)
        (tmp_path / "tests").mkdir()

        rendered = _render_template("architecture_template", tmp_path)

        # Real paths present
        assert "packages" in rendered
        assert "core" in rendered
        assert "plugin" in rendered
        # No fake paths
        assert "src/core/" not in rendered
        assert "src/api/" not in rendered

    def test_enhancer_with_mock_llm(self, tmp_path):
        """enhance_with_llm=True with mock LLM enriches ARCHITECTURE.md."""
        from darnit_baseline.remediation.enhancer import enhance_generated_file

        # Create a minimal architecture doc
        arch_content = (
            "# Architecture\n\n"
            "## Components\n\n"
            "| Component | Path |\n"
            "|-----------|------|\n"
            "| core | `packages/core/` |\n"
            "| plugin | `packages/plugin/` |\n"
        )
        arch_file = tmp_path / "ARCHITECTURE.md"
        arch_file.write_text(arch_content)

        # Create source files with docstrings
        pkg_dir = tmp_path / "packages" / "core"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text('"""Core framework for compliance auditing."""\n')

        # Mock LLM that adds descriptions
        def mock_llm(prompt):
            return (
                "# Architecture\n\n"
                "## Components\n\n"
                "| Component | Path | Description |\n"
                "|-----------|------|-------------|\n"
                "| core | `packages/core/` | Core framework for compliance auditing |\n"
                "| plugin | `packages/plugin/` | Plugin system for extensibility |\n"
            )

        result = enhance_generated_file(
            str(arch_file), str(tmp_path), "architecture", llm_fn=mock_llm
        )

        assert result is not None
        assert "Core framework for compliance auditing" in result
        assert "Plugin system for extensibility" in result

    def test_enhancer_without_llm_returns_none(self, tmp_path):
        """Without LLM available, enhancement returns None (no changes)."""
        from darnit_baseline.remediation.enhancer import enhance_generated_file

        arch_file = tmp_path / "ARCHITECTURE.md"
        arch_file.write_text("# Architecture\n\n## Components\n")

        result = enhance_generated_file(
            str(arch_file), str(tmp_path), "architecture", llm_fn=None
        )

        # No LLM available → returns None, original file unchanged
        assert result is None

    def test_is_enhanceable(self):
        """Verify file eligibility check."""
        from darnit_baseline.remediation.enhancer import is_enhanceable

        assert is_enhanceable("ARCHITECTURE.md") is True
        assert is_enhanceable("THREAT_MODEL.md") is True
        assert is_enhanceable("docs/SECURITY-ASSESSMENT.md") is True
        assert is_enhanceable("SUPPORT.md") is False
        assert is_enhanceable("LICENSE") is False
        assert is_enhanceable("CONTRIBUTING.md") is False


# =============================================================================
# Template fallback defaults tests
# =============================================================================


class TestTemplateFallbackDefaults:
    """Verify template text renders sensible defaults when context is missing.

    These render a template with no unconfirmed keys, so they cover the
    template text only. In a remediation run, a template that reads a
    defined key without a usable value (``maintainers``,
    ``security_contact`` before confirmation) is not rendered: the control
    stops with "confirmation required" (feature 042, FR-007; see
    tests/darnit/remediation/test_confirmation_required.py).
    """

    def test_security_policy_omits_email_when_no_contact(self, tmp_path):
        """Security policy omits the email option when no contact is confirmed.

        Regression guard: previously the template used
        ``default('security@example.com')`` which leaked a fake address into
        real SECURITY.md outputs, violating the "Never Guess User-Specific
        Values" rule.
        """
        rendered = _render_template("security_policy_standard", tmp_path)

        # No placeholder email leaks
        assert "security@example.com" not in rendered
        assert "example.com" not in rendered
        # No raw template variables
        assert "${context.security_contact}" not in rendered
        assert "<< context.security_contact" not in rendered
        # GitHub Security Advisories path is still present
        assert "GitHub Security Advisories" in rendered

    def test_security_policy_renders_contact_when_confirmed(self, tmp_path):
        """When context.security_contact is set, the email line is rendered verbatim."""
        scan_ctx = scan_repository(str(tmp_path))
        scan_values = flatten_scan_context(scan_ctx)

        fw_path = _get_framework_path()
        templates = _load_template("security_policy_standard")

        executor = RemediationExecutor(
            local_path=str(tmp_path),
            owner="test-org",
            repo="test-repo",
            templates=templates,
            context_values={"security_contact": "security@example-project.test"},
            scan_values=scan_values,
            framework_path=fw_path,
        )

        content = executor._get_template_content("security_policy_standard")
        assert content is not None
        rendered = executor._substitute(content, "OSPS-TEST-01")

        # The confirmed contact is rendered
        assert "security@example-project.test" in rendered
        # The email section appears
        assert "Email" in rendered
        # No fallback fake address
        assert "security@example.com" not in rendered

    def test_codeowners_fallback(self, tmp_path):
        """CODEOWNERS renders a valid placeholder when no maintainers set."""
        rendered = _render_template("codeowners_template", tmp_path)

        # Should contain a valid CODEOWNERS entry, not an empty "* "
        assert "@org/maintainers" in rendered
        assert "${context.maintainers}" not in rendered

    def test_maintainers_fallback(self, tmp_path):
        """MAINTAINERS.md renders a placeholder when no maintainers set."""
        rendered = _render_template("maintainers_template", tmp_path)

        assert "@username" in rendered
        assert "${context.maintainers}" not in rendered

    def test_governance_fallback_links(self, tmp_path):
        """Missing governance files are named in a TODO, not linked as if they exist."""
        rendered = _render_template("governance_template", tmp_path)

        assert "TODO: No CODE_OF_CONDUCT.md was found" in rendered
        assert "TODO: No SECURITY.md was found" in rendered
        assert "TODO: No MAINTAINERS.md was found" in rendered
        assert "TODO: No CODEOWNERS file was found" in rendered
        for filename in ("CODE_OF_CONDUCT.md", "SECURITY.md", "MAINTAINERS.md", "CODEOWNERS", "CONTRIBUTING.md"):
            assert not _links_to_file(rendered, filename)
        assert "${scan.code_of_conduct_link}" not in rendered
        assert "${scan.security_policy_link}" not in rendered
        assert "<< scan." not in rendered

    def test_architecture_fallback_hint(self, tmp_path):
        """Architecture renders a hint when no directory tree detected."""
        # Empty repo — no directories to detect
        rendered = _render_template("architecture_template", tmp_path)

        # Should not contain raw template variable
        assert "${scan.directory_tree}" not in rendered

    def test_test_requirements_fallback_commands(self, tmp_path):
        """Test requirements renders generic commands when no language detected."""
        rendered = _render_template("test_requirements_contributing", tmp_path)

        # Should not contain raw template variable
        assert "${scan.test_commands_all}" not in rendered
        # Should have some test command hint
        assert "test" in rendered.lower()


# =============================================================================
# Issue #751: do not invent test commands or links to missing files
# =============================================================================

# CONTRIBUTING.md and the Node testing document (docs/TESTING.md).
_JS_INSTRUCTION_TEMPLATES = ("contributing_standard", "testing_node")

# Runnable instructions these documents must not give when the repo has no
# test script. Generic prose such as "meaningful coverage" is not a command.
_INVENTED_JS_TEST_INSTRUCTIONS = (
    "make test",
    "npm test",
    "npm run test:coverage",
    "npm run test:watch",
    "npx jest",
    "Run with coverage",
    "Run in watch mode",
)

# Human-readable statement that the repository has no test command.
_NO_TEST_COMMAND_GAP = re.compile(
    r"no test command (?:was |has been )?found"
    r"|test command was not found"
    r"|no test command is (?:configured|defined|available)"
    r"|does not (?:define|include|have) a test command",
    re.IGNORECASE,
)

_VUE_VITE_SCRIPTS_WITHOUT_TESTS = {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
}

_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _write_vue_vite_package_json(root: Path, scripts: dict[str, str]) -> None:
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


def _links_to_file(rendered: str, filename: str) -> list[str]:
    """Return markdown link targets that point at ``filename``."""
    matches: list[str] = []
    for target in _MARKDOWN_LINK.findall(rendered):
        path = target.split("#", 1)[0].strip().replace("\\", "/")
        if path == filename or path.endswith("/" + filename):
            matches.append(target)
    return matches


class TestMissingCommandAndLinkAccuracy:
    """Issue #751: generated documents must not claim missing commands or files."""

    def test_vue_vite_without_tests_does_not_invent_test_commands(self, tmp_path):
        """CONTRIBUTING and Node testing state that no test command was found."""
        _write_vue_vite_package_json(tmp_path, dict(_VUE_VITE_SCRIPTS_WITHOUT_TESTS))

        failures: list[str] = []
        for template_name in _JS_INSTRUCTION_TEMPLATES:
            rendered = _render_template(template_name, tmp_path)
            problems: list[str] = []
            invented = [item for item in _INVENTED_JS_TEST_INSTRUCTIONS if item in rendered]
            if invented:
                problems.append(f"instructs commands that do not exist: {invented}")
            if _NO_TEST_COMMAND_GAP.search(rendered) is None:
                problems.append("does not state that no test command was found")
            if problems:
                failures.append(f"{template_name}: " + "; ".join(problems))
        assert not failures, "\n".join(failures)

    def test_vue_vite_with_test_script_includes_identified_command(self, tmp_path):
        """CONTRIBUTING and Node testing include the test command the scanner found."""
        _write_vue_vite_package_json(
            tmp_path,
            {**_VUE_VITE_SCRIPTS_WITHOUT_TESTS, "test": "vitest run"},
        )

        ctx = scan_repository(str(tmp_path))
        assert "javascript" in ctx.languages
        command = ctx.test_commands.get("javascript", "").strip()
        assert command, "scanner did not identify a test command"

        missing = [
            template_name
            for template_name in _JS_INSTRUCTION_TEMPLATES
            if command not in _render_template(template_name, tmp_path)
        ]
        assert missing == [], f"identified test command {command!r} is missing from {missing}"

    def test_governance_omits_links_to_missing_files(self, tmp_path):
        """GOVERNANCE.md does not link to MAINTAINERS, CODE_OF_CONDUCT, or CODEOWNERS."""
        assert not (tmp_path / "MAINTAINERS.md").exists()
        assert not (tmp_path / "CODE_OF_CONDUCT.md").exists()
        assert not (tmp_path / "CODEOWNERS").exists()
        assert not (tmp_path / ".github" / "CODEOWNERS").exists()

        rendered = _render_template("governance_template", tmp_path)
        linked = [
            filename
            for filename in ("MAINTAINERS.md", "CODE_OF_CONDUCT.md", "CODEOWNERS")
            if _links_to_file(rendered, filename)
        ]
        assert linked == [], f"GOVERNANCE.md links to missing files: {linked}"

    def test_dependencies_omits_link_to_missing_sca_workflow(self, tmp_path):
        """DEPENDENCIES.md does not link to a workflow the repository does not have."""
        workflow = tmp_path / ".github" / "workflows" / "sca.yml"
        assert not workflow.exists()

        rendered = _render_template("dependency_management_template", tmp_path)
        targets = _links_to_file(rendered, "sca.yml")
        assert targets == [], f"DEPENDENCIES.md links to missing workflow: {targets}"

    def test_sca_workflow_without_pull_request_does_not_claim_pr_review(self, tmp_path):
        """An SCA workflow that is not triggered by pull_request is not described as PR review."""
        workflow = tmp_path / ".github" / "workflows" / "sca.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "name: SCA\n"
            "on:\n"
            "  push:\n"
            "    branches: [main]\n"
            "jobs:\n"
            "  review:\n"
            "    steps:\n"
            "      - uses: actions/dependency-review-action@v4\n"
        )

        rendered = _render_template("dependency_management_template", tmp_path)

        assert _links_to_file(rendered, "sca.yml")
        assert "dependency scanning or review" in rendered
        assert "pull request dependency review" not in rendered

    def test_governance_links_files_that_exist(self, tmp_path):
        """GOVERNANCE.md links to maintainers, code owners, and the code of conduct when present."""
        (tmp_path / "MAINTAINERS.md").write_text("# Maintainers\n")
        (tmp_path / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n")
        (tmp_path / "CODEOWNERS").write_text("* @team\n")
        (tmp_path / "SECURITY.md").write_text("# Security\n")
        (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n")

        rendered = _render_template("governance_template", tmp_path)
        assert _links_to_file(rendered, "MAINTAINERS.md")
        assert _links_to_file(rendered, "CODE_OF_CONDUCT.md")
        assert _links_to_file(rendered, "CODEOWNERS")
        assert _links_to_file(rendered, "SECURITY.md")
        assert _links_to_file(rendered, "CONTRIBUTING.md")

    def test_governance_links_maintainers_scheduled_for_this_run(self, tmp_path):
        """A maintainers file this run will create is linked before it is on disk."""
        rendered = _render_template(
            "governance_template",
            tmp_path,
            scheduled_paths={"MAINTAINERS.md"},
        )
        assert _links_to_file(rendered, "MAINTAINERS.md")
        assert not _links_to_file(rendered, "CODEOWNERS")
        assert not (tmp_path / "MAINTAINERS.md").exists()

    def test_dependencies_links_existing_sca_workflow(self, tmp_path):
        """DEPENDENCIES.md links to sca.yml when that workflow is in the repository."""
        workflow = tmp_path / ".github" / "workflows" / "sca.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("name: SCA\n")
        (tmp_path / ".github" / "dependabot.yml").write_text("version: 2\n")

        rendered = _render_template("dependency_management_template", tmp_path)
        assert _links_to_file(rendered, "sca.yml") == ["../.github/workflows/sca.yml"]
        assert _links_to_file(rendered, "dependabot.yml") == ["../.github/dependabot.yml"]
        assert "Dependabot" in rendered

    def test_dependencies_links_renovate_config(self, tmp_path):
        """A Renovate repository links to renovate.json, not to a Dependabot file."""
        (tmp_path / "renovate.json").write_text("{}\n")

        rendered = _render_template("dependency_management_template", tmp_path)
        assert "Renovate" in rendered
        assert _links_to_file(rendered, "renovate.json") == ["../renovate.json"]
        assert not _links_to_file(rendered, "dependabot.yml")

    def test_node_template_includes_declared_coverage_and_watch(self, tmp_path):
        """Node testing docs include coverage and watch only when those scripts exist."""
        _write_vue_vite_package_json(
            tmp_path,
            {
                **_VUE_VITE_SCRIPTS_WITHOUT_TESTS,
                "test": "vitest run",
                "test:coverage": "vitest run --coverage",
                "test:watch": "vitest",
            },
        )

        rendered = _render_template("testing_node", tmp_path)
        assert "npm test" in rendered
        assert "npm run test:coverage" in rendered
        assert "npm run test:watch" in rendered
        assert "npx jest" not in rendered
        assert "No test command was found" not in rendered


_LOCAL_LINK_TEMPLATES = (
    "support_template",
    "support_scope_template",
    "readme_basic",
    "security_assessment_template",
)


class TestLocalDocumentLinks:
    """Issue #751: support, README, and security-assessment docs link only to real files."""

    def test_missing_local_targets_are_not_linked(self, tmp_path):
        """An empty repository does not get Markdown links to files or docs/."""
        for template_name in _LOCAL_LINK_TEMPLATES:
            rendered = _render_template(template_name, tmp_path)
            for filename in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE"):
                assert not _links_to_file(rendered, filename), template_name
            assert "](docs/)" not in rendered
            assert "](../SECURITY.md)" not in rendered
            assert "TODO:" in rendered

    def test_existing_local_targets_are_linked(self, tmp_path):
        """Files and docs/ that exist are linked, with a docs-relative security path."""
        (tmp_path / "README.md").write_text("# Project\n")
        (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n")
        (tmp_path / "SECURITY.md").write_text("# Security\n")
        (tmp_path / "LICENSE").write_text("MIT\n")
        (tmp_path / "docs").mkdir()

        support = _render_template("support_template", tmp_path)
        assert "[README](README.md)" in support
        assert "[docs/](docs/)" in support
        assert set(_links_to_file(support, "CONTRIBUTING.md")) == {"CONTRIBUTING.md"}
        assert set(_links_to_file(support, "SECURITY.md")) == {"SECURITY.md"}

        scope = _render_template("support_scope_template", tmp_path)
        assert set(_links_to_file(scope, "SECURITY.md")) == {"SECURITY.md"}

        readme = _render_template("readme_basic", tmp_path)
        assert "[docs/](docs/)" in readme
        assert set(_links_to_file(readme, "CONTRIBUTING.md")) == {"CONTRIBUTING.md"}
        assert set(_links_to_file(readme, "LICENSE")) == {"LICENSE"}

        assessment = _render_template("security_assessment_template", tmp_path)
        assert set(_links_to_file(assessment, "SECURITY.md")) == {"../SECURITY.md"}

    def test_security_policy_inside_docs_is_a_same_directory_link(self, tmp_path):
        """A security policy already under docs/ is not prefixed with ../docs/."""
        security = tmp_path / "docs" / "SECURITY.md"
        security.parent.mkdir()
        security.write_text("# Security\n")

        rendered = _render_template("security_assessment_template", tmp_path)
        assert _links_to_file(rendered, "SECURITY.md") == ["SECURITY.md"]

    def test_scheduled_security_and_docs_are_linked(self, tmp_path):
        """A file or docs entry this run will create may be linked before it exists."""
        support = _render_template("support_template", tmp_path, scheduled_paths={"SECURITY.md"})
        assert _links_to_file(support, "SECURITY.md") == ["SECURITY.md"]
        assert not (tmp_path / "SECURITY.md").exists()

        readme = _render_template("readme_basic", tmp_path, scheduled_paths={"docs/TESTING.md"})
        assert "[docs/](docs/)" in readme
        assert not (tmp_path / "docs").exists()


class TestCiAndPackageManagerClaims:
    """Generated docs claim CI tests and Node install commands only with evidence."""

    def _workflow(self, tmp_path, text: str) -> None:
        workflow = tmp_path / ".github" / "workflows" / "ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(text)

    def test_commented_npm_test_does_not_claim_pull_request_ci(self, tmp_path):
        self._workflow(
            tmp_path,
            "name: docs\non:\n  pull_request:\njobs:\n  build:\n    steps:\n"
            "      - run: echo hello\n# npm test\n",
        )

        rendered = _render_template("test_requirements_contributing", tmp_path)

        assert "Pull requests are tested in CI" not in rendered
        assert "No CI workflow that runs tests was found" in rendered

    def test_push_only_test_does_not_claim_pull_request_ci(self, tmp_path):
        self._workflow(
            tmp_path,
            "name: test\non:\n  push:\n    branches: [main]\njobs:\n  test:\n"
            "    steps:\n      - run: npm test\n",
        )

        rendered = _render_template("test_requirements_contributing", tmp_path)

        assert "Pull requests are tested in CI" not in rendered
        assert "no pull-request trigger was found" in rendered

    def test_pull_request_test_command_is_reported(self, tmp_path):
        self._workflow(
            tmp_path,
            "name: test\non: pull_request\njobs:\n  test:\n    steps:\n      - run: npm test\n",
        )

        rendered = _render_template("test_requirements_contributing", tmp_path)

        assert "Pull requests are tested in CI" in rendered

    def test_declared_pnpm_without_lockfile_installs_without_frozen_lockfile(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"packageManager": "pnpm@9.0.0", "scripts": {"test": "vitest run"}}\n'
        )

        rendered = _render_template("testing_node", tmp_path)

        assert "pnpm test" in rendered
        assert "pnpm install" in rendered
        assert "--frozen-lockfile" not in rendered
        assert "npm ci" not in rendered
        assert re.search(r"(?<!p)npm install", rendered) is None
