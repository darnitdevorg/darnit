"""End-to-end tests for context-aware template rendering.

These tests verify that the full pipeline (scan → flatten → substitute)
produces templates with real project data instead of generic placeholders.
"""

from __future__ import annotations

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
    template_name: str, tmp_path: Path, owner: str = "test-org", repo: str = "test-repo"
) -> str:
    """Scan a test repo and render a template with scan context.

    Returns the rendered template content.
    """
    scan_ctx = scan_repository(str(tmp_path))
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
        (tmp_path / "pyproject.toml").touch()
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
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "package.json").touch()

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


# =============================================================================
# T040: SUPPORT.md and GOVERNANCE.md cross-reference e2e tests
# =============================================================================


class TestDocCrossReferenceRendering:
    """Verify generated docs link to existing documentation."""

    def test_support_includes_canonical_doc_references(self, tmp_path):
        """SUPPORT.md links to canonical doc files (README, docs/, CONTRIBUTING)."""
        (tmp_path / "README.md").write_text("# My Project\n")

        rendered = _render_template("support_template", tmp_path)

        assert "[README](README.md)" in rendered
        assert "[docs/](docs/)" in rendered
        assert "[CONTRIBUTING](CONTRIBUTING.md)" in rendered

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
    """Verify templates render sensible defaults when context is missing."""

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

    def test_security_policy_minimal_omits_email_when_no_contact(self, tmp_path):
        """Minimal security policy omits the email bullet when no contact set."""
        rendered = _render_template("security_policy_minimal", tmp_path)

        assert "security@example.com" not in rendered
        assert "example.com" not in rendered
        assert "${context.security_contact}" not in rendered
        assert "<< context.security_contact" not in rendered
        # GitHub vulnerability reporting path is still present
        assert "Report a vulnerability" in rendered

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
        """Governance renders default links when scan context is empty."""
        rendered = _render_template("governance_template", tmp_path)

        # Should have fallback links, not raw variables
        assert "CODE_OF_CONDUCT.md" in rendered
        assert "SECURITY.md" in rendered
        assert "${scan.code_of_conduct_link}" not in rendered
        assert "${scan.security_policy_link}" not in rendered

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
