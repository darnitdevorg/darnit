"""Tests for entry-point discovery.

Feature 033 T018.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from darnit.stores import discovery
from darnit.stores.errors import StoreNameCollision


@pytest.fixture(autouse=True)
def _reset_discovery_cache():
    discovery._reset_discovery_cache()
    yield
    discovery._reset_discovery_cache()


def _make_fake_ep(name: str, cls, package_name: str = "fake-pkg"):
    """Construct a fake importlib.metadata.EntryPoint-like object."""
    ep = MagicMock()
    ep.name = name
    ep.value = f"{cls.__module__}:{cls.__qualname__}"
    ep.load.return_value = cls
    dist = MagicMock()
    dist.metadata = {"Name": package_name}
    ep.dist = dist
    return ep


class TestDiscoveryHappyPath:
    def test_empty_group_returns_empty_dict(self, monkeypatch):
        monkeypatch.setattr(
            discovery.metadata, "entry_points", lambda group=None: []
        )
        assert discovery.discover_stores("darnit.stores.project") == {}

    def test_one_entry_point_registered(self, monkeypatch):
        class FakeBackend:
            pass

        ep = _make_fake_ep("fake", FakeBackend, "fake-pkg")
        monkeypatch.setattr(
            discovery.metadata, "entry_points", lambda group=None: [ep]
        )
        result = discovery.discover_stores("darnit.stores.project")
        assert result == {"fake": FakeBackend}

    def test_result_cached_across_calls(self, monkeypatch):
        calls = {"n": 0}

        class Fake:
            pass

        def _ep(*a, **kw):
            calls["n"] += 1
            return [_make_fake_ep("f", Fake, "pkg")]

        monkeypatch.setattr(discovery.metadata, "entry_points", _ep)
        discovery.discover_stores("darnit.stores.project")
        discovery.discover_stores("darnit.stores.project")
        # Second call must NOT re-query entry_points.
        assert calls["n"] == 1


class TestNameCollision:
    def test_collision_raises(self, monkeypatch):
        class BackendA:
            pass

        class BackendB:
            pass

        eps = [
            _make_fake_ep("shared", BackendA, "pkg-a"),
            _make_fake_ep("shared", BackendB, "pkg-b"),
        ]
        monkeypatch.setattr(
            discovery.metadata, "entry_points", lambda group=None: eps
        )
        with pytest.raises(StoreNameCollision) as exc:
            discovery.discover_stores("darnit.stores.attestation")
        assert exc.value.name == "shared"
        # Both packages appear in the exception's message for operator visibility.
        assert "pkg-a" in str(exc.value)
        assert "pkg-b" in str(exc.value)


class TestBrokenPluginSkipped:
    def test_broken_load_logs_and_skips(self, monkeypatch, caplog):
        class GoodBackend:
            pass

        class _Placeholder:
            pass

        broken_ep = _make_fake_ep("bad", _Placeholder, "broken-pkg")
        broken_ep.load.side_effect = ImportError("kaboom")
        good_ep = _make_fake_ep("good", GoodBackend, "good-pkg")

        monkeypatch.setattr(
            discovery.metadata,
            "entry_points",
            lambda group=None: [broken_ep, good_ep],
        )
        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="darnit.stores.discovery"):
            result = discovery.discover_stores("darnit.stores.project")
        # Broken plugin skipped; good one still discovered.
        assert result == {"good": GoodBackend}
        assert any("failed to load" in rec.message for rec in caplog.records)
