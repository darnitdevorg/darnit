"""Integration tests for darnit MCP server.

These tests start the actual MCP server and connect to it as a client,
simulating how Claude Code would interact with the server.
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

# Configure pytest-asyncio
pytestmark = pytest.mark.asyncio(loop_scope="function")

from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession
from mcp import StdioServerParameters


# Path to the openssf-baseline.toml config
BASELINE_TOML = (
    Path(__file__).parent.parent.parent
    / "packages"
    / "darnit-baseline"
    / "openssf-baseline.toml"
)


@pytest.fixture
def test_repo(tmp_path):
    """Create a minimal test repository for auditing."""
    # Create basic repo structure
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text(
        "[remote \"origin\"]\n\turl = https://github.com/test-org/test-repo.git\n"
    )
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    # Create a README
    (tmp_path / "README.md").write_text("# Test Repository\n\nA test repo for integration testing.\n")

    # Create a LICENSE
    (tmp_path / "LICENSE").write_text("MIT License\n\nCopyright 2024 Test Org\n")

    return tmp_path


class TestMCPServerIntegration:
    """Integration tests that start the MCP server and call tools."""

    @pytest.mark.asyncio
    async def test_server_starts_and_lists_tools(self):
        """Test that the server starts and exposes tools."""
        if not BASELINE_TOML.exists():
            pytest.skip("openssf-baseline.toml not found")

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "darnit", "serve", str(BASELINE_TOML)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the session
                await session.initialize()

                # List available tools
                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]

                # Verify all 15 expected tools are present
                expected_tools = [
                    # Audit
                    "audit_openssf_baseline",
                    "list_available_checks",
                    # Configuration
                    "get_project_config",
                    "init_project_config",
                    "confirm_project_context",
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
                    # Test Repository
                    "create_test_repository",
                ]
                for tool in expected_tools:
                    assert tool in tool_names, f"Missing tool: {tool}"

                # Should have exactly 15 tools
                assert len(tool_names) == 15, f"Expected 15 tools, got {len(tool_names)}: {tool_names}"

    @pytest.mark.asyncio
    async def test_list_available_checks(self):
        """Test calling the list_available_checks tool."""
        if not BASELINE_TOML.exists():
            pytest.skip("openssf-baseline.toml not found")

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "darnit", "serve", str(BASELINE_TOML)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
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
    async def test_audit_on_test_repo(self, test_repo):
        """Test running an audit on a test repository."""
        if not BASELINE_TOML.exists():
            pytest.skip("openssf-baseline.toml not found")

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "darnit", "serve", str(BASELINE_TOML)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
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
    async def test_audit_with_tags_filter(self, test_repo):
        """Test running an audit with tags filtering."""
        if not BASELINE_TOML.exists():
            pytest.skip("openssf-baseline.toml not found")

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "darnit", "serve", str(BASELINE_TOML)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
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

                # All results should be from VM domain
                for r in results:
                    control_id = r.get("id", "")
                    assert "VM" in control_id, f"Expected VM domain control, got {control_id}"

    @pytest.mark.asyncio
    async def test_get_project_config_no_config(self, test_repo):
        """Test get_project_config when no config exists."""
        if not BASELINE_TOML.exists():
            pytest.skip("openssf-baseline.toml not found")

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "darnit", "serve", str(BASELINE_TOML)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
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


class TestMCPServerToolDescriptions:
    """Test that tool descriptions are properly exposed."""

    @pytest.mark.asyncio
    async def test_tool_descriptions_are_set(self):
        """Test that tools have descriptions from TOML."""
        if not BASELINE_TOML.exists():
            pytest.skip("openssf-baseline.toml not found")

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "darnit", "serve", str(BASELINE_TOML)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
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
    async def test_audit_nonexistent_path(self):
        """Test audit with a non-existent path returns error gracefully."""
        if not BASELINE_TOML.exists():
            pytest.skip("openssf-baseline.toml not found")

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "darnit", "serve", str(BASELINE_TOML)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
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
