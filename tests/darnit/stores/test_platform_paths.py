"""Feature 034 T024: platform-path resolution for the `user-local` backend.

Per-platform coverage using `monkeypatch.setattr(platform, "system", ...)`.
XDG env-var overrides tested independently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.stores.defaults import platform_paths


class TestXdgDataHome:
    def test_uses_xdg_data_home_when_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert platform_paths.xdg_data_home() == tmp_path

    def test_falls_back_to_local_share_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        assert platform_paths.xdg_data_home() == Path.home() / ".local" / "share"


class TestXdgCacheHome:
    def test_uses_xdg_cache_home_when_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert platform_paths.xdg_cache_home() == tmp_path

    def test_falls_back_to_cache_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        assert platform_paths.xdg_cache_home() == Path.home() / ".cache"


class TestUserDataRoot:
    def test_linux_uses_xdg_data(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Linux"
        )
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert platform_paths.user_data_root() == tmp_path / "darnit"

    def test_linux_falls_back_to_home_local_share(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Linux"
        )
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        expected = Path.home() / ".local" / "share" / "darnit"
        assert platform_paths.user_data_root() == expected

    def test_macos_uses_apple_application_support(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Darwin"
        )
        expected = Path.home() / "Library" / "Application Support" / "darnit"
        assert platform_paths.user_data_root() == expected

    def test_windows_uses_localappdata_when_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Windows"
        )
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        expected = tmp_path / "darnit" / "Data"
        assert platform_paths.user_data_root() == expected

    def test_windows_falls_back_when_localappdata_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Windows"
        )
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        expected = (
            Path.home() / "AppData" / "Local" / "darnit" / "Data"
        )
        assert platform_paths.user_data_root() == expected

    def test_unknown_platform_uses_xdg_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "FreeBSD"
        )
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert platform_paths.user_data_root() == tmp_path / "darnit"


class TestUserCacheRoot:
    def test_linux_uses_xdg_cache(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Linux"
        )
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert platform_paths.user_cache_root() == tmp_path / "darnit"

    def test_macos_uses_apple_caches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Darwin"
        )
        expected = Path.home() / "Library" / "Caches" / "darnit"
        assert platform_paths.user_cache_root() == expected

    def test_windows_uses_localappdata_cache(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            platform_paths.platform, "system", lambda: "Windows"
        )
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        expected = tmp_path / "darnit" / "Cache"
        assert platform_paths.user_cache_root() == expected
