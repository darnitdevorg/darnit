"""Operator configuration loading (feature 040, T012; contracts/operator-config.md)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from darnit.config.operator import loader
from darnit.config.operator.loader import BUILTIN_DEFAULTS, OperatorConfigError, load_operator_config

GOOD = 'schema_version = 1\n[trust]\nrepos = ["github.com/example/project"]\n'


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".config" / "darnit").mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(loader, "user_config_dir", lambda: home / ".config" / "darnit")
    for var in ("GITHUB_ACTIONS", "GITLAB_CI"):
        monkeypatch.delenv(var, raising=False)
    return home / ".config" / "darnit"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.unit
def test_default_location_is_used(config_home: Path) -> None:
    path = _write(config_home / "config.toml", GOOD)
    loaded = load_operator_config()
    assert loaded.source == str(path.resolve())
    assert loaded.digest == hashlib.sha256(GOOD.encode()).hexdigest()
    assert loaded.config.trust.repos == ["github.com/example/project"]


@pytest.mark.unit
def test_explicit_path_overrides_default(config_home: Path, tmp_path: Path) -> None:
    _write(config_home / "config.toml", GOOD)
    other = _write(tmp_path / "elsewhere" / "op.toml", "schema_version = 1\n")
    loaded = load_operator_config(other)
    assert loaded.source == str(other.resolve())
    assert loaded.config.trust.repos == []


@pytest.mark.unit
def test_missing_default_file_uses_builtin_defaults(config_home: Path) -> None:
    loaded = load_operator_config()
    assert loaded.source == BUILTIN_DEFAULTS
    assert loaded.digest is None
    assert loaded.config.schema_version == 1
    assert str(config_home / "config.toml") in loaded.searched


@pytest.mark.unit
def test_missing_explicit_path_is_an_error(config_home: Path, tmp_path: Path) -> None:
    with pytest.raises(OperatorConfigError, match="not found"):
        load_operator_config(tmp_path / "nope.toml")


@pytest.mark.unit
def test_validation_error_names_file_and_dotted_key(config_home: Path) -> None:
    path = _write(config_home / "config.toml", 'schema_version = 1\n[trust]\nrepo = ["x"]\n')
    with pytest.raises(OperatorConfigError) as exc:
        load_operator_config()
    assert str(path) in str(exc.value)
    assert "trust.repo" in str(exc.value)


@pytest.mark.unit
def test_invalid_toml_is_an_error(config_home: Path) -> None:
    _write(config_home / "config.toml", "schema_version = \n")
    with pytest.raises(OperatorConfigError):
        load_operator_config()


@pytest.mark.unit
def test_environment_cannot_grant_trust(config_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-008: no environment variable changes what is trusted."""
    for var in ("DARNIT_TRUST_REPO_CONFIG", "DARNIT_TRUSTED_REPOS", "DARNIT_CONFIG"):
        monkeypatch.setenv(var, "1")
    loaded = load_operator_config()
    assert loaded.source == BUILTIN_DEFAULTS
    assert loaded.config.trust.repos == []
