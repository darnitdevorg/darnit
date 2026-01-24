"""Project context helpers for reading user-confirmed facts from .project.yaml.

This module provides utilities for reading project context that affects
how controls are evaluated. Context can come from:
1. .project.yaml x-openssf-baseline.context section (user-confirmed facts)
2. .project.yaml x-openssf-baseline.controls section (explicit overrides)
3. Auto-detection from repository structure
"""

from typing import Any, Dict, List, Optional

from darnit.core.logging import get_logger
from darnit.config import (
    load_project_config,
    ProjectConfig,
    ControlStatusValue,
)

logger = get_logger("sieve.project_context")


def get_project_config_for_context(local_path: str) -> Optional[ProjectConfig]:
    """Load .project.yaml if it exists.

    Args:
        local_path: Path to the repository

    Returns:
        ProjectConfig if found, None otherwise
    """
    return load_project_config(local_path)


def get_project_context(local_path: str) -> Dict[str, Any]:
    """Get project context from .project.yaml.

    Returns a dict with user-confirmed context values.
    Missing values return None (not confirmed).

    Args:
        local_path: Path to the repository

    Returns:
        Dict of context values from x-openssf-baseline.context
    """
    config = load_project_config(local_path)
    if not config:
        return {}

    # Get context from extension
    if config.x_openssf_baseline and config.x_openssf_baseline.context:
        ctx = config.x_openssf_baseline.context
        result = {}
        if ctx.has_subprojects is not None:
            result["has_subprojects"] = ctx.has_subprojects
        if ctx.has_releases is not None:
            result["has_releases"] = ctx.has_releases
        if ctx.is_library is not None:
            result["is_library"] = ctx.is_library
        if ctx.has_compiled_assets is not None:
            result["has_compiled_assets"] = ctx.has_compiled_assets
        if ctx.ci_provider is not None:
            result["ci_provider"] = ctx.ci_provider
        return result

    return {}


def get_control_override(local_path: str, control_id: str) -> Optional[Dict[str, Any]]:
    """Get explicit override for a control from .project.yaml.

    Args:
        local_path: Path to the repository
        control_id: OSPS control ID (e.g., "OSPS-BR-02.01")

    Returns:
        Dict with 'status' and 'reason' if override exists, None otherwise
    """
    config = load_project_config(local_path)
    if not config:
        return None

    if not config.x_openssf_baseline:
        return None

    override = config.x_openssf_baseline.controls.get(control_id)
    if override:
        return {
            "status": override.status.value if isinstance(override.status, ControlStatusValue) else override.status,
            "reason": override.reason,
        }

    return None


def is_control_applicable(local_path: str, control_id: str) -> tuple[bool, Optional[str]]:
    """Check if a control is applicable for this project.

    Args:
        local_path: Path to the repository
        control_id: OSPS control ID

    Returns:
        Tuple of (is_applicable, reason_if_not)
    """
    config = load_project_config(local_path)
    if not config:
        return True, None

    return config.is_control_applicable(control_id)


def is_context_confirmed(local_path: str, context_key: str) -> bool:
    """Check if a specific context value has been confirmed by the user.

    Args:
        local_path: Path to the repository
        context_key: Context key to check

    Returns:
        True if the context value has been set
    """
    context = get_project_context(local_path)
    return context_key in context


def get_context_value(local_path: str, context_key: str, default: Any = None) -> Any:
    """Get a specific context value, or default if not confirmed.

    Args:
        local_path: Path to the repository
        context_key: Context key to retrieve
        default: Default value if not set

    Returns:
        Context value or default
    """
    context = get_project_context(local_path)
    return context.get(context_key, default)


# Context keys and their meanings
CONTEXT_KEYS = {
    "has_subprojects": {
        "description": "Does this project have subprojects or related repositories?",
        "affects": ["OSPS-QA-04.01", "OSPS-QA-04.02"],
        "prompt": "Does this project have any subprojects, additional repositories, or related codebases that should be documented?",
    },
    "has_releases": {
        "description": "Does this project make official releases?",
        "affects": ["OSPS-BR-02.01", "OSPS-BR-04.01", "OSPS-BR-06.01", "OSPS-DO-01.01", "OSPS-DO-03.01"],
        "prompt": "Does this project create official releases (tags, packages, binaries)?",
    },
    "is_library": {
        "description": "Is this a library/framework consumed by other projects?",
        "affects": ["OSPS-SA-02.01"],
        "prompt": "Is this project a library or framework that other projects depend on?",
    },
    "has_compiled_assets": {
        "description": "Does this project have compiled/binary release assets?",
        "affects": ["OSPS-QA-02.02"],
        "prompt": "Does this project release compiled binaries or packaged artifacts (not just source code)?",
    },
    "ci_provider": {
        "description": "What CI/CD system does this project use?",
        "affects": [
            "OSPS-BR-01.01", "OSPS-BR-01.02",  # Build reproducibility
            "OSPS-AC-04.01", "OSPS-AC-04.02",  # CI access control
            "OSPS-QA-06.01",  # Automated testing
            "OSPS-VM-05.02", "OSPS-VM-05.03",  # SCA and dependency scanning
            "OSPS-VM-06.02",  # SAST
        ],
        "prompt": "What CI/CD system does this project use? (github, gitlab, jenkins, circleci, none, other)",
        "values": ["github", "gitlab", "jenkins", "circleci", "azure", "travis", "none", "other"],
    },
    "ci_config_path": {
        "description": "Path to CI configuration file (for non-GitHub CI)",
        "affects": [
            "OSPS-BR-01.01", "OSPS-BR-01.02",
            "OSPS-AC-04.01", "OSPS-AC-04.02",
            "OSPS-QA-06.01",
            "OSPS-VM-05.02", "OSPS-VM-05.03",
            "OSPS-VM-06.02",
        ],
        "prompt": "What is the path to your CI configuration file? (e.g., .gitlab-ci.yml, Jenkinsfile)",
    },
}


def get_pending_confirmations(local_path: str, relevant_controls: List[str]) -> List[Dict[str, Any]]:
    """Get list of context confirmations needed for the given controls.

    Args:
        local_path: Path to the repository
        relevant_controls: List of control IDs being evaluated

    Returns:
        List of dicts with:
        - key: The context key to confirm
        - prompt: The question to ask the user
        - affects: List of control IDs affected
    """
    context = get_project_context(local_path)
    pending = []

    for key, info in CONTEXT_KEYS.items():
        # Check if any affected controls are in our relevant list
        if any(ctrl in relevant_controls for ctrl in info["affects"]):
            # Check if not already confirmed
            if key not in context:
                pending.append({
                    "key": key,
                    "prompt": info["prompt"],
                    "affects": info["affects"],
                })

    return pending


def get_ci_provider(local_path: str) -> Optional[str]:
    """Get the CI provider for a project.

    Checks:
    1. x-openssf-baseline.ci.provider
    2. x-openssf-baseline.context.ci_provider
    3. Auto-detection from repository structure

    Args:
        local_path: Path to the repository

    Returns:
        CI provider name or None
    """
    config = load_project_config(local_path)
    if config:
        provider = config.get_ci_provider()
        if provider:
            return provider

    # Auto-detect from common CI files
    import os

    ci_indicators = {
        "github": [".github/workflows"],
        "gitlab": [".gitlab-ci.yml"],
        "circleci": [".circleci/config.yml"],
        "jenkins": ["Jenkinsfile"],
        "azure": ["azure-pipelines.yml"],
        "travis": [".travis.yml"],
    }

    for provider, paths in ci_indicators.items():
        for path in paths:
            if os.path.exists(os.path.join(local_path, path)):
                return provider

    return None
