"""Each server's confirm_project_data covers only its own framework's keys (feature 042, T039a).

contracts/context-confirmation-tools.md, "Which server exposes it".
"""

from __future__ import annotations

import asyncio
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from darnit.server.tools.project_data import confirm_project_data_impl

BASELINE_KEYS = {
    "maintainers",
    "security_contact",
    "governance_model",
    "has_subprojects",
    "has_releases",
    "is_library",
    "has_compiled_assets",
    "ci_provider",
    "platform",
}
CSL_KEYS = {
    "csl_spec_name",
    "csl_working_group_scope",
    "csl_coc_contacts",
    "csl_coc_policy",
    "csl_coc_reference",
    "csl_governance_mode",
    "csl_governance_reference",
    "csl_code_license",
}
NEUTRAL_PARAMETERS = {
    "accept_candidates",
    "confirm_stored",
    "reject_stored",
    "expires_at",
    "owner",
    "repo",
    "host",
    "local_path",
}


def _tools(toml: Path) -> dict:
    from darnit.server.factory import create_server

    server = create_server(toml)
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _framework_server(tmp_path: Path, framework: str):
    """A server for ``framework`` whose own TOML declares no MCP tools."""
    from darnit.server.factory import create_server

    config = tmp_path / "framework.toml"
    config.write_text(f'[metadata]\nname = "{framework}"\n\n[mcp]\nname = "t"\n', encoding="utf-8")
    return create_server(config)


def _csl_toml() -> Path:
    return Path(str(files("darnit_csl") / "community-spec.toml"))


def _baseline_toml() -> Path:
    return Path(str(files("darnit_baseline") / "openssf-baseline.toml"))


@pytest.mark.unit
class TestExposedParameters:
    def test_csl_server_exposes_a_neutral_tool_with_only_csl_keys(self) -> None:
        tool = _tools(_csl_toml())["confirm_project_data"]

        assert set(tool.inputSchema["properties"]) == CSL_KEYS | NEUTRAL_PARAMETERS

    def test_baseline_tool_exposes_only_baseline_keys(self) -> None:
        properties = set(_tools(_baseline_toml())["confirm_project_data"].inputSchema["properties"])

        assert BASELINE_KEYS | NEUTRAL_PARAMETERS <= properties
        assert {"confirm_not_applicable", "confirm_pass_candidate"} <= properties
        assert not properties & CSL_KEYS
        assert "project_name" not in properties

    def test_python_tool_exposes_only_baseline_keys(self) -> None:
        import inspect

        from darnit_baseline.tools import confirm_project_data_tool

        parameters = set(inspect.signature(confirm_project_data_tool()).parameters)

        assert BASELINE_KEYS <= parameters
        assert not parameters & CSL_KEYS
        assert "project_name" not in parameters

    def test_every_framework_server_without_its_own_tool_gets_the_neutral_one(self, tmp_path: Path) -> None:
        server = _framework_server(tmp_path, "community-spec")
        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

        assert set(tools["confirm_project_data"].inputSchema["properties"]) == CSL_KEYS | NEUTRAL_PARAMETERS

    def test_framework_without_context_keys_gets_no_confirm_tool(self, tmp_path: Path) -> None:
        server = _framework_server(tmp_path, "hello")
        tools = {tool.name for tool in asyncio.run(server.list_tools())}

        assert "confirm_project_data" not in tools


@pytest.mark.integration
class TestRecording:
    def test_neutral_tool_records_a_csl_value(self, temp_git_repo: Path, trusted_target: tuple[str, str]) -> None:
        from darnit.config.operator.loader import get_launch_options
        from darnit.server.factory import create_server

        owner, repo = trusted_target
        # As `darnit serve --operator-config` does: the server keeps the trusting configuration.
        server = create_server(_csl_toml(), operator_config_path=get_launch_options().path)

        asyncio.run(
            server.call_tool(
                "confirm_project_data",
                {"csl_coc_policy": "umbrella", "owner": owner, "repo": repo, "local_path": str(temp_git_repo)},
            )
        )

        data = yaml.safe_load((temp_git_repo / ".project" / "darnit.yaml").read_text())
        assert data["context"]["csl_coc_policy"] == "umbrella"
        assert "csl_coc_policy" in data["confirmations"]

    @pytest.mark.parametrize(
        ("framework", "key", "value"),
        [("openssf-baseline", "csl_coc_policy", "umbrella"), ("community-spec", "maintainers", ["@alice"])],
    )
    def test_another_frameworks_key_is_refused(
        self, temp_git_repo: Path, trusted_target: tuple[str, str], framework: str, key: str, value: object
    ) -> None:
        owner, repo = trusted_target

        message = confirm_project_data_impl(
            local_path=str(temp_git_repo), owner=owner, repo=repo, framework_name=framework, **{key: value}
        )

        assert f"{key}: refused:" in message
        assert not (temp_git_repo / ".project").exists()
