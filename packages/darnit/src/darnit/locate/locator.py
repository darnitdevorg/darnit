"""Unified evidence location service.

This module provides the UnifiedLocator class that handles all evidence
location for controls, including:
1. .project/ configuration reference lookup
2. Pattern-based file discovery
3. Syncing discovered evidence back to .project/
"""

import os
from typing import Dict, List, Optional

from darnit.core.logging import get_logger
from darnit.config.loader import load_project_config, save_project_config
from darnit.config.schema import create_minimal_config, ProjectConfig
from darnit.config.discovery import discover_files, _set_config_path
from darnit.config.framework_schema import LocatorConfig

from .models import FoundEvidence, LocateResult

logger = get_logger("locate.locator")


class UnifiedLocator:
    """Unified evidence location service.

    Handles locating evidence for controls with .project/ integration:
    1. Check .project/ reference first (via project_path)
    2. Fall back to pattern-based discovery
    3. Optionally sync discovered evidence back to .project/

    Example:
        ```python
        locator = UnifiedLocator("/path/to/repo")

        # Locate using LocatorConfig from TOML
        config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md", ".github/SECURITY.md"],
            kind="file"
        )
        result = locator.locate("OSPS-VM-01.01", config)

        if result.success:
            print(f"Found: {result.found.path}")
            if result.needs_sync:
                locator.sync_to_project("OSPS-VM-01.01", result.found, config)
        ```
    """

    def __init__(
        self,
        local_path: str,
        project_config: Optional[ProjectConfig] = None,
    ):
        """Initialize the locator.

        Args:
            local_path: Repository path
            project_config: Optional pre-loaded project config (loaded on demand if not provided)
        """
        self.local_path = local_path
        self._project_config = project_config
        self._config_loaded = project_config is not None

    @property
    def project_config(self) -> Optional[ProjectConfig]:
        """Lazy-load project config on first access."""
        if not self._config_loaded:
            self._project_config = load_project_config(self.local_path)
            self._config_loaded = True
        return self._project_config

    def locate(
        self,
        control_id: str,
        locator_config: LocatorConfig,
    ) -> LocateResult:
        """Locate evidence for a control.

        Implements three-phase lookup:
        1. Check .project/ reference (project_path)
        2. Fall back to discovery patterns
        3. Return location + source

        Args:
            control_id: OSPS control ID (e.g., "OSPS-VM-01.01")
            locator_config: Configuration for how to locate evidence

        Returns:
            LocateResult with found evidence and source
        """
        searched_locations: List[str] = []

        # Phase 1: Check .project/ reference
        if locator_config.project_path:
            result = self._locate_via_config(control_id, locator_config)
            if result.success:
                logger.debug(
                    f"Control {control_id}: located via .project/ reference: {result.found.location}"
                )
                return result
            searched_locations.extend(result.searched_locations)

        # Phase 2: Fall back to pattern discovery
        if locator_config.discover:
            result = self._locate_via_discovery(control_id, locator_config)
            if result.success:
                logger.debug(
                    f"Control {control_id}: located via discovery: {result.found.location}"
                )
                # Mark for sync since it was discovered, not in config
                result.sync_recommended = True
                result.searched_locations = searched_locations + result.searched_locations
                return result
            searched_locations.extend(result.searched_locations)

        # Not found
        logger.debug(f"Control {control_id}: evidence not found")
        return LocateResult(
            found=None,
            source="none",
            searched_locations=searched_locations,
            sync_recommended=False,
        )

    def _locate_via_config(
        self,
        control_id: str,
        locator_config: LocatorConfig,
    ) -> LocateResult:
        """Try to locate evidence via .project/ reference.

        Args:
            control_id: OSPS control ID
            locator_config: Locator configuration

        Returns:
            LocateResult (may be empty if not found via config)
        """
        searched: List[str] = []

        if not locator_config.project_path:
            return LocateResult(source="none", searched_locations=searched)

        config = self.project_config
        if not config:
            searched.append(f".project/ (not found)")
            return LocateResult(source="none", searched_locations=searched)

        # Parse project_path (e.g., "security.policy" -> section="security", field="policy")
        parts = locator_config.project_path.split(".", 1)
        if len(parts) != 2:
            logger.warning(f"Invalid project_path format: {locator_config.project_path}")
            return LocateResult(source="none", searched_locations=searched)

        section, field = parts
        config_path = config.get_path(section, field)

        if not config_path:
            searched.append(f".project/{section}.{field} (not set)")
            return LocateResult(source="none", searched_locations=searched)

        # Verify the file exists (for file kind)
        if locator_config.kind == "file":
            full_path = os.path.join(self.local_path, config_path)
            if not os.path.exists(full_path):
                searched.append(f"{config_path} (referenced but missing)")
                return LocateResult(source="none", searched_locations=searched)

        # Found via config
        found = FoundEvidence(
            path=config_path if locator_config.kind == "file" else None,
            url=config_path if locator_config.kind == "url" else None,
            api_endpoint=config_path if locator_config.kind == "api" else None,
            kind=locator_config.kind,
        )
        searched.append(f".project/{section}.{field} = {config_path}")

        return LocateResult(
            found=found,
            source="config",
            searched_locations=searched,
            sync_recommended=False,  # Already in config
        )

    def _locate_via_discovery(
        self,
        control_id: str,
        locator_config: LocatorConfig,
    ) -> LocateResult:
        """Try to locate evidence via pattern discovery.

        Args:
            control_id: OSPS control ID
            locator_config: Locator configuration

        Returns:
            LocateResult (may be empty if not found via discovery)
        """
        searched: List[str] = []

        if not locator_config.discover:
            return LocateResult(source="none", searched_locations=searched)

        # Only file discovery is supported currently
        if locator_config.kind != "file":
            return LocateResult(source="none", searched_locations=searched)

        # Use the discover_files utility
        # We need a ref_path for the discovery function, use a synthetic one
        ref_path = locator_config.project_path or f"locate.{control_id}"

        discovered = discover_files(
            self.local_path,
            {ref_path: locator_config.discover}
        )

        searched.extend(locator_config.discover)

        if ref_path in discovered:
            discovered_path = discovered[ref_path]
            found = FoundEvidence(
                path=discovered_path,
                kind="file",
            )
            return LocateResult(
                found=found,
                source="discovered",
                searched_locations=searched,
                sync_recommended=True,  # Should be synced to config
            )

        return LocateResult(source="none", searched_locations=searched)

    def sync_to_project(
        self,
        control_id: str,
        found: FoundEvidence,
        locator_config: LocatorConfig,
    ) -> bool:
        """Sync found evidence back to .project/.

        Updates the .project/ configuration with the found evidence path,
        so future lookups can find it via config reference.

        Args:
            control_id: OSPS control ID
            found: The evidence that was found
            locator_config: Locator configuration (needs project_path)

        Returns:
            True if config was updated, False otherwise
        """
        if not locator_config.project_path:
            logger.debug(
                f"Control {control_id}: no project_path in locator config, cannot sync"
            )
            return False

        if not found.path:
            logger.debug(
                f"Control {control_id}: found evidence has no path, cannot sync"
            )
            return False

        parts = locator_config.project_path.split(".", 1)
        if len(parts) != 2:
            logger.debug(f"Invalid project_path format: {locator_config.project_path}")
            return False

        section, field = parts

        # Load or create config
        config = self.project_config
        if config is None:
            from darnit.config.discovery import discover_project_name

            project_name = discover_project_name(self.local_path) or "unnamed"
            config = create_minimal_config(
                name=project_name,
                project_type="software",
            )
            config.local_path = self.local_path
            self._project_config = config
            logger.info(f"Created new .project/ configuration for {project_name}")

        # Check if already set to same value
        existing_path = config.get_path(section, field)
        if existing_path == found.path:
            logger.debug(
                f"Control {control_id}: .project/{section}.{field} already set to {found.path}"
            )
            return False

        # Set the path reference
        _set_config_path(config, section, field, found.path)

        # Save the config
        save_project_config(config, self.local_path)
        logger.info(
            f"Updated .project/ with {section}.{field} = {found.path}"
        )

        return True

    def locate_and_sync(
        self,
        control_id: str,
        locator_config: LocatorConfig,
        auto_sync: bool = True,
    ) -> LocateResult:
        """Locate evidence and optionally sync to .project/.

        Convenience method that combines locate() and sync_to_project().

        Args:
            control_id: OSPS control ID
            locator_config: Locator configuration
            auto_sync: Whether to automatically sync discovered evidence

        Returns:
            LocateResult with found evidence
        """
        result = self.locate(control_id, locator_config)

        if auto_sync and result.needs_sync and result.found:
            synced = self.sync_to_project(control_id, result.found, locator_config)
            if synced:
                # Update source to reflect that it's now in config
                result.sync_recommended = False

        return result


__all__ = ["UnifiedLocator"]
