"""Remediation infrastructure for darnit framework.

This module provides generic remediation utilities:
- Helper functions for file operations and detection
- GitHub API integration for repository configuration
- Declarative remediation executor for TOML-based configs

Implementation-specific remediations (like OSPS orchestrator and actions)
should be in the respective implementation packages.
"""

from .context_validator import (
    ContextCheckResult,
    check_context_requirements,
    format_context_prompt,
    get_context_requirements_for_category,
)
from .executor import (
    RemediationExecutor,
    RemediationResult,
)
from .github import (
    detect_workflow_checks,
    enable_branch_protection,
)
from .helpers import (
    check_file_exists,
    ensure_directory,
    format_error,
    format_success,
    format_warning,
    get_repo_maintainers,
    write_file_safe,
)

__all__ = [
    # Helpers
    "ensure_directory",
    "write_file_safe",
    "check_file_exists",
    "get_repo_maintainers",
    "detect_workflow_checks",
    "format_success",
    "format_error",
    "format_warning",
    # GitHub
    "enable_branch_protection",
    # Executor
    "RemediationExecutor",
    "RemediationResult",
    # Context Validator
    "ContextCheckResult",
    "check_context_requirements",
    "format_context_prompt",
    "get_context_requirements_for_category",
]
