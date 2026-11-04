"""Unit tests for darnit-testchecks reference store backends (feature 033 T020)."""

from __future__ import annotations

import importlib.metadata
from unittest.mock import MagicMock

import pytest
from darnit_testchecks.stores import (
    InMemoryAttestationStore,
    InMemoryAuditCacheStore,
    InMemoryProjectStateStore,
    InMemoryReportStore,
)


@pytest.mark.unit
class TestInMemoryProjectStateStore:
    """Tests for InMemoryProjectStateStore."""

    def test_empty_initialization(self) -> None:
        store = InMemoryProjectStateStore()
        assert store.project is None
        assert store.read_count == 0
        assert store.read_project() is None
        assert store.read_count == 1
        assert store.close() is None

    def test_seeded_initialization_and_read_count(self) -> None:
        mock_config = MagicMock()
        mock_config.repo = "owner/repo"
        store = InMemoryProjectStateStore(project=mock_config)

        assert store.project == mock_config
        assert store.read_count == 0

        first_read = store.read_project()
        assert first_read == mock_config
        assert store.read_count == 1

        second_read = store.read_project()
        assert second_read == mock_config
        assert store.read_count == 2


@pytest.mark.unit
class TestInMemoryReportStore:
    """Tests for InMemoryReportStore."""

    def test_write_formats(self) -> None:
        store = InMemoryReportStore()
        assert store._state == {}

        store.write_markdown("rep-001", "# Markdown Report")
        assert store._state[("rep-001", "md")] == "# Markdown Report"

        store.write_json("rep-001", '{"status": "PASS"}')
        assert store._state[("rep-001", "json")] == '{"status": "PASS"}'

        store.write_sarif("rep-001", '{"$schema": "sarif"}')
        assert store._state[("rep-001", "sarif")] == '{"$schema": "sarif"}'

        assert len(store._state) == 3
        assert store.close() is None


@pytest.mark.unit
class TestInMemoryAttestationStore:
    """Tests for InMemoryAttestationStore."""

    def test_write_and_state_accumulation(self) -> None:
        store = InMemoryAttestationStore()
        assert store._state == []

        payload_1 = b'{"bundle": 1}'
        store.write("bundle-1", payload_1, "application/vnd.in-toto+json")
        assert store._state == [("bundle-1", payload_1, "application/vnd.in-toto+json")]

        payload_2 = b'{"bundle": 2}'
        store.write("bundle-2", payload_2, "application/json")
        assert len(store._state) == 2
        assert store._state[1] == ("bundle-2", payload_2, "application/json")

        assert store.close() is None


@pytest.mark.unit
class TestInMemoryAuditCacheStore:
    """Tests for InMemoryAuditCacheStore."""

    def test_cache_miss_returns_none(self) -> None:
        store = InMemoryAuditCacheStore()
        assert store.read("nonexistent_key") is None
        assert store.close() is None

    def test_cache_hit_returns_stored_payload(self) -> None:
        store = InMemoryAuditCacheStore()
        data = {"findings": ["F1"], "verdict": "PASS"}
        store.write("cache_hash_1", data)

        cached = store.read("cache_hash_1")
        assert cached == data
        assert cached is not data  # Returns a copy of dict

    def test_cache_write_swallows_exceptions(self) -> None:
        store = InMemoryAuditCacheStore()

        class ExplodingDict:
            def keys(self):
                raise RuntimeError("Boom!")

        # FR-011: write must not raise
        store.write("exploding_key", ExplodingDict())  # type: ignore[arg-type]
        assert store.read("exploding_key") is None


@pytest.mark.unit
class TestStoreDiscoveryEntryPoints:
    """Tests verifying registration under standard darnit plugin entry points."""

    @pytest.mark.parametrize(
        ("group", "name", "expected_cls"),
        [
            ("darnit.stores.project", "in-memory", InMemoryProjectStateStore),
            ("darnit.stores.report", "in-memory", InMemoryReportStore),
            ("darnit.stores.attestation", "in-memory", InMemoryAttestationStore),
            ("darnit.stores.cache", "in-memory", InMemoryAuditCacheStore),
        ],
    )
    def test_store_entry_points_resolve(self, group: str, name: str, expected_cls: type) -> None:
        eps = [ep for ep in importlib.metadata.entry_points(group=group) if ep.name == name]
        assert len(eps) == 1
        loaded_cls = eps[0].load()
        assert loaded_cls is expected_cls
