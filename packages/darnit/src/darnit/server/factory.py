"""Server factory for creating MCP servers from configuration.

This module provides the main entry point for creating FastMCP servers
dynamically from TOML configuration files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from .registry import ToolRegistry

logger = logging.getLogger(__name__)


def create_server(config_path: str | Path) -> "FastMCP":
    """Create an MCP server from a TOML configuration file.

    Reads the TOML config, discovers tools from the [mcp.tools] section,
    dynamically imports their handlers, and registers them with FastMCP.

    Args:
        config_path: Path to the TOML configuration file

    Returns:
        Configured FastMCP server ready to run

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid or tools cannot be loaded

    Example:
        >>> server = create_server("openssf-baseline.toml")
        >>> server.run()
    """
    # Import here to avoid circular imports and allow lazy loading
    from mcp.server.fastmcp import FastMCP

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found]

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Load TOML config
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    # Extract server name
    mcp_config = config.get("mcp", {})
    server_name = mcp_config.get("name", "darnit")

    # Create registry and server
    registry = ToolRegistry.from_toml(config)
    server = FastMCP(server_name)

    # Register each tool
    registered_count = 0
    for name, spec in registry.tools.items():
        try:
            handler = registry.load_handler(spec)
            server.add_tool(handler, name=name, description=spec.description)
            registered_count += 1
            logger.debug(f"Registered tool: {name}")
        except (ImportError, AttributeError, ValueError) as e:
            logger.warning(f"Failed to load tool '{name}': {e}")
            continue

    logger.info(
        f"Created MCP server '{server_name}' with {registered_count} tools"
    )

    return server


def create_server_from_dict(config: dict) -> "FastMCP":
    """Create an MCP server from a configuration dictionary.

    This is useful for testing or when the config is already parsed.

    Args:
        config: Configuration dictionary with [mcp] section

    Returns:
        Configured FastMCP server ready to run
    """
    from mcp.server.fastmcp import FastMCP

    mcp_config = config.get("mcp", {})
    server_name = mcp_config.get("name", "darnit")

    registry = ToolRegistry.from_toml(config)
    server = FastMCP(server_name)

    for name, spec in registry.tools.items():
        try:
            handler = registry.load_handler(spec)
            server.add_tool(handler, name=name, description=spec.description)
        except (ImportError, AttributeError, ValueError) as e:
            logger.warning(f"Failed to load tool '{name}': {e}")

    return server
