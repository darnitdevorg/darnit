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


def _baseline_controls():
    from darnit.config import load_controls_from_effective, load_effective_config_by_name

    return load_controls_from_effective(load_effective_config_by_name("openssf-baseline"))


def test_resolve_profile_ids_selects_the_profile_controls():
    from darnit.cli import _resolve_profile_ids

    controls = _baseline_controls()
    ids = _resolve_profile_ids("level1_quick", "openssf-baseline", controls)

    assert ids == {c.control_id for c in controls if c.level == 1}
    assert 0 < len(ids) < len(controls)
    assert _resolve_profile_ids("openssf-baseline:level1_quick", "openssf-baseline", controls) == ids


def test_resolve_profile_ids_rejects_an_unknown_profile(caplog):
    from darnit.cli import _resolve_profile_ids

    assert _resolve_profile_ids("no-such-profile", "openssf-baseline", _baseline_controls()) is None
    assert any("Cannot use profile" in record.message for record in caplog.records)


def test_resolve_profile_ids_rejects_a_framework_without_profiles(caplog):
    from darnit.cli import _resolve_profile_ids

    assert _resolve_profile_ids("level1_quick", "testchecks", []) is None
    assert any("Cannot use profile" in record.message for record in caplog.records)


def test_audit_profile_narrows_the_controls_that_run(tmp_path, monkeypatch):
    """--profile reaches the control filter; before, the flag was parsed and ignored."""
    seen = {}

    def spy(controls, filters, include_ids, exclude_ids):
        seen["include_ids"] = include_ids
        return []

    monkeypatch.setattr("darnit.filtering.filter_controls", spy)
    try:
        main(["audit", "-f", "openssf-baseline", "--profile", "level1_quick", "--no-fail", str(tmp_path)])
    except Exception:
        pass

    assert seen["include_ids"] == {c.control_id for c in _baseline_controls() if c.level == 1}


def test_audit_with_an_unknown_profile_fails_before_running(tmp_path):
    assert main(["audit", "-f", "openssf-baseline", "--profile", "no-such-profile", "--no-fail", str(tmp_path)]) == 1


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
