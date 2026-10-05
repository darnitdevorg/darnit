"""Merger precedence coverage for the ``mcp_servers`` block (spec FR-016)."""

from __future__ import annotations

from darnit.config.framework_schema import (
    FrameworkConfig,
    FrameworkMetadata,
    McpServerConfig,
)
from darnit.config.merger import merge_configs
from darnit.config.operator.schema import OperatorConfig


def _framework(**servers: McpServerConfig) -> FrameworkConfig:
    return FrameworkConfig(
        metadata=FrameworkMetadata(
            name="test",
            display_name="Test",
            version="0.0.1",
            spec_version="v0",
        ),
        mcp_servers=dict(servers),
    )


# ---------------------------------------------------------------------------
# T026: operator configuration replaces per-name (no deep merge)
# ---------------------------------------------------------------------------


def test_mcp_servers_operator_wins():
    fw = _framework(foo=McpServerConfig(command=["fw-cmd"]))
    operator = OperatorConfig(schema_version=1, mcp_servers={"foo": McpServerConfig(command=["op-cmd"])})
    eff = merge_configs(fw, operator)
    assert eff.mcp_servers["foo"].command == ["op-cmd"]


# ---------------------------------------------------------------------------
# T027: disjoint names coexist
# ---------------------------------------------------------------------------


def test_mcp_servers_disjoint_names_coexist():
    fw = _framework(a=McpServerConfig(command=["fw-a"]))
    operator = OperatorConfig(schema_version=1, mcp_servers={"b": McpServerConfig(command=["op-b"])})
    eff = merge_configs(fw, operator)
    assert set(eff.mcp_servers) == {"a", "b"}
    assert eff.mcp_servers["a"].command == ["fw-a"]
    assert eff.mcp_servers["b"].command == ["op-b"]
