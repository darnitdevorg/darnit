"""Inject .project/ context into the sieve pipeline.

This module provides utilities to inject .project/ context into CheckContext
objects used by the sieve orchestrator.

Example:
    from darnit.context.inject import inject_project_context
    from darnit.sieve.models import CheckContext

    context = CheckContext(
        owner="org",
        repo="repo",
        local_path="/path/to/repo",
        default_branch="main",
        control_id="OSPS-AC-01.01",
    )

    # Inject .project/ context
    inject_project_context(context)

    # Now context.project_context contains .project/ data
    policy_path = context.project_context.get("project.security.policy_path")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from darnit.context.dot_project_mapper import DotProjectMapper

if TYPE_CHECKING:
    from darnit.sieve.models import CheckContext

logger = logging.getLogger(__name__)


def inject_project_context(context: CheckContext) -> None:
    """Inject .project/ context into a CheckContext.

    This function reads .project/project.yaml from the repository path
    and populates context.project_context with the mapped values.

    When context.owner is set, org-level .project repo resolution is
    performed automatically and merged with local config.

    Args:
        context: CheckContext to populate with .project/ data
    """
    try:
        owner = getattr(context, "owner", "") or ""
        mapper = DotProjectMapper(context.local_path, owner=owner)
        project_context = mapper.get_context()

        context.project_context = project_context

        if project_context:
            logger.debug(
                "Injected %d .project/ context variables for %s",
                len(project_context),
                context.control_id,
            )
        else:
            logger.debug("No .project/ context available for %s", context.control_id)

    except Exception as e:
        logger.warning("Failed to inject .project/ context: %s", e)
        context.project_context = {}


def create_check_context_with_project(
    owner: str,
    repo: str,
    local_path: str,
    default_branch: str,
    control_id: str,
    control_metadata: dict | None = None,
) -> CheckContext:
    """Create a CheckContext with .project/ context pre-populated.

    This is a convenience function that creates a CheckContext and
    automatically injects .project/ context.

    Args:
        owner: Repository owner
        repo: Repository name
        local_path: Path to local repository
        default_branch: Default branch name
        control_id: Control ID being checked
        control_metadata: Optional control metadata

    Returns:
        CheckContext with project_context populated
    """
    from darnit.sieve.models import CheckContext

    context = CheckContext(
        owner=owner,
        repo=repo,
        local_path=local_path,
        default_branch=default_branch,
        control_id=control_id,
        control_metadata=control_metadata or {},
    )

    inject_project_context(context)

    return context


def get_project_value(context: CheckContext, key: str, default: any = None) -> any:
    """Get a value from .project/ context.

    Args:
        context: CheckContext with project_context
        key: Dotted key like "project.security.policy_path"
        default: Default value if key not found

    Returns:
        Value from project_context or default
    """
    return context.project_context.get(key, default)


def has_project_value(context: CheckContext, key: str) -> bool:
    """Check if a .project/ context value exists.

    Args:
        context: CheckContext with project_context
        key: Dotted key like "project.security.policy_path"

    Returns:
        True if key exists in project_context
    """
    return key in context.project_context
