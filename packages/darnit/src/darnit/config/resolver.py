"""Config-aware file resolution for controls.

This module provides functions to resolve file paths for controls by:
1. Checking .project/ configuration references first
2. Falling back to pattern-based discovery
3. Updating .project/ after remediation creates files

This enables bidirectional synchronization between checks/remediation
and .project/ configuration.
"""

import os
from typing import Dict, List, Optional, Tuple

from darnit.core.logging import get_logger
from darnit.config.loader import load_project_config, save_project_config
from darnit.config.schema import create_minimal_config, ProjectConfig
from darnit.config.discovery import discover_files, _set_config_path

logger = get_logger("config.resolver")


def resolve_file_for_control(
    local_path: str,
    control_id: str,
    file_locations: Dict[str, List[str]],
    control_reference_mapping: Dict[str, str],
) -> Tuple[Optional[str], str]:
    """Resolve file path for a control, checking .project/ first.

    This function implements a two-phase lookup:
    1. First, check if there's a reference in .project/ configuration
    2. If no reference, fall back to pattern-based file discovery

    Args:
        local_path: Repository path
        control_id: OSPS control ID (e.g., "OSPS-DO-02.01")
        file_locations: Mapping of ref_path -> possible file patterns
        control_reference_mapping: Mapping of control_id -> ref_path (e.g., "security.policy")

    Returns:
        Tuple of (file_path, source) where source is:
        - "config": Found via .project/ reference
        - "discovered": Found via pattern discovery
        - "none": Not found
    """
    # Get the reference path for this control (e.g., "security.policy")
    ref_path = control_reference_mapping.get(control_id)

    # 1. Try .project/ reference first
    config = load_project_config(local_path)
    if config and ref_path:
        parts = ref_path.split(".", 1)
        if len(parts) == 2:
            section, field = parts
            config_path = config.get_path(section, field)
            if config_path:
                full_path = os.path.join(local_path, config_path)
                if os.path.exists(full_path):
                    logger.debug(
                        f"Control {control_id}: resolved via .project/ reference: {config_path}"
                    )
                    return config_path, "config"
                else:
                    logger.debug(
                        f"Control {control_id}: .project/ reference {config_path} does not exist"
                    )

    # 2. Fall back to pattern discovery
    if ref_path and ref_path in file_locations:
        discovered = discover_files(local_path, {ref_path: file_locations[ref_path]})
        if ref_path in discovered:
            discovered_path = discovered[ref_path]
            logger.debug(
                f"Control {control_id}: discovered file {discovered_path} (not in .project/)"
            )
            return discovered_path, "discovered"

    logger.debug(f"Control {control_id}: no file found")
    return None, "none"


def update_config_after_file_create(
    local_path: str,
    control_id: str,
    created_file_path: str,
    control_reference_mapping: Dict[str, str],
) -> bool:
    """Update .project/ config after a file is created.

    This function adds a reference to the newly created file in the
    .project/ configuration, so future checks can find it via config.

    Args:
        local_path: Repository path
        control_id: OSPS control ID that was remediated (e.g., "OSPS-DO-02.01")
        created_file_path: Path to the created file (relative to repo)
        control_reference_mapping: Mapping of control_id -> ref_path (e.g., "security.policy")

    Returns:
        True if config was updated, False otherwise (e.g., no mapping for control)
    """
    # Get the reference path for this control
    ref_path = control_reference_mapping.get(control_id)
    if not ref_path:
        logger.debug(
            f"Control {control_id}: no reference mapping, cannot update .project/"
        )
        return False

    parts = ref_path.split(".", 1)
    if len(parts) != 2:
        logger.debug(f"Invalid reference path format: {ref_path}")
        return False

    section, field = parts

    # Load existing config or create minimal one
    config = load_project_config(local_path)
    if config is None:
        # Create a minimal config with discovered project name
        from darnit.config.discovery import discover_project_name

        project_name = discover_project_name(local_path) or "unnamed"
        config = create_minimal_config(
            name=project_name,
            project_type="software",
        )
        config.local_path = local_path
        logger.info(f"Created new .project/ configuration for {project_name}")

    # Check if reference already exists
    existing_path = config.get_path(section, field)
    if existing_path == created_file_path:
        logger.debug(
            f"Control {control_id}: .project/ reference already set to {created_file_path}"
        )
        return False  # Already set, no change needed

    # Set the path reference
    _set_config_path(config, section, field, created_file_path)

    # Save the config
    save_project_config(config, local_path)
    logger.info(
        f"Updated .project/ with {section}.{field} = {created_file_path}"
    )

    return True


def sync_discovered_file_to_config(
    local_path: str,
    control_id: str,
    discovered_path: str,
    control_reference_mapping: Dict[str, str],
) -> bool:
    """Sync a discovered file to .project/ config.

    When a file is found via discovery (not via config reference),
    this function can be called to add it to the config for future lookups.

    Args:
        local_path: Repository path
        control_id: OSPS control ID
        discovered_path: Path to the discovered file (relative to repo)
        control_reference_mapping: Mapping of control_id -> ref_path

    Returns:
        True if config was updated, False otherwise
    """
    return update_config_after_file_create(
        local_path=local_path,
        control_id=control_id,
        created_file_path=discovered_path,
        control_reference_mapping=control_reference_mapping,
    )


__all__ = [
    "resolve_file_for_control",
    "update_config_after_file_create",
    "sync_discovered_file_to_config",
]
