"""Unit tests for the shared helpers in ``darnit.stores.defaults.local_fs``.

Feature 034 T005. Covers ``_resolve_root_config`` per data-model E-001 +
research R-003.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.stores.defaults.local_fs import _resolve_root_config


class TestResolveRootConfig:
    def test_path_input_returned_verbatim(self, tmp_path: Path) -> None:
        """A :class:`Path` argument is a test-only shortcut and is
        returned unchanged (no `~` expansion, no `$VAR`)."""
        result = _resolve_root_config(tmp_path)
        assert result == tmp_path

    def test_absolute_string_resolved_to_path(self, tmp_path: Path) -> None:
        result = _resolve_root_config(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_tilde_expansion(self) -> None:
        home = Path.home()
        result = _resolve_root_config("~/darnit-test-subdir")
        assert result == (home / "darnit-test-subdir").resolve()

    def test_env_var_expansion(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("DARNIT_TEST_ROOT", str(tmp_path))
        result = _resolve_root_config("$DARNIT_TEST_ROOT/attestations")
        assert result == (tmp_path / "attestations").resolve()

    def test_missing_env_var_raises_keyerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ensure the var is unset (in case something else set it).
        monkeypatch.delenv("DARNIT_TEST_MISSING", raising=False)
        with pytest.raises(KeyError):
            _resolve_root_config("$DARNIT_TEST_MISSING/attestations")

    def test_combined_tilde_and_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Order: substitute $VAR first, then expand ~."""
        monkeypatch.setenv("DARNIT_TEST_SUBDIR", "sub")
        home = Path.home()
        result = _resolve_root_config("~/$DARNIT_TEST_SUBDIR/leaf")
        assert result == (home / "sub" / "leaf").resolve()

    def test_env_var_referencing_home_still_expands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `$VAR` whose VALUE contains `~` still gets ~-expanded because
        expansion runs AFTER substitution (data-model E-001)."""
        monkeypatch.setenv("DARNIT_TEST_HOME_LIKE", "~/darnit")
        home = Path.home()
        result = _resolve_root_config("$DARNIT_TEST_HOME_LIKE/x")
        assert result == (home / "darnit" / "x").resolve()

    def test_bad_type_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            _resolve_root_config(123)  # type: ignore[arg-type]


class TestPlatformPathsPublicApi:
    """Smoke check that the four public helpers are importable and callable.

    Detailed platform-specific behavior lives in
    ``test_platform_paths.py`` (T024).
    """

    def test_xdg_data_home_returns_path(self) -> None:
        from darnit.stores.defaults.platform_paths import xdg_data_home

        assert isinstance(xdg_data_home(), Path)

    def test_xdg_cache_home_returns_path(self) -> None:
        from darnit.stores.defaults.platform_paths import xdg_cache_home

        assert isinstance(xdg_cache_home(), Path)

    def test_user_data_root_returns_path(self) -> None:
        from darnit.stores.defaults.platform_paths import user_data_root

        assert isinstance(user_data_root(), Path)

    def test_user_cache_root_returns_path(self) -> None:
        from darnit.stores.defaults.platform_paths import user_cache_root

        assert isinstance(user_cache_root(), Path)
