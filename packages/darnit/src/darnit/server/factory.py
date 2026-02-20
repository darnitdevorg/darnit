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


def _bind_tool_config(handler, config: dict):
    """Wrap a tool handler to inject TOML config as _tool_config kwarg.

    If the handler signature accepts _tool_config, it will receive the
    TOML-defined parameters dict. Otherwise, the config is silently ignored.

    Args:
        handler: The original tool handler function
        config: Dict of config values from [mcp.tools.<name>] TOML section

    Returns:
        Wrapped handler that injects _tool_config
    """
    import functools
    import inspect

    sig = inspect.signature(handler)
    if "_tool_config" not in sig.parameters:
        return handler

    @functools.wraps(handler)
    def wrapper(**kwargs):
        kwargs["_tool_config"] = config
        return handler(**kwargs)

    # Remove _tool_config from the wrapper signature so FastMCP
    # doesn't expose it as an MCP tool parameter
    new_params = [
        p for name, p in sig.parameters.items() if name != "_tool_config"
    ]
    wrapper.__signature__ = sig.replace(parameters=new_params)
    return wrapper


def _register_implementation_handlers(config: dict) -> None:
    """Register handlers from the implementation specified in config.

    This enables short name resolution for handler references in TOML.
    The implementation is discovered from the metadata.name field.

    Args:
        config: Parsed TOML configuration dictionary
    """
    from darnit.core.discovery import get_implementation

    # Get framework name from metadata
    metadata = config.get("metadata", {})
    framework_name = metadata.get("name")

    if not framework_name:
        logger.debug("No metadata.name in config, skipping handler registration")
        return

    # Get the implementation
    impl = get_implementation(framework_name)
    if impl is None:
        logger.debug(f"No implementation found for '{framework_name}'")
        return

    # Register handlers if the method exists
    if hasattr(impl, "register_handlers"):
        try:
            impl.register_handlers()
            logger.debug(f"Registered handlers for '{framework_name}'")
        except Exception as e:
            logger.warning(f"Failed to register handlers for '{framework_name}': {e}")


def create_server(config_path: str | Path) -> FastMCP:
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

    # Register handlers from implementation before loading tools
    # This enables short name resolution for handler references
    _register_implementation_handlers(config)

    # Extract framework name for built-in tool binding
    metadata = config.get("metadata", {})
    framework_name = metadata.get("name")

    # Create registry and server
    registry = ToolRegistry.from_toml(config)
    server = FastMCP(server_name)

    # Register each tool
    registered_count = 0
    for name, spec in registry.tools.items():
        try:
            handler = registry.load_handler(spec, framework_name=framework_name)
            # Inject TOML config into handler if parameters are defined
            if spec.parameters:
                handler = _bind_tool_config(handler, spec.parameters)
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


def create_server_from_dict(config: dict) -> FastMCP:
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

    # Register handlers from implementation before loading tools
    _register_implementation_handlers(config)

    # Extract framework name for built-in tool binding
    metadata = config.get("metadata", {})
    framework_name = metadata.get("name")

    registry = ToolRegistry.from_toml(config)
    server = FastMCP(server_name)

    for name, spec in registry.tools.items():
        try:
            handler = registry.load_handler(spec, framework_name=framework_name)
            # Inject TOML config into handler if parameters are defined
            if spec.parameters:
                handler = _bind_tool_config(handler, spec.parameters)
            server.add_tool(handler, name=name, description=spec.description)
        except (ImportError, AttributeError, ValueError) as e:
            logger.warning(f"Failed to load tool '{name}': {e}")

    return server
