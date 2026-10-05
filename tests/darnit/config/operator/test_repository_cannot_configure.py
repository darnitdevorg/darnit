"""Tool settings planted in the audited repository have no effect (SC-001, T015).

Every file an audited repository can use to try to configure darnit is
planted with settings whose effect is observable (a command that writes a
marker file, an MCP server whose launch writes a marker file). The audit runs
through the real entry points and must neither run those commands nor spawn
those servers, and must list each ignored setting with its new home.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from darnit.cli import main as cli_main

CONTROL = "OSPS-DO-01.01"
SERVER_CONTROL = "OSPS-DO-02.01"
OPERATOR_HOME = "operator configuration"


def _exec_pass(marker: Path) -> str:
    return f'{{ handler = "exec", command = ["touch", "{marker}"] }}'


@pytest.fixture
def markers(tmp_path: Path) -> Path:
    path = tmp_path / "markers"
    path.mkdir()
    return path


@pytest.fixture
def planted_repo(tmp_path: Path, markers: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Planted\n\nA project used to plant tool settings.\n", encoding="utf-8")

    (repo / ".baseline.toml").write_text(
        f"""
extends = "../elsewhere/framework.toml"

[plugins]
allow_unsigned = true

[adapters.planted]
type = "command"
command = "touch"

[mcp_servers.planted]
command = ["touch", "{markers / "mcp-spawned"}"]

[stores.report]
backend = "filesystem"

[controls."{CONTROL}"]
passes = [{_exec_pass(markers / "baseline-pass")}]

[controls."PLANTED-01"]
name = "Planted"
description = "Planted control"
level = 1
domain = "DO"
passes = [{_exec_pass(markers / "custom-control")}]
""",
        encoding="utf-8",
    )

    operator_shaped = f"""schema_version = 1

[controls."{CONTROL}"]
passes = [{_exec_pass(markers / "operator-shaped")}]

[trust]
repos = ["github.com/planted/repo"]
"""
    (repo / ".darnit").mkdir()
    (repo / ".darnit" / "config.toml").write_text(operator_shaped, encoding="utf-8")
    (repo / "darnit.toml").write_text(operator_shaped, encoding="utf-8")

    (repo / ".project").mkdir()
    (repo / ".project" / "darnit.yaml").write_text(
        f"""mcp_servers:
  planted:
    command: ["touch", "{markers / "project-mcp"}"]
llm:
  max_cost_usd_per_run: 1000
""",
        encoding="utf-8",
    )
    return repo


@pytest.fixture
def operator_config(tmp_path: Path) -> Path:
    """Operator configuration that routes one control through the planted server name."""
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir()
    path.write_text(
        f"""schema_version = 1

[controls."{SERVER_CONTROL}"]
passes = [{{ handler = "mcp", server = "planted", tool = "check" }}]
""",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


EXPECTED_IGNORED = {
    (".darnit/config.toml", "controls"),
    (".darnit/config.toml", "trust"),
    ("darnit.toml", "controls"),
    ("darnit.toml", "trust"),
    (".project/darnit.yaml", "mcp_servers"),
    (".project/darnit.yaml", "llm"),
}


def _assert_nothing_ran(markers: Path) -> None:
    assert sorted(p.name for p in markers.iterdir()) == []


def _assert_ignored_reported(output: dict) -> None:
    ignored = output["ignored_repository_settings"]
    reported = {(entry["file"], entry["key"]) for entry in ignored}
    assert EXPECTED_IGNORED <= reported
    # .baseline.toml is not read at all: one notice, no per-key entries (FR-023).
    assert not any(entry["file"] == ".baseline.toml" for entry in ignored)
    assert [w for w in output["warnings"] if ".baseline.toml" in w] == [
        next(w for w in output["warnings"] if "darnit config migrate" in w)
    ]
    for entry in ignored:
        assert set(entry) == {"file", "key", "new_home"}
        if (entry["file"], entry["key"]) in EXPECTED_IGNORED:
            assert entry["new_home"] == OPERATOR_HOME


def _cli_audit(repo: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict:
    exit_code = cli_main(
        [
            "audit",
            str(repo),
            "-f",
            "openssf-baseline",
            "--include",
            f"{CONTROL},{SERVER_CONTROL},PLANTED-01",
            "-o",
            "json",
            "--no-fail",
            *extra,
        ]
    )
    assert exit_code == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.integration
def test_cli_audit_ignores_repository_tool_settings(
    planted_repo: Path, markers: Path, operator_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _cli_audit(planted_repo, capsys, "--operator-config", str(operator_config))

    _assert_nothing_ran(markers)
    _assert_ignored_reported(output)

    by_id = {r["id"]: r for r in output["results"]}
    assert "PLANTED-01" not in by_id
    assert by_id[SERVER_CONTROL]["status"] == "ERROR"
    assert "planted" in by_id[SERVER_CONTROL]["details"]


@pytest.mark.integration
def test_mcp_audit_tool_ignores_repository_tool_settings(
    planted_repo: Path, markers: Path, operator_config: Path
) -> None:
    from darnit.config.operator.loader import set_launch_options
    from darnit_baseline.tools import audit_openssf_baseline

    set_launch_options(operator_config)
    output = json.loads(
        audit_openssf_baseline(local_path=str(planted_repo), level=1, tags="domain=DO", output_format="json")
    )

    _assert_nothing_ran(markers)
    _assert_ignored_reported(output)

    by_id = {r["id"]: r for r in output["results"]}
    assert "PLANTED-01" not in by_id
    assert by_id[SERVER_CONTROL]["status"] == "ERROR"


@pytest.mark.integration
def test_operator_supplied_command_does_run(tmp_path: Path, planted_repo: Path, markers: Path, capsys) -> None:
    """Control for the marker mechanism: the same pass supplied by the operator runs."""
    marker = tmp_path / "operator-ran"
    config = tmp_path / "operator.toml"
    config.write_text(
        f'schema_version = 1\n\n[controls."{CONTROL}"]\npasses = [{_exec_pass(marker)}]\n',
        encoding="utf-8",
    )
    config.chmod(0o600)

    _cli_audit(planted_repo, capsys, "--operator-config", str(config))

    assert marker.exists()
    _assert_nothing_ran(markers)


@pytest.mark.integration
def test_operator_config_inside_repository_is_refused(planted_repo: Path, markers: Path, caplog) -> None:
    exit_code = cli_main(
        ["audit", str(planted_repo), "-f", "openssf-baseline", "--operator-config", str(planted_repo / "darnit.toml")]
    )

    assert exit_code != 0
    assert any("inside the audited repository" in r.getMessage() for r in caplog.records)
    _assert_nothing_ran(markers)
