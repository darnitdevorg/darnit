"""Tests for the builtin_list_controls MCP tool."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from darnit.server.tools.builtin_list import builtin_list_controls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_framework_name_returns_error() -> None:
    output = await builtin_list_controls(_framework_name="")
    assert output == "Error: No framework name configured for this tool."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_framework_name_returns_error() -> None:
    output = await builtin_list_controls(_framework_name="nonexistent_framework_xyz")
    assert output.startswith("Error loading framework config 'nonexistent_framework_xyz':")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_controls_failure_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import darnit.config

    monkeypatch.setattr(
        darnit.config,
        "load_controls_from_effective",
        MagicMock(side_effect=RuntimeError("Corrupt TOML control table")),
    )
    output = await builtin_list_controls(_framework_name="hello")
    assert output == "Error loading controls: Corrupt TOML control table"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_valid_framework_hello_structure() -> None:
    raw = await builtin_list_controls(_framework_name="hello")
    data = json.loads(raw)

    assert data["framework"] == "hello"
    assert data["total"] == 1
    assert "level_1" in data

    lvl1 = data["level_1"]
    assert lvl1["count"] == 1
    assert lvl1["domains"] == ["HELLO"]
    assert len(lvl1["controls"]) == 1

    ctrl = lvl1["controls"][0]
    assert ctrl["id"] == "HELLO-01.01"
    assert ctrl["name"] == "ReadmeExists"
    assert "README" in ctrl["description"]
    assert ctrl["domain"] == "HELLO"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_valid_framework_openssf_baseline_levels() -> None:
    raw = await builtin_list_controls(_framework_name="openssf-baseline")
    data = json.loads(raw)

    assert data["framework"] == "openssf-baseline"
    assert data["total"] > 0
    # Baseline defines level_1, level_2, and level_3 controls
    assert "level_1" in data
    assert "level_2" in data
    assert "level_3" in data

    for lvl_key in ("level_1", "level_2", "level_3"):
        lvl = data[lvl_key]
        assert lvl["count"] == len(lvl["controls"])
        assert isinstance(lvl["domains"], list)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merges_python_registry_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    from darnit.sieve.registry import get_control_registry

    @dataclass
    class MockSpec:
        control_id: str
        name: str
        description: str
        domain: str = "CUSTOM"
        level: int = 2

    extra_spec = MockSpec(
        control_id="CUSTOM-99.99",
        name="CustomPythonControl",
        description="A control registered only via Python registry",
    )

    registry = get_control_registry()
    monkeypatch.setattr(registry, "get_all_specs", lambda: [extra_spec])

    raw = await builtin_list_controls(_framework_name="hello")
    data = json.loads(raw)

    assert data["total"] == 2
    assert "level_2" in data
    assert data["level_2"]["count"] == 1
    assert data["level_2"]["controls"][0]["id"] == "CUSTOM-99.99"
    assert data["level_2"]["controls"][0]["name"] == "CustomPythonControl"
