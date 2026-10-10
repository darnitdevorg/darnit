"""Tests for darnit.cli module."""

import json
import sys

import pytest

from darnit.cli import (
    create_parser,
    format_result_text,
    format_results_json,
    format_results_text,
    main,
)


def test_install_claude_creates_settings(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    exit_code = main(["install"])

    assert exit_code == 0

    settings_path = tmp_path / ".claude.json"
    assert settings_path.exists()

    data = json.loads(settings_path.read_text())
    assert "mcpServers" in data
    assert "darnit" in data["mcpServers"]
    assert data["mcpServers"]["darnit"]["command"] == "uvx"
    assert data["mcpServers"]["darnit"]["args"] == ["--from", "darnit-mcp", "darnit", "serve"]

    assert not any(
        record.levelname == "WARNING" and "deprecated" in record.message.lower() for record in caplog.records
    )

    # The install function emits via logger.info(...), so we need pytest's
    # logging-record capture (caplog), not its stderr-FD capture (capsys).
    # When another test installs a logging handler that intercepts records
    # before they reach the stderr FD, capsys sees nothing while caplog
    # still captures every record. See issue #248 for the full post-mortem.
    assert any("Installed darnit MCP server config" in record.message for record in caplog.records), (
        "expected install confirmation log message was not emitted"
    )


def test_install_claude_alias_emits_deprecation_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    exit_code = main(["install", "--client", "claude", "--mcp-only"])

    assert exit_code == 0
    assert (tmp_path / ".claude.json").exists()
    assert any(record.levelname == "WARNING" and "deprecated" in record.message.lower() for record in caplog.records)


def test_install_claude_desktop_uses_desktop_config(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setattr(sys, "platform", "win32")

    exit_code = main(["install", "--client", "claude-desktop", "--mcp-only", "--force"])

    assert exit_code == 0

    settings_path = tmp_path / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    assert settings_path.exists()
    data = json.loads(settings_path.read_text())
    assert "darnit" in data["mcpServers"]


def test_install_claude_code_project_writes_mcp_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    exit_code = main(["install", "--client", "claude-code", "--project", "--mcp-only"])

    assert exit_code == 0

    mcp_path = tmp_path / ".mcp.json"
    assert mcp_path.exists()
    data = json.loads(mcp_path.read_text())
    assert "darnit" in data["mcpServers"]


def test_install_project_warns_for_non_claude_code(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    exit_code = main(["install", "--client", "cursor", "--project", "--mcp-only", "--force"])

    assert exit_code == 0
    assert (tmp_path / ".cursor" / "mcp.json").exists()
    assert any(record.levelname == "WARNING" and "--project" in record.message for record in caplog.records)


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

    settings_path = tmp_path / ".claude.json"
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

    exit_code = main(["install", "--client", "claude-code", "--force"])

    assert exit_code == 0

    data = json.loads(settings_path.read_text())
    assert data["theme"] == "dark"
    assert "other" in data["mcpServers"]
    assert "darnit" in data["mcpServers"]


@pytest.mark.parametrize(
    ("frameworks", "expected"),
    [
        (["gittuf", "openssf-baseline", "reproducibility"], "openssf-baseline"),
        (["community-spec", "gittuf", "hello", "openssf-baseline"], "openssf-baseline"),
        (["gittuf"], "gittuf"),
        (["community-spec", "gittuf"], None),
    ],
)
def test_default_framework(frameworks, expected):
    from darnit.cli import _default_framework

    assert _default_framework(frameworks) == expected


def _serve_with(monkeypatch, frameworks):
    """Run `darnit serve` with a fake framework list; return (exit code, served names)."""
    served = []

    class _Server:
        def run(self):
            pass

    def fake_create_server(path, **kwargs):
        served.append(path)
        return _Server()

    monkeypatch.setattr("darnit.config.list_available_frameworks", lambda: list(frameworks))
    monkeypatch.setattr("darnit.config.resolve_framework_path", lambda name: name)
    monkeypatch.setattr("darnit.server.create_server", fake_create_server)
    return main(["serve"]), served


def test_serve_defaults_to_the_baseline_not_the_first_name(monkeypatch):
    code, served = _serve_with(monkeypatch, ["gittuf", "openssf-baseline", "reproducibility"])

    assert code == 0
    assert served == ["openssf-baseline"]


def test_serve_refuses_to_guess_between_other_frameworks(monkeypatch, caplog):
    code, served = _serve_with(monkeypatch, ["community-spec", "gittuf"])

    assert code == 1
    assert served == []
    assert any("--framework" in record.message for record in caplog.records)


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
        args = create_parser().parse_args(["audit", "-f", "openssf-baseline", "-t", "level:1", "-o", "json", "."])

        assert args.command == "audit"
        assert args.framework == "openssf-baseline"
        assert args.tags == ["level:1"]
        assert args.output == "json"
        assert args.repo_path == "."

    @pytest.mark.unit
    def test_plan_command_parses_include_and_exclude(self):
        """The plan command keeps include/exclude filter arguments."""
        args = create_parser().parse_args(["plan", "--include", "AC", "--exclude", "VM", "."])

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
        """format_results_json returns a valid payload with summary counts.

        Note: the audit pipeline emits ``"N/A"`` (with slash) for excluded
        controls; the pre-feature-022 code compared against ``"NA"`` (typo)
        and the ``na`` count was always 0. Feature 022's CheckStatus Literal
        surfaced the typo; the test now uses the correct wire value.
        """
        rendered = format_results_json(
            [
                {"id": "PASS-01", "status": "PASS", "details": "", "level": 1},
                {"id": "FAIL-01", "status": "FAIL", "details": "", "level": 1},
                {"id": "WARN-01", "status": "WARN", "details": "", "level": 1},
                {"id": "NA-01", "status": "N/A", "details": "", "level": 1},
                {
                    "id": "ERROR-01",
                    "status": "ERROR",
                    "details": "Command not found: zizmor",
                    "level": 1,
                    "error_class": "not_found",
                },
                {"id": "PENDING-01", "status": "PENDING", "pending": {"kind": "llm_judgment"}, "details": "", "level": 1},
            ],
            "openssf-baseline",
        )
        payload = json.loads(rendered)

        assert payload["framework"] == "openssf-baseline"
        assert len(payload["results"]) == 6
        assert payload["summary"] == {
            "total": 6,
            "pass": 1,
            "fail": 1,
            "warn": 1,
            "na": 1,
            "error": 1,
            "pending": 1,
        }
        assert payload["summary"]["error"] == 1
        assert payload["summary"]["pending"] == 1


@pytest.mark.unit
def test_audit_command_parses_show_all():
    """The audit command accepts --show-all."""
    args = create_parser().parse_args(["audit", "--show-all", "."])
    assert args.command == "audit"
    assert args.show_all is True


@pytest.mark.unit
def test_audit_show_all_defaults_false():
    """--show-all defaults to False."""
    args = create_parser().parse_args(["audit", "."])
    assert args.show_all is False


@pytest.mark.unit
def test_format_results_text_truncates_passes_by_default():
    """By default the passed section truncates past 10 with a hint."""
    results = [{"id": f"OSPS-X-{i:02d}", "status": "PASS", "details": "ok"} for i in range(15)]
    rendered = format_results_text(results, "openssf-baseline")
    assert "... and 5 more" in rendered
    assert "--show-all" in rendered


@pytest.mark.unit
def test_format_results_text_show_all_lists_every_check():
    """--show-all lists all passes (no truncation) and includes N/A checks."""
    results = [{"id": f"OSPS-X-{i:02d}", "status": "PASS", "details": "ok"} for i in range(15)]
    results.append({"id": "OSPS-NA-01.01", "status": "N/A", "details": "not applicable"})
    rendered = format_results_text(results, "openssf-baseline", show_all=True)
    assert "... and" not in rendered
    for i in range(15):
        assert f"OSPS-X-{i:02d}" in rendered
    assert "OSPS-NA-01.01" in rendered


def _mixed_results() -> list[dict]:
    """One result per CheckStatus, so no bucket can hide behind another."""
    return [
        {"id": "OSPS-PASS-01.01", "status": "PASS", "details": "satisfied", "level": 1},
        {"id": "OSPS-FAIL-01.01", "status": "FAIL", "details": "not satisfied", "level": 1},
        {"id": "OSPS-WARN-01.01", "status": "WARN", "details": "needs verification", "level": 1},
        {"id": "OSPS-NA-01.01", "status": "N/A", "details": "not applicable", "level": 1},
        {
            "id": "OSPS-BR-01.01",
            "status": "ERROR",
            "details": "Command not found: zizmor",
            "level": 1,
            "error_class": "not_found",
        },
        {
            "id": "OSPS-LLM-01.01",
            "status": "PENDING", "pending": {"kind": "llm_judgment"},
            "details": "Awaiting LLM analysis",
            "level": 1,
        },
    ]


@pytest.mark.unit
def test_format_results_text_shows_errors_without_show_all():
    """ERROR results are shown without --show-all."""
    rendered = format_results_text(_mixed_results(), "openssf-baseline")

    assert "--- Errors (1) ---" in rendered
    assert "OSPS-BR-01.01" in rendered
    assert "Command not found: zizmor" in rendered
    assert "[not_found]" in rendered


@pytest.mark.unit
def test_format_results_text_shows_pending_without_show_all():
    """PENDING results are shown without --show-all."""
    rendered = format_results_text(_mixed_results(), "openssf-baseline")

    assert "--- Pending (1) ---" in rendered
    assert "OSPS-LLM-01.01" in rendered
    assert "Awaiting LLM analysis" in rendered


@pytest.mark.unit
def test_format_results_text_summary_counts_account_for_total():
    """The summary includes every status count."""
    rendered = format_results_text(_mixed_results(), "openssf-baseline")

    assert "Total: 6 | Pass: 1 | Fail: 1 | Warn: 1 | N/A: 1 | Error: 1 | Pending: 1" in rendered


@pytest.mark.unit
def test_format_results_text_show_all_does_not_duplicate_sections():
    """--show-all does not duplicate ERROR or PENDING results."""
    rendered = format_results_text(_mixed_results(), "openssf-baseline", show_all=True)

    assert rendered.count("OSPS-BR-01.01") == 1
    assert rendered.count("OSPS-LLM-01.01") == 1
    assert rendered.count("--- Errors (1) ---") == 1
    assert rendered.count("--- Pending (1) ---") == 1
    assert "--- ERROR (" not in rendered
    assert "--- PENDING (" not in rendered
    assert "--- N/A (1) ---" in rendered
    assert rendered.count("OSPS-NA-01.01") == 1
