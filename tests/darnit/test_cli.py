"""Tests for darnit.cli module."""

import json

import pytest

from darnit.cli import create_parser, format_result_text, format_results_json, main


def test_install_claude_creates_settings(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    exit_code = main(["install"])

    assert exit_code == 0

    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.exists()

    data = json.loads(settings_path.read_text())
    assert "mcpServers" in data
    assert "darnit" in data["mcpServers"]
    assert data["mcpServers"]["darnit"]["command"] == "uvx"
    assert data["mcpServers"]["darnit"]["args"] == ["--from", "darnit", "darnit", "serve"]

    captured = capsys.readouterr()
    assert "Installed darnit MCP server config" in captured.out

def test_install_cursor_creates_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    exit_code = main(["install", "--client", "cursor"])

    assert exit_code == 0

    settings_path = tmp_path / ".cursor" / "mcp.json"
    assert settings_path.exists()

    data = json.loads(settings_path.read_text())
    assert "darnit" in data["mcpServers"]

def test_install_preserves_existing_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcpServers": {
                    "other": {
                        "command": "example",
                        "args": ["serve"],
                    }
                },
            }
        )
    )

    exit_code = main(["install", "--force"])

    assert exit_code == 0

    data = json.loads(settings_path.read_text())
    assert data["theme"] == "dark"
    assert "other" in data["mcpServers"]
    assert "darnit" in data["mcpServers"]


class TestCreateParser:
    """Tests for CLI argument parsing."""

    @pytest.mark.unit
    def test_audit_command_parses_repo_path(self):
        """The audit command accepts a repository path positional argument."""
        args = create_parser().parse_args(["audit", "."])

        assert args.command == "audit"
        assert args.repo_path == "."

    @pytest.mark.unit
    def test_serve_command_parses_without_config(self):
        """The serve command parses with default optional arguments."""
        args = create_parser().parse_args(["serve"])

        assert args.command == "serve"
        assert args.config is None
        assert args.framework is None

    @pytest.mark.unit
    def test_validate_command_parses_framework_path(self):
        """The validate command requires a framework path argument."""
        args = create_parser().parse_args(["validate", "path/to/config.toml"])

        assert args.command == "validate"
        assert args.framework_path == "path/to/config.toml"

    @pytest.mark.unit
    def test_audit_command_parses_flags(self):
        """The audit command keeps framework, tag, and output flags."""
        args = create_parser().parse_args(
            ["audit", "-f", "openssf-baseline", "-t", "level:1", "-o", "json", "."]
        )

        assert args.command == "audit"
        assert args.framework == "openssf-baseline"
        assert args.tags == ["level:1"]
        assert args.output == "json"
        assert args.repo_path == "."

    @pytest.mark.unit
    def test_plan_command_parses_include_and_exclude(self):
        """The plan command keeps include/exclude filter arguments."""
        args = create_parser().parse_args(
            ["plan", "--include", "AC", "--exclude", "VM", "."]
        )

        assert args.command == "plan"
        assert args.include == "AC"
        assert args.exclude == "VM"
        assert args.repo_path == "."

    @pytest.mark.unit
    def test_main_without_subcommand_prints_help_and_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        """Running with no subcommand prints help instead of failing."""
        monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)

        exit_code = main([])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "usage:" in captured.out
        assert "Declarative compliance auditing for software projects" in captured.out


    @pytest.mark.unit
    def test_audit_command_parses_profile_flag(self):
        """The audit command accepts --profile flag."""
        args = create_parser().parse_args(["audit", "--profile", "level1_quick", "."])

        assert args.command == "audit"
        assert args.profile == "level1_quick"

    @pytest.mark.unit
    def test_audit_command_parses_profile_short_flag(self):
        """The audit command accepts -p short flag for profile."""
        args = create_parser().parse_args(["audit", "-p", "access_control", "."])

        assert args.profile == "access_control"

    @pytest.mark.unit
    def test_plan_command_parses_profile_flag(self):
        """The plan command accepts --profile flag."""
        args = create_parser().parse_args(["plan", "--profile", "security_critical", "."])

        assert args.command == "plan"
        assert args.profile == "security_critical"

    @pytest.mark.unit
    def test_profiles_command_parses(self):
        """The profiles command parses without arguments."""
        args = create_parser().parse_args(["profiles"])

        assert args.command == "profiles"

    @pytest.mark.unit
    def test_profiles_command_parses_impl_flag(self):
        """The profiles command accepts --impl flag."""
        args = create_parser().parse_args(["profiles", "--impl", "openssf-baseline"])

        assert args.command == "profiles"
        assert args.impl == "openssf-baseline"


class TestFormatting:
    """Tests for CLI output formatting helpers."""

    @pytest.mark.unit
    def test_format_result_text_includes_control_id(self):
        """A formatted result line includes the control ID and details."""
        rendered = format_result_text(
            {
                "id": "OSPS-AC-01.01",
                "status": "PASS",
                "details": "Control satisfied",
            }
        )

        assert "OSPS-AC-01.01" in rendered
        assert "PASS" in rendered
        assert "Control satisfied" in rendered

    @pytest.mark.unit
    def test_format_results_json_returns_valid_json(self):
        """format_results_json returns a valid payload with summary counts."""
        rendered = format_results_json(
            [
                {"id": "PASS-01", "status": "PASS"},
                {"id": "FAIL-01", "status": "FAIL"},
                {"id": "WARN-01", "status": "WARN"},
                {"id": "NA-01", "status": "NA"},
            ],
            "openssf-baseline",
        )
        payload = json.loads(rendered)

        assert payload["framework"] == "openssf-baseline"
        assert len(payload["results"]) == 4
        assert payload["summary"] == {
            "total": 4,
            "pass": 1,
            "fail": 1,
            "warn": 1,
            "na": 1,
        }
