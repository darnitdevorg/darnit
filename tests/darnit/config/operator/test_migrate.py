"""``darnit config migrate``: .baseline.toml to .project/ claims and an operator fragment (feature 040, US5, T058)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

from darnit.cli import main as cli_main
from darnit.config.operator import loader
from darnit.config.operator.migrate import MigrationError, migrate_baseline_toml
from darnit.config.operator.schema import OperatorConfig
from darnit.config.schema import BaselineExtension
from darnit.trust.assertions import collect_assertions

BASELINE = """version = "1.0"
extends = "openssf-baseline"

[settings]
timeout = 60

[plugins]
allow_unsigned = false
trusted_publishers = ["https://github.com/example"]

[adapters.scanner]
type = "command"
command = "scanner"

[mcp_servers.scanner]
command = ["scanner-mcp", "--stdio"]
env = { SCANNER_TOKEN = "$SCANNER_TOKEN" }

[stores.report]
backend = "filesystem"

[controls."OSPS-BR-02.01"]
status = "n/a"
reason = "Pre-1.0 project with no releases yet"

[controls."OSPS-VM-02.01"]
status = "disabled"

[controls."OSPS-DO-01.01"]
passes = [{ handler = "file_exists", files = ["README.md", "README.rst"] }]

[controls."CUSTOM-01"]
name = "InternalReview"
level = 1
domain = "SA"
description = "Internal review sign-off"
passes = [{ handler = "manual", steps = ["Check sign-off"] }]
"""

CLAIM_IDS = {"OSPS-BR-02.01", "OSPS-VM-02.01", "OSPS-DO-01.01", "CUSTOM-01"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / ".baseline.toml").write_text(BASELINE, encoding="utf-8")
    return path


@pytest.fixture
def operator_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "home" / "darnit"
    config_dir.mkdir(parents=True)
    path = config_dir / "config.toml"
    path.write_text('schema_version = 1\n\n[trust]\nrepos = ["github.com/example/repo"]\n', encoding="utf-8")
    monkeypatch.setattr(loader, "user_config_dir", lambda: config_dir)
    return path


def _extension(repo: Path) -> dict:
    return yaml.safe_load((repo / ".project" / "darnit.yaml").read_text(encoding="utf-8"))


@pytest.mark.unit
class TestClaims:
    def test_status_and_reason_are_written_to_project_darnit_yaml(self, repo: Path) -> None:
        result = migrate_baseline_toml(repo)

        controls = _extension(repo)["controls"]
        assert controls == {
            "OSPS-BR-02.01": {"status": "n/a", "reason": "Pre-1.0 project with no releases yet"},
            "OSPS-VM-02.01": {"status": "disabled"},
        }
        assert sorted(result.written) == ["OSPS-BR-02.01", "OSPS-VM-02.01"]
        assert result.project_file == repo / ".project" / "darnit.yaml"

    def test_written_file_is_schema_conformant_and_read_as_claims(self, repo: Path) -> None:
        migrate_baseline_toml(repo)
        (repo / ".baseline.toml").unlink()

        BaselineExtension.model_validate(_extension(repo))
        claims = collect_assertions(repo, CLAIM_IDS)
        assert {c.control_id: c.location.split(":")[0] for c in claims} == {
            "OSPS-BR-02.01": ".project/darnit.yaml",
            "OSPS-VM-02.01": ".project/darnit.yaml",
        }

    def test_existing_content_is_preserved(self, repo: Path) -> None:
        (repo / ".project").mkdir()
        (repo / ".project" / "darnit.yaml").write_text(
            "context:\n  has_releases: false\ncontrols:\n  OSPS-QA-01.01:\n    status: n/a\n    reason: kept\n",
            encoding="utf-8",
        )

        migrate_baseline_toml(repo)

        data = _extension(repo)
        assert data["context"] == {"has_releases": False}
        assert data["controls"]["OSPS-QA-01.01"] == {"status": "n/a", "reason": "kept"}
        assert "OSPS-BR-02.01" in data["controls"]

    def test_existing_claim_is_not_overwritten_without_force(self, repo: Path) -> None:
        (repo / ".project").mkdir()
        (repo / ".project" / "darnit.yaml").write_text(
            "controls:\n  OSPS-BR-02.01:\n    status: n/a\n    reason: written by a person\n    asserted_by: '@alice'\n",
            encoding="utf-8",
        )

        result = migrate_baseline_toml(repo)

        assert result.skipped == ["OSPS-BR-02.01"]
        assert _extension(repo)["controls"]["OSPS-BR-02.01"]["reason"] == "written by a person"

        forced = migrate_baseline_toml(repo, force=True)

        assert "OSPS-BR-02.01" in forced.written
        assert _extension(repo)["controls"]["OSPS-BR-02.01"] == {
            "status": "n/a",
            "reason": "Pre-1.0 project with no releases yet",
        }

    def test_identical_claim_is_left_alone(self, repo: Path) -> None:
        migrate_baseline_toml(repo)
        again = migrate_baseline_toml(repo)

        assert again.written == []
        assert sorted(again.unchanged) == ["OSPS-BR-02.01", "OSPS-VM-02.01"]
        assert again.skipped == []

    def test_baseline_toml_is_not_deleted(self, repo: Path) -> None:
        migrate_baseline_toml(repo)
        assert (repo / ".baseline.toml").read_text(encoding="utf-8") == BASELINE

    def test_missing_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(MigrationError, match=".baseline.toml"):
            migrate_baseline_toml(tmp_path)

    def test_unreadable_project_file_is_not_clobbered(self, repo: Path) -> None:
        (repo / ".project").mkdir()
        bad = "controls: [unterminated\n"
        (repo / ".project" / "darnit.yaml").write_text(bad, encoding="utf-8")

        with pytest.raises(MigrationError, match="darnit.yaml"):
            migrate_baseline_toml(repo)
        assert (repo / ".project" / "darnit.yaml").read_text(encoding="utf-8") == bad


@pytest.mark.unit
class TestOperatorFragment:
    def test_fragment_holds_the_tool_settings(self, repo: Path) -> None:
        fragment = tomllib.loads(migrate_baseline_toml(repo).operator_fragment)

        assert fragment["plugins"] == {"allow_unsigned": False, "trusted_publishers": ["https://github.com/example"]}
        assert fragment["mcp_servers"]["scanner"]["command"] == ["scanner-mcp", "--stdio"]
        assert fragment["mcp_servers"]["scanner"]["env"] == {"SCANNER_TOKEN": "$SCANNER_TOKEN"}
        assert fragment["stores"] == {"report": {"backend": "filesystem"}}
        assert fragment["controls"]["OSPS-DO-01.01"]["passes"] == [
            {"handler": "file_exists", "files": ["README.md", "README.rst"]}
        ]
        assert fragment["custom_controls"]["CUSTOM-01"]["name"] == "InternalReview"
        assert fragment["custom_controls"]["CUSTOM-01"]["passes"] == [
            {"handler": "manual", "steps": ["Check sign-off"]}
        ]

    def test_fragment_is_valid_operator_configuration(self, repo: Path) -> None:
        fragment = tomllib.loads(migrate_baseline_toml(repo).operator_fragment)

        OperatorConfig.model_validate({"schema_version": 1, **fragment})

    def test_settings_operator_configuration_cannot_express_are_listed(self, repo: Path) -> None:
        result = migrate_baseline_toml(repo)

        assert {"adapters", "extends", "settings"} <= set(result.not_migrated)
        assert "# [adapters.scanner]" in result.operator_fragment

    def test_claims_only_file_has_no_fragment(self, tmp_path: Path) -> None:
        (tmp_path / ".baseline.toml").write_text(
            '[controls."OSPS-BR-02.01"]\nstatus = "n/a"\nreason = "none"\n', encoding="utf-8"
        )

        assert migrate_baseline_toml(tmp_path).operator_fragment == ""


@pytest.mark.unit
class TestCommand:
    def test_prints_fragment_and_next_steps_without_touching_operator_config(
        self, repo: Path, operator_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = operator_file.read_bytes()

        assert cli_main(["config", "migrate", str(repo)]) == 0
        out = capsys.readouterr().out

        assert operator_file.read_bytes() == before
        assert "[mcp_servers.scanner]" in out
        assert str(operator_file) in out
        assert "delete .baseline.toml" in out.lower()
        assert "OSPS-BR-02.01" in out
        assert (repo / ".baseline.toml").exists()

    def test_does_not_create_operator_config(self, repo: Path, tmp_path: Path, monkeypatch) -> None:
        config_dir = tmp_path / "absent" / "darnit"
        monkeypatch.setattr(loader, "user_config_dir", lambda: config_dir)

        assert cli_main(["config", "migrate", str(repo)]) == 0
        assert not config_dir.exists()

    def test_reports_skipped_claims_and_force(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (repo / ".project").mkdir()
        (repo / ".project" / "darnit.yaml").write_text(
            "controls:\n  OSPS-BR-02.01:\n    status: n/a\n    reason: mine\n", encoding="utf-8"
        )

        assert cli_main(["config", "migrate", str(repo)]) == 0
        assert "--force" in capsys.readouterr().out
        assert _extension(repo)["controls"]["OSPS-BR-02.01"]["reason"] == "mine"

        assert cli_main(["config", "migrate", str(repo), "--force"]) == 0
        assert _extension(repo)["controls"]["OSPS-BR-02.01"]["reason"] == "Pre-1.0 project with no releases yet"

    def test_missing_file_fails(self, tmp_path: Path) -> None:
        assert cli_main(["config", "migrate", str(tmp_path)]) == 1

    def test_defaults_to_current_directory(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        assert cli_main(["config", "migrate"]) == 0
        assert (repo / ".project" / "darnit.yaml").is_file()
