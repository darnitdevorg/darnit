"""Operator configuration applied to the effective configuration (T018, T019)."""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
    McpServerConfig,
    StoreBlock,
    StoresConfig,
)
from darnit.config.merger import (
    load_user_config,
    load_user_config_with_report,
    merge_configs,
)
from darnit.config.operator.schema import OperatorConfig


def _framework() -> FrameworkConfig:
    return FrameworkConfig(
        metadata=FrameworkMetadata(name="test-framework", display_name="Test", version="1.0.0"),
        controls={
            "TEST-01": ControlConfig(
                name="One",
                level=1,
                domain="AC",
                description="First",
                passes=[HandlerInvocation(handler="file_exists", files=["ONE.md"])],
            ),
            "TEST-02": ControlConfig(name="Two", level=1, domain="AC", description="Second"),
        },
        mcp_servers={
            "shared": McpServerConfig(command=["framework-shared"]),
            "framework-only": McpServerConfig(command=["framework-only"]),
        },
        stores=StoresConfig(report=StoreBlock(backend="filesystem"), cache=StoreBlock(backend="filesystem")),
    )


def _operator(**data) -> OperatorConfig:
    return OperatorConfig.model_validate({"schema_version": 1, **data})


@pytest.mark.unit
def test_without_operator_config_nothing_changes() -> None:
    effective = merge_configs(_framework())
    assert effective.controls["TEST-01"].passes_config[0]["files"] == ["ONE.md"]
    assert set(effective.mcp_servers) == {"shared", "framework-only"}


@pytest.mark.unit
def test_operator_passes_replace_control_passes() -> None:
    operator = _operator(controls={"TEST-01": {"passes": [{"handler": "file_exists", "files": ["OPERATOR.md"]}]}})
    effective = merge_configs(_framework(), operator=operator)

    passes = effective.controls["TEST-01"].passes_config
    assert [p["handler"] for p in passes] == ["file_exists"]
    assert passes[0]["files"] == ["OPERATOR.md"]
    assert effective.controls["TEST-02"].passes_config is None


@pytest.mark.unit
def test_operator_control_for_another_framework_is_ignored() -> None:
    operator = _operator(controls={"OTHER-01": {"passes": [{"handler": "manual"}]}})
    effective = merge_configs(_framework(), operator=operator)
    assert "OTHER-01" not in effective.controls


@pytest.mark.unit
def test_operator_custom_controls_are_added() -> None:
    operator = _operator(
        custom_controls={
            "OPS-01": {
                "name": "OperatorCheck",
                "description": "Operator-defined check",
                "level": 1,
                "domain": "OP",
                "passes": [{"handler": "file_exists", "files": ["OPS.md"]}],
            }
        }
    )
    effective = merge_configs(_framework(), operator=operator)

    custom = effective.controls["OPS-01"]
    assert custom.name == "OperatorCheck"
    assert custom.passes_config[0]["files"] == ["OPS.md"]


@pytest.mark.unit
def test_operator_mcp_servers_replace_by_name() -> None:
    operator = _operator(mcp_servers={"shared": {"command": ["operator-shared"]}, "extra": {"command": ["x"]}})
    effective = merge_configs(_framework(), operator=operator)

    assert effective.mcp_servers["shared"].command == ["operator-shared"]
    assert effective.mcp_servers["framework-only"].command == ["framework-only"]
    assert effective.mcp_servers["extra"].command == ["x"]


@pytest.mark.unit
def test_operator_stores_override_per_kind() -> None:
    operator = _operator(stores={"report": {"backend": "operator-backend"}})
    effective = merge_configs(_framework(), operator=operator)

    assert effective.stores.report.backend == "operator-backend"
    assert effective.stores.cache.backend == "filesystem"


@pytest.mark.unit
def test_plugins_allowed_refuses_other_frameworks() -> None:
    with pytest.raises(ValueError, match="plugins.allowed"):
        merge_configs(_framework(), operator=_operator(plugins={"allowed": ["openssf-baseline"]}))

    effective = merge_configs(_framework(), operator=_operator(plugins={"allowed": ["test-framework"]}))
    assert effective.framework_name == "test-framework"


@pytest.mark.unit
def test_repository_config_cannot_supply_what_operator_config_does(tmp_path: Path) -> None:
    (tmp_path / ".baseline.toml").write_text(
        '[mcp_servers.shared]\ncommand = ["repo-shared"]\n\n[controls."TEST-02"]\npasses = [{ handler = "manual" }]\n',
        encoding="utf-8",
    )
    operator = _operator(controls={"TEST-01": {"passes": [{"handler": "file_exists", "files": ["OPERATOR.md"]}]}})
    effective = merge_configs(_framework(), load_user_config(tmp_path), operator=operator)

    assert effective.mcp_servers["shared"].command == ["framework-shared"]
    assert effective.controls["TEST-02"].passes_config is None
    assert effective.controls["TEST-01"].passes_config[0]["files"] == ["OPERATOR.md"]


@pytest.mark.unit
def test_load_user_config_with_report_lists_ignored_keys(tmp_path: Path) -> None:
    (tmp_path / ".baseline.toml").write_text(
        'extends = "openssf-baseline"\n\n[stores.report]\nbackend = "filesystem"\n\n'
        '[controls."TEST-01"]\nstatus = "n/a"\nreason = "not here"\npasses = [{ handler = "manual" }]\n',
        encoding="utf-8",
    )

    user, ignored = load_user_config_with_report(tmp_path)

    assert user is not None
    assert user.extends == "openssf-baseline"
    assert {(s.file, s.key, s.new_home) for s in ignored} == {
        (".baseline.toml", "stores", "operator configuration"),
        (".baseline.toml", "controls.TEST-01.passes", "operator configuration"),
    }


@pytest.mark.unit
def test_load_user_config_with_report_without_file(tmp_path: Path) -> None:
    assert load_user_config_with_report(tmp_path) == (None, [])
