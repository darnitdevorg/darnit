"""Built-in list_controls tool for any framework.

Provides a generic control listing tool that works with any TOML-defined framework.
Lists all controls defined in the framework TOML organized by level.

Usage in TOML:
    [mcp.tools.list_controls]
    builtin = "list_controls"
    description = "List all available controls"
"""

from __future__ import annotations

import json

from darnit.core.logging import get_logger

logger = get_logger("server.tools.builtin_list")


async def builtin_list_controls(
    *,
    _framework_name: str = "",
) -> str:
    """List all available controls organized by level.

    Returns a JSON structure with controls grouped by maturity level,
    including names, descriptions, and domains.

    Args:
        _framework_name: Internal - set by the factory at registration time.

    Returns:
        JSON-formatted control listing.
    """
    from darnit.config import (
        load_controls_from_effective,
        load_effective_config_by_name,
    )
    from darnit.core.discovery import get_implementation
    from darnit.sieve.registry import get_control_registry

    if not _framework_name:
        return "Error: No framework name configured for this tool."

    # Load effective config
    try:
        config = load_effective_config_by_name(_framework_name)
    except Exception as e:
        return f"Error loading framework config '{_framework_name}': {e}"

    # Load TOML controls
    try:
        toml_controls = load_controls_from_effective(config)
    except Exception as e:
        return f"Error loading controls: {e}"

    # Register Python controls
    impl = get_implementation(_framework_name)
    if impl and hasattr(impl, "register_controls"):
        try:
            impl.register_controls()
        except Exception as e:
            logger.warning(f"Error registering Python controls: {e}")

    registry = get_control_registry()
    toml_ids = {c.control_id for c in toml_controls}
    python_controls = [
        spec for spec in registry.get_all_specs()
        if spec.control_id not in toml_ids
    ]

    all_controls = toml_controls + python_controls
    all_controls.sort(key=lambda c: c.control_id)

    # Group by level
    by_level: dict[int, list[dict]] = {}
    for control in all_controls:
        lvl = control.level or 0
        if lvl not in by_level:
            by_level[lvl] = []
        by_level[lvl].append({
            "id": control.control_id,
            "name": control.name,
            "description": control.description,
            "domain": control.domain or "",
        })

    result = {
        "framework": _framework_name,
        "total": len(all_controls),
    }

    for lvl in sorted(by_level.keys()):
        controls_at_level = by_level[lvl]
        domains = sorted({c["domain"] for c in controls_at_level if c["domain"]})
        result[f"level_{lvl}"] = {
            "count": len(controls_at_level),
            "domains": domains,
            "controls": controls_at_level,
        }

    return json.dumps(result, indent=2)


__all__ = ["builtin_list_controls"]
