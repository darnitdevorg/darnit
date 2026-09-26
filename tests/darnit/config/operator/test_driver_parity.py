"""The CLI, the MCP audit tool, and the harness apply the same operator configuration (SC-002, T016)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from darnit.cli import main as cli_main
from darnit.config.operator.loader import set_launch_options
from darnit.core.llm_step import LLMJudgment, MockLLMStep
from darnit.harness.driver import HarnessRun

CONTROL = "OSPS-DO-01.01"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository without a README, so the framework's own passes for CONTROL fail."""
    path = tmp_path / "repo"
    path.mkdir()
    (path / "OPERATOR_README.txt").write_text("documented elsewhere\n", encoding="utf-8")
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/project.git"],
        cwd=path,
        check=True,
    )
    return path


@pytest.fixture
def operator_config(tmp_path: Path) -> Path:
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir()
    path.write_text(
        f"""schema_version = 1

[controls."{CONTROL}"]
passes = [{{ handler = "file_exists", files = ["OPERATOR_README.txt"] }}]
""",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status(results: list[dict], control_id: str) -> str:
    return next(r["status"] for r in results if r["id"] == control_id)


@pytest.mark.integration
def test_cli_mcp_and_harness_apply_the_same_operator_config(
    repo: Path, operator_config: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    expected_digest = _digest(operator_config)

    exit_code = cli_main(
        [
            "audit",
            str(repo),
            "-f",
            "openssf-baseline",
            "--include",
            CONTROL,
            "-o",
            "json",
            "--no-fail",
            "--operator-config",
            str(operator_config),
        ]
    )
    assert exit_code == 0
    cli_output = json.loads(capsys.readouterr().out)

    from darnit_baseline.tools import audit_openssf_baseline

    set_launch_options(operator_config)
    mcp_output = json.loads(
        audit_openssf_baseline(local_path=str(repo), level=1, tags="domain=DO", output_format="json")
    )

    run = HarnessRun(
        local_path=str(repo),
        framework_name="openssf-baseline",
        level=1,
        llm_step=MockLLMStep(LLMJudgment(outcome="inconclusive", confidence=0.0, reasoning="mock")),
        per_call_timeout_s=10,
        total_run_timeout_s=120,
    )
    report = json.loads(asyncio.new_event_loop().run_until_complete(run.run()).to_json())

    for output, results in (
        (cli_output, cli_output["results"]),
        (mcp_output, mcp_output["results"]),
        (report, report["controls"]),
    ):
        assert output["operator_config"]["source"] == str(operator_config.resolve())
        assert output["operator_config"]["digest"] == expected_digest
        assert _status(results, CONTROL) == "PASS"


@pytest.mark.integration
def test_without_operator_config_every_driver_reports_builtin_defaults(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli_main(
        ["audit", str(repo), "-f", "openssf-baseline", "--include", CONTROL, "-o", "json", "--no-fail"]
    )
    assert exit_code == 0
    cli_output = json.loads(capsys.readouterr().out)

    from darnit_baseline.tools import audit_openssf_baseline

    mcp_output = json.loads(
        audit_openssf_baseline(local_path=str(repo), level=1, tags="domain=DO", output_format="json")
    )

    for output in (cli_output, mcp_output):
        assert output["operator_config"]["source"] == "builtin-defaults"
        assert output["operator_config"]["digest"] is None
        assert _status(output["results"], CONTROL) != "PASS"
