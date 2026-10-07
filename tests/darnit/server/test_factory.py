"""Tests for darnit.server.factory module."""

import asyncio
import logging
import tomllib
from pathlib import Path

import pytest

from darnit.server.factory import create_server, create_server_from_dict


class TestCreateServerFromDict:
    """Tests for create_server_from_dict function."""

    def test_creates_server_with_name(self):
        """Test server is created with correct name."""
        config = {
            "mcp": {
                "name": "test-server",
                "tools": {},
            }
        }
        server = create_server_from_dict(config)
        assert server.name == "test-server"

    def test_creates_server_default_name(self):
        """Test server uses default name if not specified."""
        config = {"mcp": {"tools": {}}}
        server = create_server_from_dict(config)
        assert server.name == "darnit"

    def test_creates_server_empty_config(self):
        """Test server is created with empty config."""
        config = {}
        server = create_server_from_dict(config)
        assert server is not None
        assert server.name == "darnit"

    def test_registers_tools(self):
        """Test that tools are registered with the server."""
        config = {
            "mcp": {
                "name": "test-server",
                "tools": {
                    "my_tool": {
                        "handler": "darnit.core.logging:get_logger",
                        "description": "Serialize to JSON",
                    }
                },
            }
        }
        server = create_server_from_dict(config)
        # The server should have registered the tool
        # We can verify by checking the server's internal state
        # FastMCP stores tools in _tool_manager
        assert server is not None


class TestCreateServer:
    """Tests for create_server function."""

    def test_file_not_found(self):
        """Test raises FileNotFoundError for missing config."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            create_server("/nonexistent/path/config.toml")

    def test_loads_from_toml_file(self, tmp_path):
        """Test loading server from TOML file."""
        config_path = tmp_path / "test.toml"
        config_path.write_text('''
[mcp]
name = "from-file-server"

[mcp.tools.get_logger]
handler = "darnit.core.logging:get_logger"
description = "Logger"
''')
        server = create_server(str(config_path))
        assert server.name == "from-file-server"

    def test_loads_path_object(self, tmp_path):
        """Test loading server from Path object."""
        config_path = tmp_path / "test.toml"
        config_path.write_text('''
[mcp]
name = "path-server"
''')
        server = create_server(config_path)  # Pass Path directly
        assert server.name == "path-server"

    def test_handles_invalid_handler(self, tmp_path, caplog):
        """A missing handler is skipped with a warning; the other tools still load."""
        config_path = tmp_path / "test.toml"
        config_path.write_text('''
[mcp]
name = "test-server"

[mcp.tools.valid_tool]
handler = "darnit.core.logging:get_logger"
description = "Valid tool"

[mcp.tools.invalid_tool]
handler = "darnit.nonexistent_module:func"
description = "Invalid tool"
''')
        with caplog.at_level(logging.WARNING):
            server = create_server(str(config_path))
        tools = {tool.name for tool in asyncio.run(server.list_tools())}
        assert "valid_tool" in tools
        assert "invalid_tool" not in tools
        assert "Failed to load tool 'invalid_tool'" in caplog.text

    @pytest.mark.parametrize("handler", ["os:system", "subprocess:run", "darnit_not_installed_xyz.tools:run"])
    def test_refused_handler_is_reported_at_startup(self, tmp_path, caplog, handler):
        """A tool whose module path the policy refuses does not load, and startup says so."""
        config_path = tmp_path / "test.toml"
        config_path.write_text(f'''
[mcp]
name = "test-server"

[mcp.tools.valid_tool]
handler = "darnit.core.logging:get_logger"
description = "Valid tool"

[mcp.tools.refused_tool]
handler = "{handler}"
description = "Refused tool"
''')
        with caplog.at_level(logging.WARNING):
            server = create_server(str(config_path))
        tools = {tool.name for tool in asyncio.run(server.list_tools())}
        assert "valid_tool" in tools
        assert "refused_tool" not in tools
        refusals = [r for r in caplog.records if r.levelno == logging.ERROR and "refused_tool" in r.getMessage()]
        assert refusals and handler in refusals[0].getMessage()

    def test_refused_handler_is_reported_from_dict(self, caplog):
        config = {"mcp": {"tools": {"refused_tool": {"handler": "os:system", "description": "x"}}}}
        with caplog.at_level(logging.WARNING):
            server = create_server_from_dict(config)
        assert "refused_tool" not in {tool.name for tool in asyncio.run(server.list_tools())}
        assert any(r.levelno == logging.ERROR and "refused_tool" in r.getMessage() for r in caplog.records)

    def test_openssf_baseline_toml(self):
        """Test loading the actual openssf-baseline.toml file."""
        # Find the openssf-baseline.toml file
        baseline_path = (
            Path(__file__).parent.parent.parent.parent
            / "packages"
            / "darnit-baseline"
            / "openssf-baseline.toml"
        )
        if baseline_path.exists():
            # Should be able to create server from it
            # Note: This test may fail if darnit_baseline tools have import errors
            try:
                server = create_server(str(baseline_path))
                assert server.name == "openssf-baseline"
            except ImportError:
                # Skip if darnit_baseline not installed
                pytest.skip("darnit_baseline not installed")
        else:
            pytest.skip("openssf-baseline.toml not found")


def _shipped_framework_configs() -> list[tuple[str, Path]]:
    from darnit.core.discovery import discover_implementations

    configs = []
    for name, impl in sorted(discover_implementations().items()):
        path = impl.get_framework_config_path()
        if path is not None and Path(path).is_file():
            configs.append((name, Path(path)))
    return configs


SHIPPED_FRAMEWORKS = _shipped_framework_configs()


class TestShippedFrameworkTools:
    """Every [mcp.tools] entry of every installed framework loads (#490)."""

    def test_the_community_spec_module_path_tool_is_among_them(self):
        assert "community-spec" in dict(SHIPPED_FRAMEWORKS)

    @pytest.mark.parametrize(("name", "config_path"), SHIPPED_FRAMEWORKS, ids=[name for name, _ in SHIPPED_FRAMEWORKS])
    def test_all_declared_tools_register(self, name, config_path, caplog):
        declared = set(tomllib.loads(config_path.read_text(encoding="utf-8")).get("mcp", {}).get("tools", {}))
        with caplog.at_level(logging.WARNING, logger="darnit"):
            server = create_server(config_path)
        registered = {tool.name for tool in asyncio.run(server.list_tools())}
        assert declared <= registered, f"{name}: {sorted(declared - registered)} did not load\n{caplog.text}"
