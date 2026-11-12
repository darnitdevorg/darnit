"""Tests for darnit.core.discovery module."""

import logging
from pathlib import Path

import pytest

from darnit.core.discovery import (
    clear_cache,
    discover_implementations,
    get_implementation,
)


class TestDiscoverImplementations:
    """Tests for discover_implementations function."""

    @pytest.fixture(autouse=True)
    def clear_discovery_cache(self):
        """Clear cache before each test."""
        clear_cache()
        yield
        clear_cache()

    @pytest.mark.unit
    def test_discovers_openssf_baseline(self):
        """Test that openssf-baseline implementation is discovered."""
        implementations = discover_implementations()
        assert "openssf-baseline" in implementations

    @pytest.mark.unit
    def test_clear_cache_works(self):
        """Test that clear_cache resets the cache."""
        impl1 = discover_implementations()
        clear_cache()
        impl2 = discover_implementations()
        # Should be different dict objects after cache clear
        assert impl1 is not impl2


class TestGetImplementation:
    """Tests for get_implementation function."""

    @pytest.fixture(autouse=True)
    def clear_discovery_cache(self):
        """Clear cache before each test."""
        clear_cache()
        yield
        clear_cache()

    @pytest.mark.unit
    def test_get_existing_implementation(self):
        """Test getting an existing implementation by name."""
        impl = get_implementation("openssf-baseline")
        assert impl is not None
        assert impl.name == "openssf-baseline"

    @pytest.mark.unit
    def test_get_nonexistent_implementation(self):
        """Test getting a nonexistent implementation returns None."""
        impl = get_implementation("nonexistent-implementation")
        assert impl is None


class TestNoPluginVerification:
    """darnit does not verify plugin signatures (framework-design 6.6, Appendix C)."""

    @pytest.fixture(autouse=True)
    def clear_discovery_cache(self):
        clear_cache()
        yield
        clear_cache()

    @pytest.mark.unit
    def test_discovery_logs_no_verification_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="darnit"):
            implementations = discover_implementations()

        assert "openssf-baseline" in implementations
        assert [r.getMessage() for r in caplog.records if "verif" in r.getMessage().lower()] == []
        assert [r.getMessage() for r in caplog.records if r.name == "darnit.core.discovery" and r.levelno >= logging.WARNING] == []

    @pytest.mark.unit
    def test_discovery_writes_nothing_under_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        assert discover_implementations()
        assert get_implementation("openssf-baseline") is not None

        assert sorted(home.rglob("*")) == []
