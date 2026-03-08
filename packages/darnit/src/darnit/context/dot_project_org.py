"""Org-level .project repository resolver.

CNCF projects maintain a dedicated `.project` repository at the org level
(e.g., `project-copacetic/.project`) containing shared metadata across all
repos in the org. This module discovers and fetches that metadata via the
`gh` CLI, caching results per session.

Example:
    from darnit.context.dot_project_org import OrgProjectResolver

    resolver = OrgProjectResolver()
    config = resolver.resolve("my-org")
    if config:
        print(config.name)
        print(config.maintainers)
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from darnit.context.dot_project import DotProjectReader, ProjectConfig

logger = logging.getLogger(__name__)

# Module-level cache: owner -> ProjectConfig | None
_org_cache: dict[str, ProjectConfig | None] = {}


def clear_cache() -> None:
    """Clear the org project cache."""
    _org_cache.clear()


class OrgProjectResolver:
    """Resolves org-level .project repository metadata.

    Discovers and fetches `project.yaml` and `maintainers.yaml` from
    `{owner}/.project` GitHub repos via the `gh` CLI.

    Caches results per owner for the duration of the session.
    """

    def __init__(self) -> None:
        self._gh_available: bool | None = None

    def resolve(self, owner: str) -> ProjectConfig | None:
        """Resolve org-level .project config for a GitHub owner.

        Args:
            owner: GitHub org or user (e.g., "kusari-oss")

        Returns:
            ProjectConfig from the org .project repo, or None if unavailable
        """
        if not owner:
            return None

        # Check cache first
        if owner in _org_cache:
            logger.debug("Using cached org .project config for %s", owner)
            return _org_cache[owner]

        if not self._is_gh_available():
            logger.debug("gh CLI not available, skipping org .project resolution")
            _org_cache[owner] = None
            return None

        config = self._fetch_org_project(owner)
        _org_cache[owner] = config
        return config

    def _is_gh_available(self) -> bool:
        """Check if gh CLI is available and authenticated."""
        if self._gh_available is not None:
            return self._gh_available

        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self._gh_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._gh_available = False

        if not self._gh_available:
            logger.debug("gh CLI not available or not authenticated")
        return self._gh_available

    def _repo_exists(self, owner: str) -> bool:
        """Check if {owner}/.project repo exists on GitHub."""
        try:
            result = subprocess.run(
                ["gh", "api", f"/repos/{owner}/.project", "--silent"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _fetch_file_content(self, owner: str, path: str) -> str | None:
        """Fetch a file from {owner}/.project repo via gh API.

        Args:
            owner: GitHub org or user
            path: File path within the repo (e.g., "project.yaml")

        Returns:
            File content as string, or None if not found
        """
        try:
            result = subprocess.run(
                [
                    "gh", "api",
                    f"/repos/{owner}/.project/contents/{path}",
                    "--jq", ".content",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return None

            content = result.stdout.strip()
            if not content:
                return None

            # GitHub API returns base64-encoded content
            import base64
            return base64.b64decode(content).decode("utf-8")

        except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
            logger.debug("Failed to fetch %s/.project/%s: %s", owner, path, e)
            return None

    def _fetch_org_project(self, owner: str) -> ProjectConfig | None:
        """Fetch and parse org-level .project config.

        Tries to fetch project.yaml and maintainers.yaml from {owner}/.project.
        Uses a temporary directory to leverage the existing DotProjectReader.
        """
        if not self._repo_exists(owner):
            logger.debug("No .project repo found for org %s", owner)
            return None

        logger.info("Found org-level .project repo for %s", owner)

        # Fetch files into a temp directory and use DotProjectReader
        with tempfile.TemporaryDirectory(prefix="darnit-org-project-") as tmpdir:
            project_dir = Path(tmpdir) / ".project"
            project_dir.mkdir()

            # Fetch project.yaml
            project_content = self._fetch_file_content(owner, "project.yaml")
            if not project_content:
                # Also try .project/project.yaml (nested structure)
                project_content = self._fetch_file_content(
                    owner, ".project/project.yaml"
                )

            if project_content:
                (project_dir / "project.yaml").write_text(project_content)
            else:
                logger.debug("No project.yaml found in %s/.project", owner)
                return None

            # Fetch maintainers.yaml
            maintainers_content = self._fetch_file_content(
                owner, "maintainers.yaml"
            )
            if not maintainers_content:
                maintainers_content = self._fetch_file_content(
                    owner, ".project/maintainers.yaml"
                )
            if maintainers_content:
                (project_dir / "maintainers.yaml").write_text(maintainers_content)

            # Parse using existing reader
            reader = DotProjectReader(tmpdir)
            if reader.exists():
                try:
                    config = reader.read()
                    logger.info(
                        "Loaded org .project config for %s: %s",
                        owner,
                        config.name or "(unnamed)",
                    )
                    return config
                except Exception as e:
                    logger.warning(
                        "Failed to parse org .project for %s: %s", owner, e
                    )

        return None
