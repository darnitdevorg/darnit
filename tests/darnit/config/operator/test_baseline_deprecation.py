""".baseline.toml during and after its deprecation release (feature 040, US5, T057).

During the deprecation release per-control ``status``/``reason`` are read
as not-applicable claims under the same rules as ``.project/`` claims, and
every audit warns once per setting in the file with the setting's new home.
After it, the file is ignored and a single notice says so.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from darnit.cli import main as cli_main
from darnit.config import merger
from darnit.config.merger import baseline_toml_warnings, load_user_config, load_user_config_with_report
from darnit.trust.assertions import collect_assertions

OWN = "github.com/example/repo"
CLAIMED = "OSPS-DO-01.01"
_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")

REPRESENTATIVE = f"""version = "1.0"
extends = "openssf-baseline"

[settings]
timeout = 60

[plugins]
allow_unsigned = true

[adapters.scanner]
type = "command"
command = "scanner"

[mcp_servers.scanner]
command = ["scanner-mcp", "--stdio"]

[stores.report]
backend = "filesystem"

[controls."{CLAIMED}"]
status = "n/a"
reason = "docs live elsewhere"
passes = [{{ handler = "manual" }}]

[controls."CUSTOM-01"]
name = "Custom"
level = 1
domain = "DO"
passes = [{{ handler = "manual" }}]
"""

EXPECTED_HOMES = {
    "extends": "--framework",
    "settings": "operator configuration",
    "plugins": "operator configuration",
    "adapters": "operator configuration",
    "mcp_servers": "operator configuration",
    "stores": "operator configuration",
    f"controls.{CLAIMED}.status": ".project/darnit.yaml",
    f"controls.{CLAIMED}.reason": ".project/darnit.yaml",
    f"controls.{CLAIMED}.passes": "operator configuration",
    "controls.CUSTOM-01": "operator configuration",
}


@pytest.fixture(autouse=True)
def _outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _CI_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def ended(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(merger, "BASELINE_TOML_DEPRECATION_ACTIVE", False)


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


def _setting(warning: str) -> str:
    return warning.split("`")[1]


def _operator(trusted: bool):
    from darnit.config.operator.loader import LoadedOperatorConfig
    from darnit.config.operator.schema import OperatorConfig

    config = OperatorConfig.model_validate({"schema_version": 1, "trust": {"repos": [OWN] if trusted else []}})
    return LoadedOperatorConfig(config=config, source="test", digest=None, permission_check="ok", strict=False)


def _audit(repo: Path, *, trusted: bool) -> dict:
    from darnit.config import load_controls_from_framework, load_framework_config
    from darnit.tools.audit import _get_framework_config_path, run_sieve_audit

    framework = load_framework_config(_get_framework_config_path("openssf-baseline"))
    controls = [c for c in load_controls_from_framework(framework) if c.control_id == CLAIMED]
    results, _ = run_sieve_audit(
        owner="example",
        repo="repo",
        local_path=str(repo),
        default_branch="main",
        level=1,
        controls=controls,
        framework_name="openssf-baseline",
        operator_config=_operator(trusted),
        target=OWN,
    )
    return next(r for r in results if r["id"] == CLAIMED)


@pytest.mark.unit
class TestDeprecationRelease:
    def test_switch_is_on_for_this_release(self) -> None:
        assert merger.BASELINE_TOML_DEPRECATION_ACTIVE is True

    def test_one_warning_per_setting_naming_its_new_home(self, tmp_path: Path) -> None:
        warnings = baseline_toml_warnings(_write(tmp_path))

        assert len(warnings) == len(EXPECTED_HOMES)
        by_setting = {_setting(w): w for w in warnings}
        assert set(by_setting) == set(EXPECTED_HOMES)
        for setting, home in EXPECTED_HOMES.items():
            assert home in by_setting[setting], by_setting[setting]
            assert "deprecated" in by_setting[setting]

    def test_claim_warnings_point_at_the_migration(self, tmp_path: Path) -> None:
        warnings = baseline_toml_warnings(_write(tmp_path))

        status = next(w for w in warnings if _setting(w) == f"controls.{CLAIMED}.status")
        assert "darnit config migrate" in status

    def test_no_file_no_warnings(self, tmp_path: Path) -> None:
        assert baseline_toml_warnings(tmp_path) == []

    def test_unreadable_file_gets_one_warning(self, tmp_path: Path) -> None:
        (warning,) = baseline_toml_warnings(_write(tmp_path, "[controls\n"))
        assert ".baseline.toml" in warning and "deprecated" in warning

    def test_only_status_and_reason_become_claims(self, tmp_path: Path) -> None:
        repo = _write(tmp_path)

        (claim,) = collect_assertions(repo, {CLAIMED, "CUSTOM-01"})
        assert (claim.control_id, claim.reason) == (CLAIMED, "docs live elsewhere")
        assert claim.location == f".baseline.toml:controls.{CLAIMED}"

        user = load_user_config(repo)
        assert user is not None
        assert set(user.controls) == {CLAIMED}
        assert user.get_control_override(CLAIMED).passes is None
        assert not user.mcp_servers and not user.adapters


@pytest.mark.integration
class TestDeprecatedClaimsFollowTheTrustRules:
    def test_untrusted_claim_is_pending(self, tmp_path: Path) -> None:
        result = _audit(_git_repo(tmp_path), trusted=False)

        assert result["assertion"]["outcome"] == "pending"
        assert result["assertion"]["location"] == f".baseline.toml:controls.{CLAIMED}"

    def test_trusted_claim_is_honored(self, tmp_path: Path) -> None:
        result = _audit(_git_repo(tmp_path), trusted=True)

        assert result["status"] == "N/A"
        assert result["assertion"]["outcome"] == "honored"


@pytest.mark.integration
def test_every_audit_reports_the_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)
    repo = _git_repo(tmp_path)

    with caplog.at_level(logging.WARNING, logger="darnit"):
        cli_main(["audit", str(repo), "-f", "openssf-baseline", "--include", CLAIMED, "-o", "json", "--no-fail"])
    output = json.loads(capsys.readouterr().out)

    assert {_setting(w) for w in output["warnings"]} == set(EXPECTED_HOMES)
    for setting in EXPECTED_HOMES:
        assert f"`{setting}`" in caplog.text


@pytest.mark.unit
class TestAfterDeprecation:
    def test_file_is_not_read(self, tmp_path: Path, ended: None) -> None:
        repo = _write(tmp_path)

        assert load_user_config(repo) is None
        assert load_user_config_with_report(repo) == (None, [])
        assert collect_assertions(repo, {CLAIMED}) == []

    def test_single_notice_says_it_was_ignored(self, tmp_path: Path, ended: None) -> None:
        (notice,) = baseline_toml_warnings(_write(tmp_path))

        assert ".baseline.toml" in notice and "ignored" in notice
        assert "darnit config migrate" in notice

    def test_no_file_no_notice(self, tmp_path: Path, ended: None) -> None:
        assert baseline_toml_warnings(tmp_path) == []


@pytest.mark.integration
def test_claim_has_no_effect_after_deprecation(tmp_path: Path, ended: None) -> None:
    result = _audit(_git_repo(tmp_path), trusted=True)

    assert "assertion" not in result or result["assertion"] is None
    assert result["status"] != "N/A"
