"""``darnit init`` explains .project/ claims and operator configuration instead of writing .baseline.toml (040 T063)."""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.cli import main as cli_main
from darnit.config.operator import loader


@pytest.fixture(autouse=True)
def _quiet_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "xdg" / "darnit"
    monkeypatch.setattr(loader, "user_config_dir", lambda: path)
    return path


@pytest.mark.unit
def test_init_writes_nothing(tmp_path: Path, config_dir: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert cli_main(["init", str(repo)]) == 0

    assert list(repo.iterdir()) == []
    assert not config_dir.exists()


@pytest.mark.unit
def test_init_explains_claims_and_operator_configuration(
    tmp_path: Path, config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main(["init", str(tmp_path)]) == 0
    out = capsys.readouterr().out

    assert ".project/darnit.yaml" in out
    assert "status: n/a" in out and "reason:" in out
    assert str(config_dir / "config.toml") in out
    assert "darnit config show" in out
    assert "darnit config trust add" in out
    assert "--framework" in out


@pytest.mark.unit
def test_init_points_existing_baseline_toml_at_migrate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".baseline.toml").write_text('extends = "openssf-baseline"\n', encoding="utf-8")

    assert cli_main(["init", str(tmp_path)]) == 0

    assert "darnit config migrate" in capsys.readouterr().out
    assert (tmp_path / ".baseline.toml").read_text(encoding="utf-8") == 'extends = "openssf-baseline"\n'
