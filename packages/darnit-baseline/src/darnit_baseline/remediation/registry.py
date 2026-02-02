"""Remediation registry mapping controls to fix functions.

This module defines which remediation functions address which OSPS controls,
enabling automated detection of applicable fixes based on audit failures.
"""

from typing import Any

# Remediation categories with their associated control IDs and fix functions
REMEDIATION_REGISTRY: dict[str, dict[str, Any]] = {
    "branch_protection": {
        "description": "Enable branch protection rules",
        "controls": ["OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-QA-07.01"],
        "function": "enable_branch_protection",
        "safe": True,  # Safe to auto-apply
        "requires_api": True,
    },
    "status_checks": {
        "description": "Configure required status checks",
        "controls": ["OSPS-QA-03.01"],
        "function": "configure_status_checks",
        "safe": True,
        "requires_api": True,
    },
    "security_policy": {
        "description": "Create SECURITY.md with vulnerability reporting and VEX policy",
        "controls": ["OSPS-VM-01.01", "OSPS-VM-02.01", "OSPS-VM-03.01", "OSPS-VM-04.02"],
        "function": "create_security_policy",
        "safe": True,
        "requires_api": False,
    },
    "vex_policy": {
        "description": "Add VEX policy section to existing SECURITY.md",
        "controls": ["OSPS-VM-04.02"],
        "function": "ensure_vex_policy",
        "safe": True,
        "requires_api": False,
    },
    "codeowners": {
        "description": "Create CODEOWNERS file",
        "controls": ["OSPS-GV-01.01", "OSPS-GV-01.02", "OSPS-GV-04.01"],
        "function": "create_codeowners",
        "safe": True,
        "requires_api": False,
        # Context requirements (fallback for plugins - TOML is primary)
        "requires_context": [{
            "key": "maintainers",
            "required": True,
            "confidence_threshold": 0.9,
            "prompt_if_auto_detected": True,
            "warning": "GitHub collaborators are not necessarily project maintainers. Please confirm who should be code owners.",
        }],
    },
    "maintainers": {
        "description": "Create MAINTAINERS.md with project maintainers",
        "controls": ["OSPS-GV-01.01", "OSPS-GV-01.02", "OSPS-GV-04.01"],
        "function": "create_maintainers_doc",
        "safe": True,
        "requires_api": False,
        # Context requirements (fallback for plugins - TOML is primary)
        "requires_context": [{
            "key": "maintainers",
            "required": True,
            "confidence_threshold": 0.9,
            "prompt_if_auto_detected": True,
            "warning": "GitHub collaborators are not necessarily project maintainers. Please confirm the actual project maintainers.",
        }],
    },
    "governance": {
        "description": "Create GOVERNANCE.md",
        "controls": ["OSPS-GV-01.01", "OSPS-GV-01.02"],
        "function": "create_governance_doc",
        "safe": True,
        "requires_api": False,
        # Context requirements (fallback for plugins - TOML is primary)
        "requires_context": [{
            "key": "maintainers",
            "required": True,
            "confidence_threshold": 0.9,
            "prompt_if_auto_detected": True,
            "warning": "GitHub collaborators are not necessarily project maintainers. Please confirm the actual project maintainers.",
        }],
    },
    "contributing": {
        "description": "Create CONTRIBUTING.md guide",
        "controls": ["OSPS-GV-03.01", "OSPS-GV-03.02"],
        "function": "create_contributing_guide",
        "safe": True,
        "requires_api": False,
    },
    "dco_enforcement": {
        "description": "Configure DCO enforcement",
        "controls": ["OSPS-LE-01.01"],
        "function": "configure_dco_enforcement",
        "safe": True,
        "requires_api": False,
    },
    "bug_report_template": {
        "description": "Create bug report issue template",
        "controls": ["OSPS-DO-02.01"],
        "function": "create_bug_report_template",
        "safe": True,
        "requires_api": False,
    },
    "dependabot": {
        "description": "Configure Dependabot for dependency scanning",
        "controls": ["OSPS-VM-05.01", "OSPS-VM-05.02", "OSPS-VM-05.03"],
        "function": "create_dependabot_config",
        "safe": True,
        "requires_api": False,
    },
    "support_doc": {
        "description": "Create SUPPORT.md",
        "controls": ["OSPS-DO-03.01"],
        "function": "create_support_doc",
        "safe": True,
        "requires_api": False,
    },
}


def get_control_to_category_map() -> dict[str, str]:
    """Build reverse mapping from control ID to remediation category.

    Returns:
        Dict mapping control IDs (e.g., "OSPS-AC-03.01") to category names
        (e.g., "branch_protection")
    """
    mapping = {}
    for category, info in REMEDIATION_REGISTRY.items():
        for control_id in info["controls"]:
            mapping[control_id] = category
    return mapping


def get_categories_for_failures(failures: list[dict[str, Any]]) -> list[str]:
    """Determine which remediation categories apply to the given failures.

    Args:
        failures: List of check results with status="FAIL"

    Returns:
        Sorted list of applicable remediation category names
    """
    control_map = get_control_to_category_map()
    categories = set()

    for failure in failures:
        control_id = failure.get("id", "")
        if control_id in control_map:
            categories.add(control_map[control_id])

    return sorted(categories)


def get_all_categories() -> list[str]:
    """Get all available remediation category names."""
    return sorted(REMEDIATION_REGISTRY.keys())


def get_category_info(category: str) -> dict[str, Any]:
    """Get information about a specific remediation category.

    Args:
        category: Category name (e.g., "branch_protection")

    Returns:
        Dict with description, controls, function name, etc.

    Raises:
        KeyError: If category doesn't exist
    """
    return REMEDIATION_REGISTRY[category]


def get_controls_by_category(category: str) -> list[str]:
    """Get list of control IDs addressed by a category.

    Args:
        category: Category name

    Returns:
        List of OSPS control IDs
    """
    return REMEDIATION_REGISTRY.get(category, {}).get("controls", [])


__all__ = [
    "REMEDIATION_REGISTRY",
    "get_control_to_category_map",
    "get_categories_for_failures",
    "get_all_categories",
    "get_category_info",
    "get_controls_by_category",
]
