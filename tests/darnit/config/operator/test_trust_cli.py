"""``darnit config trust add|list|remove`` edits only ``[trust].repos`` (feature 040, T036)."""

from __future__ import annotations

import stat
import tomllib
from pathlib import Path

import pytest

from darnit.cli import main as cli_main
from darnit.config.operator import loader


def _trust(config: Path, *args: str) -> int:
    return cli_main(["config", "trust", *args, "--operator-config", str(config)])


def _repos(config: Path) -> list[str]:
    return tomllib.loads(config.read_text(encoding="utf-8"))["trust"]["repos"]


@pytest.mark.unit
class TestAdd:
    def test_creates_file_with_schema_version_and_private_modes(self, tmp_path: Path) -> None:
        config = tmp_path / "darnit" / "config.toml"

        assert _trust(config, "add", "git@github.com:Example/Own.git") == 0

        data = tomllib.loads(config.read_text(encoding="utf-8"))
        assert data == {"schema_version": 1, "trust": {"repos": ["github.com/example/own"]}}
        assert stat.S_IMODE(config.stat().st_mode) == 0o600
        assert stat.S_IMODE(config.parent.stat().st_mode) == 0o700

    def test_default_location_is_the_resolved_operator_config(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(loader, "user_config_dir", lambda: tmp_path / "xdg" / "darnit")

        assert cli_main(["config", "trust", "add", "github.com/example/own"]) == 0
        assert _repos(tmp_path / "xdg" / "darnit" / "config.toml") == ["github.com/example/own"]

    def test_preserves_everything_else(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        original = """# my darnit settings
schema_version = 1

[plugins]
allowed = ["openssf-baseline"]  # keep this comment

[trust]
case_insensitive_hosts = ["git.example.com"]
repos = [
    "github.com/example/one",  # first
]

[[trust.ci]]
event = "push-default-branch"

[llm]
model = "claude-sonnet-5"
"""
        config.write_text(original, encoding="utf-8")

        assert _trust(config, "add", "https://git.example.com/Team/Two") == 0

        text = config.read_text(encoding="utf-8")
        assert _repos(config) == ["github.com/example/one", "git.example.com/team/two"]
        before, after = tomllib.loads(original), tomllib.loads(text)
        before["trust"].pop("repos")
        after["trust"].pop("repos")
        assert before == after
        assert "# my darnit settings" in text
        assert "# keep this comment" in text

    def test_adds_repos_to_existing_trust_table(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("schema_version = 1\n\n[trust]\ncase_insensitive_hosts = []\n", encoding="utf-8")

        assert _trust(config, "add", "github.com/example/own") == 0
        assert _repos(config) == ["github.com/example/own"]

    def test_duplicate_in_another_form_is_not_added(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text('schema_version = 1\n\n[trust]\nrepos = ["github.com/example/own"]\n', encoding="utf-8")
        before = config.read_text(encoding="utf-8")

        assert _trust(config, "add", "https://github.com/Example/Own.git") == 0
        assert config.read_text(encoding="utf-8") == before

    def test_unparseable_identity_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"

        assert _trust(config, "add", "not a repository") == 1
        assert not config.exists()

    def test_inline_trust_table_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        original = 'schema_version = 1\ntrust = { repos = ["github.com/example/one"] }\n'
        config.write_text(original, encoding="utf-8")

        assert _trust(config, "add", "github.com/example/two") == 1
        assert config.read_text(encoding="utf-8") == original

    def test_invalid_existing_file_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("schema_version = 1\nbogus = true\n", encoding="utf-8")

        assert _trust(config, "add", "github.com/example/two") == 1


@pytest.mark.unit
class TestRemoveAndList:
    def test_remove_matches_canonical_form(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            'schema_version = 1\n\n[trust]\nrepos = ["github.com/example/one", "github.com/example/two"]\n',
            encoding="utf-8",
        )

        assert _trust(config, "remove", "git@github.com:Example/One.git") == 0
        assert _repos(config) == ["github.com/example/two"]

    def test_remove_unknown_entry_fails(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text('schema_version = 1\n\n[trust]\nrepos = ["github.com/example/one"]\n', encoding="utf-8")

        assert _trust(config, "remove", "github.com/example/other") == 1
        assert _repos(config) == ["github.com/example/one"]

    def test_remove_without_file_fails(self, tmp_path: Path) -> None:
        assert _trust(tmp_path / "config.toml", "remove", "github.com/example/one") == 1

    def test_list(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            'schema_version = 1\n\n[trust]\nrepos = ["github.com/example/one", "github.com/example/two"]\n',
            encoding="utf-8",
        )

        assert _trust(config, "list") == 0
        assert capsys.readouterr().out.splitlines() == ["github.com/example/one", "github.com/example/two"]

    def test_list_without_file_is_empty(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert _trust(tmp_path / "config.toml", "list") == 0
        assert capsys.readouterr().out == ""
