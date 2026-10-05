""".baseline.toml is not read (feature 040 FR-023; framework-design 14.4).

No key in a repository's ``.baseline.toml`` affects an audit, even for a
repository the operator trusts. An audit of a repository that has one
records exactly one notice pointing at ``darnit config migrate``, which
still moves the file's claims to ``.project/darnit.yaml``.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from darnit.cli import main as cli_main
from darnit.config.merger import baseline_toml_warnings, find_ignored_repository_settings
from darnit.trust.assertions import collect_assertions

OWN = "github.com/example/repo"
CLAIMED = "OSPS-DO-01.01"
_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")

REPRESENTATIVE = f"""version = "1.0"
extends = "testchecks"

[settings]
timeout = 60

[plugins]
allow_unsigned = true

[mcp_servers.scanner]
command = ["scanner-mcp", "--stdio"]

[stores.report]
backend = "filesystem"

[controls."{CLAIMED}"]
status = "n/a"
reason = "docs live elsewhere"

[controls."CUSTOM-01"]
name = "Custom"
level = 1
domain = "DO"
passes = [{{ handler = "manual" }}]
"""


@pytest.fixture(autouse=True)
def _outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _CI_VARS:
        monkeypatch.delenv(var, raising=False)


def _write(repo: Path, text: str = REPRESENTATIVE) -> Path:
    repo.mkdir(exist_ok=True)
    (repo / ".baseline.toml").write_text(text, encoding="utf-8")
    return repo


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://{OWN}.git"], cwd=repo, check=True)
    return _write(repo)


def _trusting_operator_file(tmp_path: Path) -> Path:
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir()
    path.write_text(f'schema_version = 1\n\n[trust]\nrepos = ["{OWN}"]\n', encoding="utf-8")
    path.chmod(0o600)
    return path


def _cli_audit(repo: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict:
    exit_code = cli_main(["audit", str(repo), "--include", CLAIMED, "-o", "json", "--no-fail", *extra])
    assert exit_code == 0
    return json.loads(capsys.readouterr().out)


def _notices(text: str) -> int:
    return text.count(".baseline.toml")


@pytest.mark.unit
class TestNotice:
    def test_one_notice_pointing_at_migrate(self, tmp_path: Path) -> None:
        (notice,) = baseline_toml_warnings(_write(tmp_path))

        assert ".baseline.toml" in notice and "ignored" in notice
        assert "darnit config migrate" in notice
        assert ".project/darnit.yaml" in notice
        assert "operator configuration" in notice

    def test_unreadable_file_gets_the_same_single_notice(self, tmp_path: Path) -> None:
        assert baseline_toml_warnings(_write(tmp_path, "[controls\n")) == baseline_toml_warnings(_write(tmp_path))

    def test_no_file_no_notice(self, tmp_path: Path) -> None:
        assert baseline_toml_warnings(tmp_path) == []

    def test_keys_are_not_listed_as_ignored_settings(self, tmp_path: Path) -> None:
        assert find_ignored_repository_settings(_write(tmp_path)) == []


@pytest.mark.unit
def test_no_claims_are_read(tmp_path: Path) -> None:
    assert collect_assertions(_write(tmp_path), {CLAIMED}) == []


@pytest.mark.integration
def test_trusted_repository_claim_has_no_effect_and_one_notice_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)
    repo = _git_repo(tmp_path)
    operator = _trusting_operator_file(tmp_path)

    with caplog.at_level(logging.WARNING, logger="darnit"):
        output = _cli_audit(repo, capsys, "-f", "openssf-baseline", "--repo", OWN, "--operator-config", str(operator))

    assert output["trust"]["trusted"] is True
    (result,) = [r for r in output["results"] if r["id"] == CLAIMED]
    assert result["status"] != "N/A"
    assert not result.get("assertion")
    assert sum(_notices(w) for w in output["warnings"]) == 1
    (logged,) = [r for r in caplog.records if ".baseline.toml" in r.getMessage()]
    assert logged.levelno == logging.WARNING
    assert _notices(logged.getMessage()) == 1
    assert not any(s["file"] == ".baseline.toml" for s in output["ignored_repository_settings"])


@pytest.mark.integration
def test_extends_does_not_select_the_framework(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``extends = "testchecks"`` is ignored: the default framework is audited, not testchecks."""
    output = _cli_audit(_git_repo(tmp_path), capsys)

    assert output["framework"] == "openssf-baseline"
    (result,) = output["results"]
    assert result["id"] == CLAIMED
    assert result["level"] == 1


@pytest.mark.integration
def test_repository_supplied_command_is_not_run(tmp_path: Path) -> None:
    """A pass in .baseline.toml is never executed, through the MCP audit tool."""
    from darnit_baseline.tools import audit_openssf_baseline

    marker = tmp_path / "marker.txt"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# x\n", encoding="utf-8")
    _write(
        repo,
        f'[controls."{CLAIMED}"]\npasses = [ {{ handler = "exec", command = ["sh", "-c", "echo pwned > {marker}"] }} ]\n',
    )

    audit_openssf_baseline(owner="o", repo="r", local_path=str(repo), output_format="json")

    assert not marker.exists()


@pytest.mark.integration
def test_migrate_moves_the_claim_and_the_audit_then_honors_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)
    repo = _git_repo(tmp_path)
    operator = _trusting_operator_file(tmp_path)

    assert cli_main(["config", "migrate", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "[mcp_servers.scanner]" in out

    output = _cli_audit(repo, capsys, "-f", "openssf-baseline", "--repo", OWN, "--operator-config", str(operator))

    (result,) = [r for r in output["results"] if r["id"] == CLAIMED]
    assert result["status"] == "N/A"
    assert result["assertion"]["outcome"] == "honored"
    assert result["assertion"]["location"] == f".project/darnit.yaml:controls.{CLAIMED}"
    assert sum(_notices(w) for w in output["warnings"]) == 1
