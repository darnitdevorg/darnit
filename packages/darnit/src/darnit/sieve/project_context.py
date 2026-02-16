"""Project context helpers for control applicability checks.

This module provides the is_control_applicable() function used by
remediation orchestration to skip non-applicable controls.
"""

from darnit.config import load_project_config


def is_control_applicable(local_path: str, control_id: str) -> tuple[bool, str | None]:
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
