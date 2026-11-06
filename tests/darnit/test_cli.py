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
    assert data["mcpServers"]["darnit"]["args"] == [
        "--from",
        "darnit-mcp",
        "darnit",
        "serve",
        "--framework",
        "openssf-baseline",
    ]

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
        (["gittuf", "openssf-baseline", "amber"], "openssf-baseline"),
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
    code, served = _serve_with(monkeypatch, ["gittuf", "openssf-baseline", "amber"])

    assert code == 0
    assert served == ["openssf-baseline"]


def test_serve_refuses_to_guess_between_other_frameworks(monkeypatch, caplog):
    code, served = _serve_with(monkeypatch, ["community-spec", "gittuf"])

    assert code == 1
    assert served == []
    assert any("--framework" in record.message for record in caplog.records)


def test_install_from_source_registers_local_executable(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    exe_name = "darnit.exe" if sys.platform == "win32" else "darnit"
    (bin_dir / exe_name).write_text("")
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python"))

    exit_code = main(["install", "--mcp-only", "--from-source"])

    assert exit_code == 0
    entry = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]["darnit"]
    assert entry == {"command": str(bin_dir / exe_name), "args": ["serve", "--framework", "openssf-baseline"]}


def test_install_from_source_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    on_path = tmp_path / "onpath" / "darnit"
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setattr("shutil.which", lambda name: str(on_path) if name == "darnit" else None)

    exit_code = main(["install", "--mcp-only", "--from-source"])

    assert exit_code == 0
    entry = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]["darnit"]
    assert entry == {"command": str(on_path), "args": ["serve", "--framework", "openssf-baseline"]}


def test_install_from_source_fails_when_executable_is_missing(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setattr("shutil.which", lambda name: None)
    settings = tmp_path / ".claude.json"
    settings.write_text('{"mcpServers": {}}')

    exit_code = main(["install", "--mcp-only", "--from-source"])

    assert exit_code == 1
    assert settings.read_text() == '{"mcpServers": {}}'
    assert not settings.with_suffix(".json.bak").exists(), "a failed lookup must not write a backup"
    assert not (tmp_path / ".cursor").exists()
    assert any("--from-source" in record.message for record in caplog.records)


def _config(name="openssf-baseline"):
    from darnit.config import load_effective_config_by_name

    return load_effective_config_by_name(name)


def _controls(name="openssf-baseline"):
    from darnit.config import load_controls_from_effective

    return load_controls_from_effective(_config(name))


def _baseline_controls():
    return _controls()


def _planned_control_ids(caplog: pytest.LogCaptureFixture) -> set[str]:
    """Control IDs the plan command listed, one bullet per control."""
    prefix = "  • "
    found = set()
    for record in caplog.records:
        message = record.message
        if message.startswith(prefix) and ": " in message:
            found.add(message.removeprefix(prefix).split(": ", 1)[0])
    return found


def _run_plan(argv: list[str], caplog: pytest.LogCaptureFixture) -> tuple[int, set[str]]:
    import logging

    caplog.clear()
    with caplog.at_level(logging.INFO):
        code = main(argv)
    return code, _planned_control_ids(caplog)


def test_resolve_profile_ids_selects_the_profile_controls():
    from darnit.cli import _resolve_profile_ids

    controls = _baseline_controls()
    ids = _resolve_profile_ids("level1_quick", _config(), controls)

    assert ids == {c.control_id for c in controls if c.level == 1}
    assert 0 < len(ids) < len(controls)
    assert _resolve_profile_ids("openssf-baseline:level1_quick", _config(), controls) == ids


def test_resolve_profile_ids_reads_the_loaded_framework_config():
    """community-spec defines profiles in its TOML but ships no get_audit_profiles()."""
    from darnit.cli import _resolve_profile_ids

    controls = _controls("community-spec")
    ids = _resolve_profile_ids("required_files", _config("community-spec"), controls)

    assert ids is not None
    assert 0 < len(ids) <= len(controls)


def test_resolve_profile_ids_rejects_an_unknown_profile(caplog):
    from darnit.cli import _resolve_profile_ids

    assert _resolve_profile_ids("no-such-profile", _config(), _baseline_controls()) is None
    assert any("Cannot use profile" in record.message for record in caplog.records)


def test_resolve_profile_ids_rejects_a_framework_without_profiles(caplog):
    from darnit.cli import _resolve_profile_ids

    assert _resolve_profile_ids("level1_quick", _config("testchecks"), []) is None
    assert any("Cannot use profile" in record.message for record in caplog.records)


def test_audit_profile_narrows_the_controls_that_run(tmp_path, monkeypatch):
    """--profile reaches the control filter; before, the flag was parsed and ignored."""
    from darnit import filtering

    seen = {}
    real_filter = filtering.filter_controls

    def spy(controls, filters, include_ids, exclude_ids):
        seen["include_ids"] = include_ids
        return real_filter(controls, filters, include_ids, exclude_ids)

    def fake_audit(**kwargs):
        seen["audit"] = kwargs
        return [], {}

    monkeypatch.setattr("darnit.filtering.filter_controls", spy)
    monkeypatch.setattr("darnit.tools.audit.run_sieve_audit", fake_audit)
    code = main(["audit", "-f", "openssf-baseline", "--profile", "level1_quick", "--no-fail", str(tmp_path)])

    assert code == 0
    level1 = {c.control_id for c in _baseline_controls() if c.level == 1}
    assert seen["include_ids"] == level1
    assert {c.control_id for c in seen["audit"]["controls"]} == level1


def test_audit_profile_with_a_tag_that_leaves_nothing_fails(tmp_path, caplog):
    code = main(["audit", "-f", "openssf-baseline", "--profile", "level1_quick", "-t", "level=3", "--no-fail", str(tmp_path)])

    assert code == 1
    assert any("leave no controls" in record.message for record in caplog.records)


def test_plan_profile_shows_exactly_level1_quick_controls(tmp_path, caplog):
    """openssf-baseline --profile level1_quick lists that profile and nothing else."""
    from darnit.cli import _resolve_profile_ids

    controls = _baseline_controls()
    expected = {c.control_id for c in controls if c.level == 1}

    assert expected
    assert expected < {c.control_id for c in controls}
    assert _resolve_profile_ids("level1_quick", _config(), controls) == expected

    code, shown = _run_plan(
        ["plan", "-f", "openssf-baseline", "--profile", "level1_quick", str(tmp_path)],
        caplog,
    )

    assert code == 0
    assert shown == expected
    assert "OSPS-BR-02.01" not in shown


def test_plan_profile_shows_community_spec_required_files(tmp_path, caplog):
    """community-spec --profile required_files lists the profile's controls."""
    from darnit.cli import _resolve_profile_ids

    expected = {
        "CSL-01.01",
        "CSL-01.02",
        "CSL-02.01",
        "CSL-03.01",
        "CSL-04.01",
        "CSL-05.01",
    }
    resolved = _resolve_profile_ids("required_files", _config("community-spec"), _controls("community-spec"))
    assert resolved == expected

    code, shown = _run_plan(
        ["plan", "-f", "community-spec", "--profile", "required_files", str(tmp_path)],
        caplog,
    )

    assert code == 0
    assert shown == expected
    assert "CSL-06.01" not in shown


def test_plan_unknown_profile_fails(tmp_path, caplog):
    code, shown = _run_plan(
        ["plan", "-f", "openssf-baseline", "--profile", "no-such-profile", str(tmp_path)],
        caplog,
    )

    assert code == 1
    assert shown == set()
    assert any("Cannot use profile 'no-such-profile'" in record.message for record in caplog.records)


def test_plan_profile_unknown_to_the_loaded_framework_fails(tmp_path, caplog):
    code, shown = _run_plan(
        ["plan", "-f", "community-spec", "--profile", "openssf-baseline:level1_quick", str(tmp_path)],
        caplog,
    )

    assert code == 1
    assert shown == set()
    assert any("Cannot use profile" in record.message for record in caplog.records)


def test_plan_profile_that_selects_no_controls_fails(tmp_path, caplog):
    framework = tmp_path / "empty_profile.toml"
    framework.write_text(
        """[metadata]
name = "empty-profile"
display_name = "Empty Profile"
version = "0.1.0"
description = "A profile whose filters match nothing"

[audit_profiles.nothing]
description = "Matches no controls"
tags = { level = 9 }

[controls."EMP-01"]
name = "Present"
description = "A control the profile does not select"
level = 1
"""
    )

    code, shown = _run_plan(["plan", "-f", str(framework), "--profile", "nothing", str(tmp_path)], caplog)

    assert code == 1
    assert shown == set()
    assert any("selects no controls" in record.message for record in caplog.records)


def test_plan_profile_and_include_with_no_overlap_fails(tmp_path, caplog):
    code, shown = _run_plan(
        [
            "plan",
            "-f",
            "openssf-baseline",
            "--profile",
            "level1_quick",
            "--include",
            "OSPS-BR-02.01",
            str(tmp_path),
        ],
        caplog,
    )

    assert code == 1
    assert shown == set()
    assert any("no controls in common" in record.message for record in caplog.records)


def test_plan_profile_intersects_include(tmp_path, caplog):
    """--include keeps only the overlap with the profile."""
    code, shown = _run_plan(
        [
            "plan",
            "-f",
            "openssf-baseline",
            "--profile",
            "level1_quick",
            "--include",
            "OSPS-AC-01.01,OSPS-BR-02.01",
            str(tmp_path),
        ],
        caplog,
    )

    assert code == 0
    assert shown == {"OSPS-AC-01.01"}


def test_plan_profile_honors_exclude(tmp_path, caplog):
    expected = {c.control_id for c in _baseline_controls() if c.level == 1} - {"OSPS-AC-01.01"}

    code, shown = _run_plan(
        [
            "plan",
            "-f",
            "openssf-baseline",
            "--profile",
            "level1_quick",
            "--exclude",
            "OSPS-AC-01.01",
            str(tmp_path),
        ],
        caplog,
    )

    assert code == 0
    assert shown == expected


def test_plan_profile_honors_tags(tmp_path, caplog):
    expected = {c.control_id for c in _baseline_controls() if c.level == 1 and c.domain == "AC"}
    assert expected
    assert "OSPS-BR-01.01" not in expected

    code, shown = _run_plan(
        ["plan", "-f", "openssf-baseline", "--profile", "level1_quick", "-t", "domain=AC", str(tmp_path)],
        caplog,
    )

    assert code == 0
    assert shown == expected


def test_plan_profile_combines_include_exclude_and_tags(tmp_path, caplog):
    """Each filter removes a control the others would have kept."""
    code, shown = _run_plan(
        [
            "plan",
            "-f",
            "openssf-baseline",
            "--profile",
            "level1_quick",
            "--include",
            "OSPS-AC-01.01,OSPS-AC-03.01,OSPS-BR-01.01,OSPS-AC-04.01",
            "--exclude",
            "OSPS-AC-03.01",
            "-t",
            "domain=AC",
            str(tmp_path),
        ],
        caplog,
    )

    assert code == 0
    assert shown == {"OSPS-AC-01.01"}


def test_plan_profile_and_tag_that_leaves_nothing_fails(tmp_path, caplog):
    code, shown = _run_plan(
        ["plan", "-f", "openssf-baseline", "--profile", "level1_quick", "-t", "level=3", str(tmp_path)],
        caplog,
    )

    assert code == 1
    assert shown == set()
    assert any("leave no controls" in record.message for record in caplog.records)


def test_plan_profile_include_excluded_entirely_fails(tmp_path, caplog):
    code, shown = _run_plan(
        [
            "plan",
            "-f",
            "openssf-baseline",
            "--profile",
            "level1_quick",
            "--include",
            "OSPS-AC-01.01",
            "--exclude",
            "OSPS-AC-01.01",
            str(tmp_path),
        ],
        caplog,
    )

    assert code == 1
    assert shown == set()
    assert any("leave no controls" in record.message for record in caplog.records)


def test_plan_profile_includes_controls_with_no_level(tmp_path, caplog):
    """A profile can select a control that declares no maturity level."""
    framework = tmp_path / "unleveled.toml"
    framework.write_text(
        """[metadata]
name = "unleveled-profile"
display_name = "Unleveled Profile"
version = "0.1.0"
description = "Profile selects a control with no level"

[audit_profiles.only_unleveled]
description = "The control with no level"
controls = ["MIX-NONE"]

[controls."MIX-01"]
name = "LevelOne"
description = "Has a level"
level = 1

[controls."MIX-NONE"]
name = "Unleveled"
description = "Control without a level"
"""
    )

    code, shown = _run_plan(
        ["plan", "-f", str(framework), "--profile", "only_unleveled", str(tmp_path)],
        caplog,
    )

    assert code == 0
    assert shown == {"MIX-NONE"}
    assert "No level (1 controls):" in caplog.text
    assert "Level 1" not in caplog.text


def test_plan_without_profile_lists_controls_a_profile_would_omit(tmp_path, caplog):
    """Omitting --profile still plans the whole framework."""
    expected = {c.control_id for c in _baseline_controls()}

    code, shown = _run_plan(["plan", "-f", "openssf-baseline", str(tmp_path)], caplog)

    assert code == 0
    assert shown == expected
    assert "OSPS-AC-01.01" in shown
    assert "OSPS-BR-02.01" in shown


def test_profiles_command_lists_profiles_from_the_framework_config(caplog):
    code = main(["profiles", "--impl", "community-spec"])

    assert code == 0
    assert any("required_files" in record.message for record in caplog.records)


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
            "status": "PENDING",
            "pending": {"kind": "llm_judgment"},
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


@pytest.mark.unit
def test_validate_command_executes_on_all_shipped_frameworks():
    """`darnit validate` succeeds on every shipped framework TOML."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    shipped_tomls = sorted(repo_root.glob("packages/*/src/*/*.toml"))
    assert len(shipped_tomls) >= 6

    for toml_path in shipped_tomls:
        exit_code = main(["validate", str(toml_path)])
        assert exit_code == 0, f"Validation failed for {toml_path}"


@pytest.mark.unit
def test_plan_command_executes_on_all_shipped_frameworks(tmp_path):
    """`darnit plan` succeeds on all registered framework implementations."""
    from darnit.core.discovery import discover_implementations

    impls = discover_implementations()
    assert "openssf-baseline" in impls

    for name in sorted(impls):
        exit_code = main(["plan", "-f", name, str(tmp_path)])
        assert exit_code == 0, f"Plan failed for framework {name}"


@pytest.mark.unit
def test_validate_and_plan_sort_with_unleveled_controls_last(tmp_path, caplog):
    """Controls mixing int levels and None are sorted with None last without TypeError."""
    import logging

    framework_file = tmp_path / "mixed_levels.toml"
    framework_file.write_text(
        """[metadata]
name = "mixed-levels"
display_name = "Mixed Levels"
version = "0.1.0"
description = "Test framework with mixed levels"

[controls."MIX-01"]
name = "LevelOne"
description = "First level control"
level = 1

[controls."MIX-02"]
name = "LevelTwo"
description = "Second level control"
tags = { level = 2 }

[controls."MIX-NONE"]
name = "Unleveled"
description = "Control without a level"
"""
    )

    with caplog.at_level(logging.INFO):
        exit_code = main(["validate", str(framework_file)])
    assert exit_code == 0
    assert "L1=1, L2=1, none=1" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO):
        plan_exit = main(["plan", "-f", str(framework_file), str(tmp_path)])
    assert plan_exit == 0
    assert "Level 1 (1 controls):" in caplog.text
    assert "Level 2 (1 controls):" in caplog.text
    assert "No level (1 controls):" in caplog.text

    idx_l1 = caplog.text.index("Level 1")
    idx_l2 = caplog.text.index("Level 2")
    idx_none = caplog.text.index("No level")
    assert idx_l1 < idx_l2 < idx_none
