"""Remediation templates render strictly, and rendered YAML/JSON must parse (#152).

A name a template uses that does not exist used to render as an empty
string, and a rendered workflow file was written without checking it was
valid YAML. Both now stop the remediation while planning: the preview
reports the error and an apply writes nothing.

Absent ``scan.*`` and ``project.*`` keys mean "not detected", and a
``context.*`` key with no value means "not set"; templates test them with
``<% if scan.x %>`` or ``| default(...)``, and those still render. (A context
key that needs confirmation still stops the remediation; see
test_confirmation_required.py.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config.framework_schema import HandlerInvocation, RemediationConfig, TemplateConfig
from darnit.remediation.executor import RemediationExecutor


def _run(repo: Path, content: str, path: str = "OUT.md", *, dry_run: bool = False, scan: dict | None = None):
    executor = RemediationExecutor(
        local_path=str(repo),
        owner="example-org",
        repo="example",
        templates={"t": TemplateConfig(content=content)},
        scan_values=scan or {},
    )
    config = RemediationConfig(handlers=[HandlerInvocation(handler="file_create", path=path, template="t")])
    return executor.execute("C-1", config, dry_run=dry_run)


@pytest.mark.unit
class TestStrictNames:
    @pytest.mark.parametrize("dry_run", [True, False])
    def test_misspelled_top_level_name_stops_the_remediation(self, tmp_path: Path, dry_run: bool) -> None:
        result = _run(tmp_path, "# << REOP >>\n", dry_run=dry_run)
        assert not result.success
        assert result.message.startswith("template 't': uses an undefined variable")
        assert "REOP" in result.message
        assert result.details["template_error"]["template"] == "t"
        assert not (tmp_path / "OUT.md").exists()

    def test_misspelled_namespace_stops_the_remediation(self, tmp_path: Path) -> None:
        result = _run(tmp_path, "<< scna.test_command >>\n")
        assert not result.success
        assert "scna" in result.message

    def test_syntax_error_stops_the_remediation(self, tmp_path: Path) -> None:
        result = _run(tmp_path, "<% if REPO %>unterminated\n")
        assert not result.success
        assert "syntax error" in result.message
        assert not (tmp_path / "OUT.md").exists()

    def test_known_names_render(self, tmp_path: Path) -> None:
        result = _run(tmp_path, "<< OWNER >>/<< REPO >> on << BRANCH >>\n")
        assert result.success
        assert (tmp_path / "OUT.md").read_text() == "example-org/example on main\n"


@pytest.mark.unit
class TestDetectedValues:
    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("[<< scan.test_command >>]\n", "[]\n"),
            ("<% if scan.test_command %>yes<% else %>no<% endif %>\n", "no\n"),
            ("<< scan.directory_tree | default('none') >>\n", "none\n"),
            ("<% if scan.package_manager == 'uv' %>uv<% else %>other<% endif %>\n", "other\n"),
            ("[<< project.name >>]\n", "[]\n"),
            ("[<< scan['test_command'] >>]\n", "[]\n"),
            ("<% if context.security_contact %>contact<% else %>none<% endif %>\n", "none\n"),
            ("[<< context.not_declared >>]\n", "[]\n"),
            ("<< context.get('maintainers', '@org/maintainers') >>\n", "@org/maintainers\n"),
            ("<< scan.items() | list | length >>\n", "0\n"),
        ],
    )
    def test_absent_detected_value_is_empty(self, tmp_path: Path, content: str, expected: str) -> None:
        result = _run(tmp_path, content)
        assert result.success, result.message
        assert (tmp_path / "OUT.md").read_text() == expected

    def test_present_detected_value_renders(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            "<% if scan.test_command %><< scan.test_command >><% endif %>\n",
            scan={"scan.test_command": "pytest"},
        )
        assert result.success
        assert (tmp_path / "OUT.md").read_text() == "pytest\n"


@pytest.mark.unit
class TestStructuredOutput:
    WORKFLOW = "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ${{ github.sha }}\n"

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_invalid_yaml_stops_the_remediation(self, tmp_path: Path, dry_run: bool) -> None:
        result = _run(tmp_path, "name: ci\non: [push\n", path=".github/workflows/ci.yml", dry_run=dry_run)
        assert not result.success
        assert "rendered .github/workflows/ci.yml is not valid YAML" in result.message
        assert not (tmp_path / ".github" / "workflows" / "ci.yml").exists()

    def test_valid_yaml_with_actions_expressions_is_written(self, tmp_path: Path) -> None:
        result = _run(tmp_path, self.WORKFLOW, path=".github/workflows/ci.yaml")
        assert result.success, result.message
        assert (tmp_path / ".github" / "workflows" / "ci.yaml").read_text() == self.WORKFLOW

    def test_invalid_json_stops_the_remediation(self, tmp_path: Path) -> None:
        result = _run(tmp_path, '{"name": "<< REPO >>",}\n', path="renovate.json")
        assert not result.success
        assert "rendered renovate.json is not valid JSON" in result.message
        assert not (tmp_path / "renovate.json").exists()

    def test_valid_json_is_written(self, tmp_path: Path) -> None:
        result = _run(tmp_path, '{"name": "<< REPO >>"}\n', path="renovate.json")
        assert result.success
        assert (tmp_path / "renovate.json").read_text() == '{"name": "example"}\n'

    def test_markdown_is_not_parsed(self, tmp_path: Path) -> None:
        result = _run(tmp_path, "name: [unclosed\n", path="NOTES.md")
        assert result.success
