"""Server factory for creating MCP servers from configuration.

This module provides the main entry point for creating FastMCP servers
dynamically from TOML configuration files.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from darnit.core.handlers import HandlerImportRefused

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


def _darnit_code_locations() -> list[Path]:
    import darnit

    return [Path(sys.prefix), Path(sys.executable), Path(darnit.__file__).parent]


def registration_scope_warning(audit_target: str | Path, *, code_locations: list[Path] | None = None) -> str | None:
    """Warn when darnit's own code runs from inside the audited repository.

    Coding agents start user-scope and repository-scope MCP servers alike in
    the session directory, so the working directory says nothing about how
    darnit was registered. A repository-scoped registration such as
    ``uv run darnit serve`` does, however, run the repository's own copy of
    darnit, which is visible in where the interpreter and package live.
    """
    target = Path(audit_target).resolve()
    for location in code_locations if code_locations is not None else _darnit_code_locations():
        resolved = location.resolve()
        if resolved == target or target in resolved.parents:
            return (
                f"darnit is running from {resolved}, inside the audited repository, so the "
                "repository supplies the code auditing it (for example a repository-scoped "
                "`uv run darnit serve` registration). That is expected when developing darnit "
                "itself; for other repositories, register darnit at user scope "
                "(`darnit install` without --project) and do not approve repository-scoped "
                "darnit servers."
            )
    return None


def create_server(
    config_path: str | Path,
    *,
    operator_config_path: str | Path | None = None,
    strict_operator_config: bool = False,
) -> FastMCP:
    """Create an MCP server from a TOML configuration file.

    Reads the TOML config, discovers tools from the [mcp.tools] section,
    dynamically imports their handlers, and registers them with FastMCP.
    The operator configuration launch options are recorded so each audit
    tool call resolves operator configuration against its own target.

    Args:
        config_path: Path to the TOML configuration file
        operator_config_path: ``--operator-config`` given at launch
        strict_operator_config: ``--strict-operator-config`` given at launch

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

    from darnit.config.operator.loader import set_launch_options

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found]

    set_launch_options(operator_config_path, strict=strict_operator_config)

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
        except HandlerImportRefused as e:
            logger.error(f"Refused to load tool '{name}': {e}")
            continue
        except (ImportError, AttributeError, ValueError) as e:
            logger.warning(f"Failed to load tool '{name}': {e}")
            continue

    # RFC-0001 Stage 1 (feature 025 T036): register framework-independent
    # harness-loop tools (run_next_action / submit_action_result). These
    # live in darnit-core and drive the ActionPlan protocol; they are
    # available regardless of which framework's TOML the server was built
    # from.
    from darnit.server.tools.harness_loop import register_harness_loop_tools

    register_harness_loop_tools(server)

    # Feature 041: the one path by which a coding agent's judgment reaches an
    # audit, bound to this server's framework.
    from darnit.server.tools.judgments import register_judgment_tools

    register_judgment_tools(server, framework_name)

    # Feature 042: a framework whose TOML does not define its own
    # confirm_project_data gets the framework-neutral one for its context keys.
    from darnit.server.tools.project_data import register_confirmation_tool

    register_confirmation_tool(server, framework_name, registry.tools)

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
        except HandlerImportRefused as e:
            logger.error(f"Refused to load tool '{name}': {e}")
        except (ImportError, AttributeError, ValueError) as e:
            logger.warning(f"Failed to load tool '{name}': {e}")

    # RFC-0001 Stage 1 (feature 025 T036): also register harness-loop tools.
    from darnit.server.tools.harness_loop import register_harness_loop_tools

    register_harness_loop_tools(server)

    from darnit.server.tools.judgments import register_judgment_tools

    register_judgment_tools(server, framework_name)

    from darnit.server.tools.project_data import register_confirmation_tool

    register_confirmation_tool(server, framework_name, registry.tools)

    return server
