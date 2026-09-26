"""Operator configuration is never read from inside the audited repository (FR-004, T013)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from darnit.config.operator import loader
from darnit.config.operator.loader import OperatorConfigError, load_operator_config


@pytest.fixture(autouse=True)
def _no_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "user_config_dir", lambda: tmp_path / "no-such-config-dir")
    for var in ("GITHUB_ACTIONS", "GITLAB_CI"):
        monkeypatch.delenv(var, raising=False)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    return repo


def _cfg(path: Path) -> Path:
    path.write_text("schema_version = 1\n", encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.unit
def test_explicit_path_inside_audited_repo_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    inside = _cfg(repo / "sub" / "operator.toml")
    with pytest.raises(OperatorConfigError, match="inside the audited repository"):
        load_operator_config(inside, audit_target=repo)


@pytest.mark.unit
def test_symlink_pointing_into_repo_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    inside = _cfg(repo / "operator.toml")
    link = tmp_path / "link.toml"
    os.symlink(inside, link)
    with pytest.raises(OperatorConfigError, match="inside the audited repository"):
        load_operator_config(link, audit_target=repo)


@pytest.mark.unit
def test_default_location_inside_repo_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A launcher that points XDG_CONFIG_HOME into the repository gains nothing."""
    repo = _repo(tmp_path)
    cfg_dir = repo / "sub"
    _cfg(cfg_dir / "config.toml")
    monkeypatch.setattr(loader, "user_config_dir", lambda: cfg_dir)
    with pytest.raises(OperatorConfigError, match="inside the audited repository"):
        load_operator_config(audit_target=repo)


@pytest.mark.unit
def test_path_outside_repo_is_accepted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = _cfg(tmp_path / "operator.toml")
    assert load_operator_config(outside, audit_target=repo).config.schema_version == 1


@pytest.mark.unit
def test_sibling_directory_with_common_prefix_is_not_inside(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sibling = tmp_path / "repo-other"
    sibling.mkdir()
    cfg = _cfg(sibling / "operator.toml")
    assert load_operator_config(cfg, audit_target=repo).config.schema_version == 1
