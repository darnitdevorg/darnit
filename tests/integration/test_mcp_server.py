"""Integration tests for darnit MCP server.

These tests start the actual MCP server and connect to it as a client,
simulating how Claude Code would interact with the server.
"""

import json
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

# Configure pytest-asyncio and mark as integration test
pytestmark = [
    pytest.mark.asyncio(loop_scope="function"),
    pytest.mark.integration,
]

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import get_default_environment, stdio_client

# Path to the openssf-baseline.toml config
BASELINE_TOML = Path(str(files("darnit_baseline") / "openssf-baseline.toml"))


@pytest.fixture(scope="module", autouse=True)
def require_baseline_toml():
    """Ensure openssf-baseline.toml is present; fail if missing so tests do not go dark silently."""
    assert BASELINE_TOML.is_file(), f"openssf-baseline.toml not found at {BASELINE_TOML}"


@pytest.fixture
def mcp_server_params(tmp_path):
    """Build isolated environment and StdioServerParameters launching darnit directly."""
    # Preserve existing tree-sitter language pack cache so the spawned server doesn't download over network
    real_home = Path.home()
    for rel in ("Library/Caches/tree-sitter-language-pack", ".cache/tree-sitter-language-pack"):
        src = real_home / rel
        if src.exists():
            dest = tmp_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.symlink_to(src)
            except OSError:
                pass

    env = get_default_environment()
    env["HOME"] = str(tmp_path)
    env["XDG_CONFIG_HOME"] = str(tmp_path / ".config")
    env["XDG_DATA_HOME"] = str(tmp_path / ".local" / "share")
    darnit_bin = Path(sys.executable).with_name("darnit")
    return StdioServerParameters(
        command=str(darnit_bin),
        args=["serve", str(BASELINE_TOML)],
        env=env,
    )


@pytest.fixture
def test_repo(tmp_path):
    """Create a minimal test repository for auditing."""
    repo = tmp_path / "test-repo"
    repo.mkdir(parents=True, exist_ok=True)
    # Create basic repo structure
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text('[remote "origin"]\n\turl = https://github.com/test-org/test-repo.git\n')
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    # Create a README
    (repo / "README.md").write_text("# Test Repository\n\nA test repo for integration testing.\n")

    # Create a LICENSE
    (repo / "LICENSE").write_text("MIT License\n\nCopyright 2024 Test Org\n")

    return repo


class TestMCPServerIntegration:
    """Integration tests that start the MCP server and call tools."""

    @pytest.mark.asyncio
    async def test_server_starts_and_lists_tools(self, mcp_server_params):
        """Test that the server starts and exposes tools."""
        async with stdio_client(mcp_server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the session
                await session.initialize()

                # List available tools
                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]

                # Verify all 22 expected tools are present
                expected_tools = [
                    # Audit
                    "audit_openssf_baseline",
                    "list_available_checks",
                    "audit_org",
                    # Configuration
                    "get_project_config",
                    "init_project_config",
                    "confirm_project_data",
                    "get_pending_data",
                    # Threat Model & Attestation
                    "generate_threat_model",
                    "generate_attestation",
                    # Remediation
                    "create_security_policy",
                    "enable_branch_protection",
                    "remediate_audit_findings",
                    # Git Workflow
                    "create_remediation_branch",
                    "commit_remediation_changes",
                    "create_remediation_pr",
                    "get_remediation_status",
                    # Org & Test Repository
                    "list_org_repos",
                    "create_test_repository",
                    # Harness Loop (Feature 025)
                    "run_next_action",
                    "submit_action_result",
                    # Judgments & Candidates (Feature 041)
                    "submit_judgment",
                    "confirm_pass_candidate",
                ]
                for tool in expected_tools:
                    assert tool in tool_names, f"Missing tool: {tool}"

                # Should have exactly 22 tools
                assert len(tool_names) == 22, f"Expected 22 tools, got {len(tool_names)}: {tool_names}"

    @pytest.mark.asyncio
    async def test_list_available_checks(self, mcp_server_params):
        """Test calling the list_available_checks tool."""
        async with stdio_client(mcp_server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call list_available_checks
                result = await session.call_tool("list_available_checks", {})

                # Parse the result
                assert result.content
                content = result.content[0]
                assert content.type == "text"

                checks = json.loads(content.text)

                # Verify structure
                assert "level1" in checks
                assert "level2" in checks
                assert "level3" in checks
                assert len(checks["level1"]) > 0

    @pytest.mark.asyncio
    async def test_audit_on_test_repo(self, test_repo, mcp_server_params):
        """Test running an audit on a test repository."""
        async with stdio_client(mcp_server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call audit_openssf_baseline
                result = await session.call_tool(
                    "audit_openssf_baseline",
                    {
                        "local_path": str(test_repo),
                        "level": 1,  # Just level 1 for speed
                        "output_format": "json",
                    },
                )

                # Parse the result
                assert result.content
                content = result.content[0]
                assert content.type == "text"

                # Should be valid JSON
                audit_result = json.loads(content.text)

                # Verify structure
                assert "owner" in audit_result
                assert "repo" in audit_result
                assert "results" in audit_result
                assert "summary" in audit_result

                # Should have some results
                assert len(audit_result["results"]) > 0

    @pytest.mark.asyncio
    async def test_audit_with_tags_filter(self, test_repo, mcp_server_params):
        """Test running an audit with tags filtering."""
        async with stdio_client(mcp_server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call audit_openssf_baseline with tags filter for VM domain only
                result = await session.call_tool(
                    "audit_openssf_baseline",
                    {
                        "local_path": str(test_repo),
                        "level": 1,
                        "tags": "domain=VM",  # Filter to VM domain only
                        "output_format": "json",
                    },
                )

                # Parse the result
                assert result.content
                content = result.content[0]
                assert content.type == "text"

                # Should be valid JSON
                audit_result = json.loads(content.text)

                # Should have results
                assert "results" in audit_result
                results = audit_result["results"]
                assert results

                # All returned controls should belong to the VM domain
                baseline_controls = tomllib.loads(BASELINE_TOML.read_text(encoding="utf-8")).get("controls", {})
                for r in results:
                    control_id = r.get("id", "")
                    assert control_id in baseline_controls, f"Unknown control: {control_id}"
                    ctrl = baseline_controls[control_id]
                    domain = ctrl.get("domain") or ctrl.get("tags", {}).get("domain")
                    assert domain == "VM", f"Expected VM domain control, got {control_id} with domain {domain}"

    @pytest.mark.asyncio
    async def test_get_project_config_no_config(self, test_repo, mcp_server_params):
        """Test get_project_config when no config exists."""
        async with stdio_client(mcp_server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call get_project_config
                result = await session.call_tool(
                    "get_project_config",
                    {"local_path": str(test_repo)},
                )

                assert result.content
                content = result.content[0]
                assert content.type == "text"

                # Should indicate no config found
                assert "No .project.yaml found" in content.text or "init_project_config" in content.text

    @pytest.mark.asyncio
    async def test_get_pending_data_and_confirm_project_data(self, test_repo, mcp_server_params):
        """Test get_pending_data and confirm_project_data round trip."""
        async with stdio_client(mcp_server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call get_pending_data before confirm
                pending_res = await session.call_tool(
                    "get_pending_data",
                    {
                        "local_path": str(test_repo),
                        "owner": "test-org",
                        "repo": "test-repo",
                    },
                )
                assert pending_res.content
                content_before = pending_res.content[0].text
                assert "AskUserQuestion" in content_before
                parsed_before = json.loads(content_before.split("\n---\n", 1)[-1])
                keys_before = [q["key"] for q in parsed_before.get("questions", [])]
                assert "security_contact" in keys_before

                # Call confirm_project_data
                confirm_res = await session.call_tool(
                    "confirm_project_data",
                    {
                        "local_path": str(test_repo),
                        "owner": "test-org",
                        "repo": "test-repo",
                        "security_contact": "security@test-org.com",
                    },
                )
                assert confirm_res.content
                assert "security_contact: confirmed" in confirm_res.content[0].text

                # Call get_pending_data after confirm; security_contact should now be gone
                after_res = await session.call_tool(
                    "get_pending_data",
                    {
                        "local_path": str(test_repo),
                        "owner": "test-org",
                        "repo": "test-repo",
                    },
                )
                assert after_res.content
                content_after = after_res.content[0].text
                parsed_after = json.loads(content_after.split("\n---\n", 1)[-1])
                keys_after = [q["key"] for q in parsed_after.get("questions", [])]
                assert "security_contact" not in keys_after


class TestMCPServerToolDescriptions:
    """Test that tool descriptions are properly exposed."""

    @pytest.mark.asyncio
    async def test_tool_descriptions_are_set(self, mcp_server_params):
        """Test that tools have descriptions from TOML."""
        async with stdio_client(mcp_server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools_result = await session.list_tools()

                # Find audit tool
                audit_tool = next(
                    (t for t in tools_result.tools if t.name == "audit_openssf_baseline"),
                    None,
                )

                assert audit_tool is not None
                assert audit_tool.description
                assert "audit" in audit_tool.description.lower()


class TestMCPServerErrorHandling:
    """Test error handling in the MCP server."""

    @pytest.mark.asyncio
    async def test_audit_nonexistent_path(self, mcp_server_params):
        """Test audit with a non-existent path returns error gracefully."""
        async with stdio_client(mcp_server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call audit with non-existent path
                result = await session.call_tool(
                    "audit_openssf_baseline",
                    {"local_path": "/nonexistent/path/to/repo"},
                )

                assert result.content
                content = result.content[0]

                # Should contain error message, not crash
                assert "Error" in content.text or "not found" in content.text.lower()
