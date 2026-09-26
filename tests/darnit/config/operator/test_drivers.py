"""Driver wiring for operator configuration: CLI flags, config show, serve, harness, install (T020-T027)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from darnit.cli import create_parser
from darnit.cli import main as cli_main
from darnit.config.operator import loader
from darnit.config.operator.loader import get_launch_options, load_operator_config


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.unit
@pytest.mark.parametrize("command", ["audit", "run", "harness", "serve"])
def test_operator_config_flags_on_every_driver(command: str) -> None:
    argv = [command, "--operator-config", "/cfg.toml", "--strict-operator-config"]
    if command in ("harness",):
        argv.insert(1, ".")
    args = create_parser().parse_args(argv)
    assert args.operator_config == "/cfg.toml"
    assert args.strict_operator_config is True


@pytest.mark.unit
def test_serve_keeps_positional_framework_config_distinct() -> None:
    args = create_parser().parse_args(["serve", "framework.toml", "--operator-config", "/op.toml"])
    assert args.config == "framework.toml"
    assert args.operator_config == "/op.toml"


@pytest.mark.unit
def test_config_show_reports_source_digest_and_redacts_env(tmp_path: Path, capsys) -> None:
    cfg = _write(
        tmp_path / "op" / "config.toml",
        """schema_version = 1

[mcp_servers.scanner]
command = ["scanner-mcp", "--stdio"]
env = { SCANNER_TOKEN = "$SCANNER_TOKEN", LITERAL = "sk-not-a-reference" }

[llm]
model = "claude-sonnet-5"
""",
    )

    assert cli_main(["config", "show", "--operator-config", str(cfg)]) == 0
    out = capsys.readouterr().out

    assert str(cfg.resolve()) in out
    assert hashlib.sha256(cfg.read_bytes()).hexdigest() in out
    assert "permission check: passed" in out
    assert '"$SCANNER_TOKEN"' in out
    assert "[redacted]" in out
    assert "sk-not-a-reference" not in out
    assert "claude-sonnet-5" in out


@pytest.mark.unit
def test_config_show_without_file_reports_builtin_defaults(capsys) -> None:
    assert cli_main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert "builtin-defaults" in out
    assert str(loader.user_config_dir() / "config.toml") in out


@pytest.mark.unit
def test_config_show_missing_explicit_path_fails(tmp_path: Path, caplog) -> None:
    assert cli_main(["config", "show", "--operator-config", str(tmp_path / "nope.toml")]) != 0
    assert any("not found" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_invalid_operator_config_stops_the_audit(tmp_path: Path, caplog) -> None:
    cfg = _write(tmp_path / "op.toml", "schema_version = 1\n[plugins]\nunknown = true\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    assert cli_main(["audit", str(repo), "--operator-config", str(cfg)]) != 0
    assert any("plugins.unknown" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_create_server_records_launch_options(tmp_path: Path) -> None:
    from darnit.config.merger import resolve_framework_path
    from darnit.server.factory import create_server

    cfg = _write(tmp_path / "op.toml", "schema_version = 1\n")
    create_server(resolve_framework_path("openssf-baseline"), operator_config_path=cfg, strict_operator_config=True)

    assert get_launch_options() == loader.LaunchOptions(path=str(cfg), strict=True)


@pytest.mark.unit
def test_registration_scope_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from darnit.server.factory import registration_scope_warning

    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

    monkeypatch.chdir(elsewhere)
    assert registration_scope_warning(str(repo)) is None

    monkeypatch.chdir(repo / "sub")
    assert "user scope" in registration_scope_warning(str(repo))

    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert "user scope" in registration_scope_warning(str(repo))


@pytest.mark.unit
def test_install_project_scope_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")

    assert cli_main(["install", "--client", "claude-code", "--project", "--mcp-only", "--force"]) == 0

    assert json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]["darnit"]
    assert any(r.levelname == "WARNING" and "user scope" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_install_defaults_to_user_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")

    assert cli_main(["install", "--client", "claude-code", "--mcp-only", "--force"]) == 0

    assert (tmp_path / "home" / ".claude.json").exists()
    assert not (tmp_path / ".mcp.json").exists()


class TestHarnessLlmSettings:
    def _run(self, tmp_path: Path, llm: str):
        from darnit.core.llm_step import PydanticAILLMStep
        from darnit.harness.driver import HarnessRun

        cfg = _write(tmp_path / "op.toml", f"schema_version = 1\n[llm]\n{llm}\n")
        return HarnessRun(
            local_path=str(tmp_path),
            llm_step=PydanticAILLMStep(),
            operator_config=load_operator_config(cfg),
        )

    @pytest.mark.unit
    def test_model_from_operator_config(self, tmp_path: Path) -> None:
        run = self._run(tmp_path, 'provider = "anthropic"\nmodel = "claude-opus-5"')
        run._apply_operator_llm_settings()
        assert run.llm_step.model == "anthropic:claude-opus-5"
        assert run.llm_provider == "anthropic:claude-opus-5"

    @pytest.mark.unit
    def test_unsupported_provider_is_a_setup_error(self, tmp_path: Path) -> None:
        from darnit.harness.driver import HarnessSetupError

        run = self._run(tmp_path, 'provider = "other"\nmodel = "m"')
        with pytest.raises(HarnessSetupError, match="llm.provider"):
            run._apply_operator_llm_settings()
