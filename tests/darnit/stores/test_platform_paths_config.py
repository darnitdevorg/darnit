"""User configuration directory resolution (feature 040, research R1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.stores.defaults import platform_paths


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "APPDATA"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.mark.unit
@pytest.mark.parametrize("system", ["Linux", "Darwin", "FreeBSD"])
def test_defaults_to_dot_config(home: Path, monkeypatch: pytest.MonkeyPatch, system: str) -> None:
    """macOS uses ~/.config like Linux, matching gh, uv, ruff, and git."""
    monkeypatch.setattr(platform_paths.platform, "system", lambda: system)
    assert platform_paths.user_config_dir() == home / ".config" / "darnit"


@pytest.mark.unit
@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_absolute_xdg_config_home_is_honored(
    home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, system: str
) -> None:
    monkeypatch.setattr(platform_paths.platform, "system", lambda: system)
    custom = tmp_path / "cfg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom))
    assert platform_paths.user_config_dir() == custom / "darnit"


@pytest.mark.unit
def test_relative_xdg_config_home_is_ignored(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The XDG spec says relative values are invalid and must be ignored."""
    monkeypatch.setattr(platform_paths.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/dir")
    assert platform_paths.user_config_dir() == home / ".config" / "darnit"


@pytest.mark.unit
def test_windows_uses_appdata(home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(platform_paths.platform, "system", lambda: "Windows")
    appdata = tmp_path / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    assert platform_paths.user_config_dir() == appdata / "darnit"


@pytest.mark.unit
@pytest.mark.parametrize(("var", "func"), [("XDG_DATA_HOME", "xdg_data_home"), ("XDG_CACHE_HOME", "xdg_cache_home")])
def test_relative_xdg_data_and_cache_values_are_ignored(
    home: Path, monkeypatch: pytest.MonkeyPatch, var: str, func: str
) -> None:
    monkeypatch.setenv(var, "relative/dir")
    default = home / (".local/share" if var == "XDG_DATA_HOME" else ".cache")
    assert getattr(platform_paths, func)() == default
