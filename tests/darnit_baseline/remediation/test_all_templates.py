"""Comprehensive parametrized rendering tests for all darnit-baseline templates.

T050: All templates render without error and have no unresolved placeholders.
T051: YAML templates produce parseable YAML after rendering.
T052: GitHub Actions ${{ }} expressions survive substitution intact.

Covers the 52 templates defined in openssf-baseline.toml with a realistic
repository context (CI workflows, Dependabot, Python project, common doc files).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

from darnit.config.framework_schema import TemplateConfig
from darnit.remediation.executor import RemediationExecutor
from darnit_baseline.remediation.scanner import flatten_scan_context, scan_repository

# ---------------------------------------------------------------------------
# Template categorisation
# ---------------------------------------------------------------------------

WORKFLOW_TEMPLATES = [
    "ci_go_workflow",
    "ci_node_workflow",
    "ci_python_workflow",
    "ci_rust_workflow",
    "ci_test_workflow",
    "release_signing_workflow",
    "sast_workflow",
    "sbom_workflow",
    "sca_workflow",
]

YAML_TEMPLATES = WORKFLOW_TEMPLATES + [
    "allow_forking_payload",
    "branch_deletion_protection_payload",
    "branch_protection_payload",
    "dependabot_config",
    "dependabot_go",
    "dependabot_node",
    "dependabot_python",
    "dependabot_rust",
    "mfa_enforcement_payload",
    "pr_review_payload",
    "repo_visibility_payload",
]

DOCUMENTATION_TEMPLATES = [
    "api_documentation_template",
    "architecture_template",
    "bug_report_template",
    "codeowners_template",
    "contributing_standard",
    "dependency_management_template",
    "end_of_support_template",
    "governance_template",
    "maintainers_template",
    "readme_basic",
    "release_verification_template",
    "sast_policy_template",
    "sca_policy_template",
    "secrets_management_policy",
    "security_assessment_template",
    "security_policy_minimal",
    "security_policy_standard",
    "support_scope_template",
    "support_template",
    "test_requirements_contributing",
    "testing_go",
    "testing_instructions",
    "testing_node",
    "testing_python",
    "testing_rust",
    "threat_model_basic",
    "vex_policy_template",
]

ALL_TEMPLATES = YAML_TEMPLATES + DOCUMENTATION_TEMPLATES + [
    "gitignore_secrets",
    "license_apache",
    "license_bsd3",
    "license_mit",
    "vulnerability_reporting_payload",
]

# ---------------------------------------------------------------------------
# Helpers (independent copies; not imported from test_template_rendering to
# keep the two files decoupled)
# ---------------------------------------------------------------------------


def _get_framework_path() -> str:
    from darnit_baseline import get_framework_path

    p = get_framework_path()
    assert p is not None, "Framework path not found"
    return str(p)


def _load_template(template_name: str) -> dict[str, TemplateConfig]:
    fw_path = _get_framework_path()
    with open(fw_path, "rb") as f:
        config = tomllib.load(f)
    tmpl_data = config.get("templates", {}).get(template_name)
    if not tmpl_data:
        pytest.skip(f"Template '{template_name}' not in framework TOML")
    return {template_name: TemplateConfig(**tmpl_data)}


def _render_template(template_name: str, repo: Path) -> str:
    scan_ctx = scan_repository(str(repo))
    scan_values = flatten_scan_context(scan_ctx)
    fw_path = _get_framework_path()
    templates = _load_template(template_name)
    executor = RemediationExecutor(
        local_path=str(repo),
        owner="test-org",
        repo="test-repo",
        templates=templates,
        scan_values=scan_values,
        framework_path=fw_path,
    )
    content = executor._get_template_content(template_name)
    assert content is not None, f"Template '{template_name}' content is None"
    return executor._substitute(content, "T050-01")


def _get_raw_template(template_name: str) -> str | None:
    """Return the un-rendered template file content, or None if unresolvable."""
    fw_path = _get_framework_path()
    with open(fw_path, "rb") as f:
        config = tomllib.load(f)
    tmpl_data = config.get("templates", {}).get(template_name)
    if not tmpl_data:
        return None
    file_field = tmpl_data.get("file")
    if not file_field:
        return tmpl_data.get("content")
    template_path = Path(fw_path).parent / file_field
    return template_path.read_text() if template_path.exists() else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def rich_repo(tmp_path: Path) -> Path:
    """Realistic repository structure that exercises most scan-context branches."""
    (tmp_path / "README.md").write_text("# Test Project\n")
    (tmp_path / "CONTRIBUTING.md").write_text(
        "# Contributing\n\nThis project is governed by Test Org.\n"
    )
    (tmp_path / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n")
    (tmp_path / "SECURITY.md").write_text("# Security Policy\n")
    (tmp_path / "LICENSE").write_text("Apache-2.0\n")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'test'\nversion = '0.1.0'\n"
    )
    (tmp_path / "uv.lock").touch()

    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "sast.yml").write_text(
        "name: SAST\njobs:\n  analyze:\n    steps:\n"
        "      - uses: github/codeql-action/init@v3\n"
        "      - uses: github/codeql-action/analyze@v3\n"
    )
    (wf_dir / "dependency-review.yml").write_text(
        "name: SCA\njobs:\n  review:\n    steps:\n"
        "      - uses: actions/dependency-review-action@v4\n"
    )
    (tmp_path / ".github" / "dependabot.yml").write_text(
        "version: 2\nupdates:\n  - package-ecosystem: pip\n    directory: /\n"
    )

    (tmp_path / "packages" / "core" / "src").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# T050: All templates render without error
# ---------------------------------------------------------------------------


class TestAllTemplatesRender:
    """T050 — Every template renders without raising an error."""

    @pytest.mark.parametrize("template_name", ALL_TEMPLATES)
    def test_renders_without_error(self, template_name: str, rich_repo: Path) -> None:
        rendered = _render_template(template_name, rich_repo)
        assert rendered is not None

    @pytest.mark.parametrize("template_name", ALL_TEMPLATES)
    def test_no_unresolved_dollar_brace_placeholders(
        self, template_name: str, rich_repo: Path
    ) -> None:
        """Old-style ${...} patterns must not appear after rendering.

        GHA ${{ }} expressions are stripped before the check so they are never
        incorrectly flagged as unresolved placeholders.
        """
        rendered = _render_template(template_name, rich_repo)
        cleaned = re.sub(r"\$\{\{.*?\}\}", "", rendered, flags=re.DOTALL)
        leaks = re.findall(r"\$\{[^}]+\}", cleaned)
        assert not leaks, (
            f"Unresolved old-style placeholder(s) in '{template_name}': {leaks}"
        )

    @pytest.mark.parametrize("template_name", ALL_TEMPLATES)
    def test_no_unrendered_jinja_variables(
        self, template_name: str, rich_repo: Path
    ) -> None:
        """Jinja2 << identifier >> delimiters must not survive into rendered output."""
        rendered = _render_template(template_name, rich_repo)
        leaks = re.findall(r"<<\s+[\w][\w.]*\s+>>", rendered)
        assert not leaks, (
            f"Unrendered Jinja2 variable(s) in '{template_name}': {leaks}"
        )


# ---------------------------------------------------------------------------
# T051: YAML templates produce valid YAML
# ---------------------------------------------------------------------------


class TestYAMLTemplatesProduceValidYAML:
    """T051 — YAML templates produce parseable YAML after rendering."""

    @pytest.mark.parametrize("template_name", YAML_TEMPLATES)
    def test_yaml_parses_cleanly(self, template_name: str, rich_repo: Path) -> None:
        rendered = _render_template(template_name, rich_repo)
        try:
            parsed = yaml.safe_load(rendered)
        except yaml.YAMLError as exc:
            pytest.fail(
                f"Template '{template_name}' produced invalid YAML: {exc}\n\n"
                f"Rendered:\n{rendered}"
            )
        if template_name in WORKFLOW_TEMPLATES:
            assert parsed is not None, (
                f"Workflow template '{template_name}' parsed to None"
            )


# ---------------------------------------------------------------------------
# T052: GitHub Actions expressions survive substitution
# ---------------------------------------------------------------------------


class TestWorkflowGHAExpressionsPreserved:
    """T052 — ${{ }} expressions in workflow templates survive substitution."""

    @pytest.mark.parametrize("template_name", WORKFLOW_TEMPLATES)
    def test_gha_expressions_intact(self, template_name: str, rich_repo: Path) -> None:
        raw = _get_raw_template(template_name)
        if raw is None:
            pytest.skip(f"Could not read raw template '{template_name}'")
        gha_exprs = re.findall(r"\$\{\{[^}]+\}\}", raw)
        if not gha_exprs:
            pytest.skip(f"Template '{template_name}' contains no GHA expressions")
        rendered = _render_template(template_name, rich_repo)
        for expr in gha_exprs:
            assert expr in rendered, (
                f"GHA expression {expr!r} was mangled in '{template_name}'"
            )
