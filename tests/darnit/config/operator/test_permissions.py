"""Permission check on the operator configuration file (FR-007, T014)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from darnit.config.operator import loader
from darnit.config.operator.loader import OperatorConfigError, load_operator_config

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "user_config_dir", lambda: tmp_path / "no-such-config-dir")
    for var in ("GITHUB_ACTIONS", "GITLAB_CI"):
        monkeypatch.delenv(var, raising=False)


def _cfg(tmp_path: Path, text: str = "schema_version = 1\n", mode: int = 0o600) -> Path:
    d = tmp_path / "cfgdir"
    d.mkdir(mode=0o700, exist_ok=True)
    path = d / "operator.toml"
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


@pytest.mark.unit
def test_private_file_passes(tmp_path: Path) -> None:
    assert load_operator_config(_cfg(tmp_path)).permission_check == "passed"


@pytest.mark.unit
def test_world_writable_file_warns_by_default(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    loaded = load_operator_config(_cfg(tmp_path, mode=0o666))
    assert loaded.permission_check.startswith("failed")
    assert "writable" in caplog.text


@pytest.mark.unit
def test_group_writable_parent_fails(tmp_path: Path) -> None:
    path = _cfg(tmp_path)
    path.parent.chmod(0o770)
    assert load_operator_config(path).permission_check.startswith("failed")


@pytest.mark.unit
def test_strict_flag_refuses_failing_file(tmp_path: Path) -> None:
    with pytest.raises(OperatorConfigError, match="permission"):
        load_operator_config(_cfg(tmp_path, mode=0o666), strict=True)


@pytest.mark.unit
def test_ci_turns_strict_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(OperatorConfigError, match="permission"):
        load_operator_config(_cfg(tmp_path, mode=0o666))


@pytest.mark.unit
def test_file_can_turn_strict_on(tmp_path: Path) -> None:
    text = "schema_version = 1\n[policy]\nstrict_permissions = true\n"
    with pytest.raises(OperatorConfigError, match="permission"):
        load_operator_config(_cfg(tmp_path, text=text, mode=0o666))


@pytest.mark.unit
def test_file_cannot_turn_strict_off(tmp_path: Path) -> None:
    text = "schema_version = 1\n[policy]\nstrict_permissions = false\n"
    with pytest.raises(OperatorConfigError, match="permission"):
        load_operator_config(_cfg(tmp_path, text=text, mode=0o666), strict=True)


@pytest.mark.unit
def test_not_checkable_platform_refused_only_in_strict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "_permissions_checkable", lambda: False)
    path = _cfg(tmp_path)
    assert load_operator_config(path).permission_check == "not_checkable"
    with pytest.raises(OperatorConfigError, match="permission"):
        load_operator_config(path, strict=True)
