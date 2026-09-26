"""Every audit-running path records a trust decision (feature 040, T034, T035)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from darnit.cli import main as cli_main
from darnit.config.operator.loader import set_launch_options
from darnit.core.llm_step import LLMJudgment, MockLLMStep
from darnit.harness.driver import HarnessRun

OWN = "github.com/example/own"
CONTROL = "OSPS-DO-01.01"
_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")


@pytest.fixture(autouse=True)
def _outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _CI_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "own"
    path.mkdir()
    (path / "README.md").write_text("# own\n", encoding="utf-8")
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/own.git"], cwd=path, check=True)
    return path


@pytest.fixture
def operator_config(tmp_path: Path) -> Path:
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir()
    path.write_text(f'schema_version = 1\n\n[trust]\nrepos = ["{OWN}"]\n', encoding="utf-8")
    path.chmod(0o600)
    return path


def _cli_audit(repo: Path, operator_config: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict:
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
            *extra,
        ]
    )
    assert exit_code == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.integration
class TestCli:
    def test_explicit_repo_is_operator_target(
        self, repo: Path, operator_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        trust = _cli_audit(repo, operator_config, capsys, "--repo", "github.com/Example/Own")["trust"]

        assert trust["repository"] == OWN
        assert trust["identity_source"] == "operator_target"
        assert trust["trusted"] is True
        assert trust["reason"] == "listed; local run"

    def test_checkout_remote_is_only_a_hint(
        self, repo: Path, operator_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        trust = _cli_audit(repo, operator_config, capsys)["trust"]

        assert trust["repository"] == OWN
        assert trust["identity_source"] == "checkout_hint"
        assert trust["trusted"] is False
        assert trust["reason"] == "identity from checkout only"

    def test_mismatch_with_origin_is_reported(
        self, repo: Path, operator_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        trust = _cli_audit(repo, operator_config, capsys, "--repo", "github.com/example/other")["trust"]

        assert trust["trusted"] is False
        assert any("github.com/example/own" in w for w in trust["warnings"])

    def test_unparseable_repo_is_refused(self, repo: Path, operator_config: Path) -> None:
        exit_code = cli_main(
            ["audit", str(repo), "-f", "openssf-baseline", "--operator-config", str(operator_config), "--repo", "nope"]
        )

        assert exit_code == 1

    def test_text_output_names_trust(
        self, repo: Path, operator_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli_main(
            [
                "audit",
                str(repo),
                "-f",
                "openssf-baseline",
                "--include",
                CONTROL,
                "--no-fail",
                "--operator-config",
                str(operator_config),
                "--repo",
                OWN,
            ]
        )

        assert f"Trust: {OWN} trusted (listed; local run)" in capsys.readouterr().out


@pytest.mark.integration
class TestMcpTools:
    def test_owner_and_repo_arguments_are_operator_target(self, repo: Path, operator_config: Path) -> None:
        from darnit_baseline.tools import audit_openssf_baseline

        set_launch_options(operator_config)
        output = json.loads(
            audit_openssf_baseline(
                owner="example", repo="own", local_path=str(repo), level=1, tags="domain=DO", output_format="json"
            )
        )

        assert output["trust"]["identity_source"] == "operator_target"
        assert output["trust"]["trusted"] is True

    def test_host_argument_is_used(self, repo: Path, operator_config: Path) -> None:
        from darnit_baseline.tools import audit_openssf_baseline

        set_launch_options(operator_config)
        output = json.loads(
            audit_openssf_baseline(
                owner="example",
                repo="own",
                host="gitlab.com",
                local_path=str(repo),
                level=1,
                tags="domain=DO",
                output_format="json",
            )
        )

        assert output["trust"]["repository"] == "gitlab.com/example/own"
        assert output["trust"]["trusted"] is False

    def test_detected_owner_and_repo_are_not_a_target(self, repo: Path, operator_config: Path) -> None:
        from darnit_baseline.tools import audit_openssf_baseline

        set_launch_options(operator_config)
        output = json.loads(
            audit_openssf_baseline(local_path=str(repo), level=1, tags="domain=DO", output_format="json")
        )

        assert output["trust"]["identity_source"] == "checkout_hint"
        assert output["trust"]["trusted"] is False

    def test_builtin_audit_records_trust(self, repo: Path, operator_config: Path) -> None:
        from darnit.server.tools.builtin_audit import builtin_audit

        set_launch_options(operator_config)
        output = json.loads(
            asyncio.new_event_loop().run_until_complete(
                builtin_audit(
                    local_path=str(repo),
                    level=1,
                    output_format="json",
                    tags="domain=DO",
                    owner="example",
                    repo="own",
                    _framework_name="openssf-baseline",
                )
            )
        )

        assert output["trust"]["repository"] == OWN
        assert output["trust"]["trusted"] is True


@pytest.mark.integration
def test_harness_report_records_trust(repo: Path, operator_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    set_launch_options(operator_config)
    run = HarnessRun(
        local_path=str(repo),
        framework_name="openssf-baseline",
        level=1,
        llm_step=MockLLMStep(LLMJudgment(outcome="inconclusive", confidence=0.0, reasoning="mock")),
        per_call_timeout_s=10,
        total_run_timeout_s=120,
        target=OWN,
    )
    report = asyncio.new_event_loop().run_until_complete(run.run())

    assert json.loads(report.to_json())["trust"]["trusted"] is True
    assert "Trust" in report.to_markdown()


@pytest.mark.integration
def test_org_sweep_uses_each_repository_as_operator_target(
    tmp_path: Path, operator_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from darnit.tools import audit_org

    def fake_clone(owner: str, name: str, target_dir: str) -> bool:
        subprocess.run(["git", "init", "-q", target_dir], check=True)
        return True

    monkeypatch.setattr(audit_org, "clone_repo", fake_clone)
    set_launch_options(operator_config)
    result = audit_org._audit_single_repo("example", "own", 1, ["domain=DO"], framework_name="openssf-baseline")

    assert result["trust"]["repository"] == OWN
    assert result["trust"]["identity_source"] == "operator_target"
    assert result["trust"]["trusted"] is True


@pytest.mark.integration
def test_cmd_run_prints_trust(
    repo: Path, operator_config: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("darnit.agent.graph.audit", lambda state: state)
    cli_main(
        ["run", str(repo), "--feedback", "noninteractive", "--operator-config", str(operator_config), "--repo", OWN]
    )

    assert f"  Trust      : {OWN} trusted (listed; local run)" in capsys.readouterr().out


@pytest.mark.integration
def test_attestation_records_trust(repo: Path, operator_config: Path, tmp_path: Path) -> None:
    from darnit_baseline.attestation.predicate import build_assessment_predicate

    trust = {"repository": OWN, "identity_source": "operator_target", "trusted": True, "reason": "listed; local run"}
    predicate = build_assessment_predicate(
        owner="example",
        repo="own",
        commit="0" * 40,
        ref="main",
        level=1,
        results=[],
        project_config=None,
        adapters_used=["builtin"],
        trust=trust,
    )

    assert predicate["trust"] == trust
