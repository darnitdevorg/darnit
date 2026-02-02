"""OSPS compliance check implementations.

This module provides check functions for OpenSSF Baseline (OSPS v2025.10.10)
compliance verification, organized by maturity level.

Levels:
- Level 1: Baseline security requirements (24 controls)
- Level 2: Enhanced security requirements (18 controls)
- Level 3: Highest security requirements (19 controls)
"""

from typing import Any

# Constants
from .constants import (
    API_DOCS,
    BINARY_EXTENSIONS,
    DANGEROUS_CONTEXTS,
    DANGEROUS_SECRET_FILES,
    DEPENDENCY_FILES,
    DESIGN_DOCS,
    GOVERNANCE_FILES,
    LOCKFILE_PATTERNS,
    OSI_LICENSES,
    SCA_TOOL_PATTERNS,
    SECRET_PATTERNS,
    SECURITY_DOCS,
    THREAT_MODEL_DOCS,
)

# Level 1 checks
from .level1 import (
    check_level1_access_control,
    check_level1_build_release,
    check_level1_documentation,
    check_level1_governance,
    check_level1_legal,
    check_level1_quality,
    check_level1_vulnerability,
    run_all_level1_checks,
)

# Level 2 checks
from .level2 import (
    check_level2_access_control,
    check_level2_build_release,
    check_level2_documentation,
    check_level2_governance,
    check_level2_legal,
    check_level2_quality,
    check_level2_security_architecture,
    check_level2_vulnerability,
    run_all_level2_checks,
)

# Level 3 checks
from .level3 import (
    check_level3_access_control,
    check_level3_build_release,
    check_level3_documentation,
    check_level3_governance,
    check_level3_quality,
    check_level3_security_architecture,
    check_level3_vulnerability,
    run_all_level3_checks,
)

__all__ = [
    # Level 1 checks
    "check_level1_access_control",
    "check_level1_build_release",
    "check_level1_documentation",
    "check_level1_governance",
    "check_level1_legal",
    "check_level1_quality",
    "check_level1_vulnerability",
    "run_all_level1_checks",
    # Level 2 checks
    "check_level2_access_control",
    "check_level2_build_release",
    "check_level2_documentation",
    "check_level2_governance",
    "check_level2_legal",
    "check_level2_quality",
    "check_level2_security_architecture",
    "check_level2_vulnerability",
    "run_all_level2_checks",
    # Level 3 checks
    "check_level3_access_control",
    "check_level3_build_release",
    "check_level3_documentation",
    "check_level3_governance",
    "check_level3_quality",
    "check_level3_security_architecture",
    "check_level3_vulnerability",
    "run_all_level3_checks",
    # Constants
    "OSI_LICENSES",
    "BINARY_EXTENSIONS",
    "DEPENDENCY_FILES",
    "LOCKFILE_PATTERNS",
    "DANGEROUS_SECRET_FILES",
    "DANGEROUS_CONTEXTS",
    "SECRET_PATTERNS",
    "GOVERNANCE_FILES",
    "DESIGN_DOCS",
    "API_DOCS",
    "SECURITY_DOCS",
    "THREAT_MODEL_DOCS",
    "SCA_TOOL_PATTERNS",
    # Convenience aliases
    "run_level1_checks",
    "run_level2_checks",
    "run_level3_checks",
]


# Convenience aliases for backward compatibility
def run_level1_checks(owner: str, repo: str, local_path: str, default_branch: str) -> list[dict[str, Any]]:
    """Run all Level 1 OSPS checks. Alias for run_all_level1_checks."""
    return run_all_level1_checks(owner, repo, local_path, default_branch)


def run_level2_checks(owner: str, repo: str, local_path: str, default_branch: str) -> list[dict[str, Any]]:
    """Run all Level 2 OSPS checks. Alias for run_all_level2_checks."""
    return run_all_level2_checks(owner, repo, local_path, default_branch)


def run_level3_checks(owner: str, repo: str, local_path: str, default_branch: str) -> list[dict[str, Any]]:
    """Run all Level 3 OSPS checks. Alias for run_all_level3_checks."""
    return run_all_level3_checks(owner, repo, local_path, default_branch)
