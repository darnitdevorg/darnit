"""Remediation infrastructure for darnit framework.

This module provides generic remediation utilities:
- GitHub API integration for repository configuration
- Declarative remediation executor for TOML-based configs

Implementation-specific remediations (like OSPS orchestrator and actions)
should be in the respective implementation packages.
"""

from .context_validator import (
    ContextCheckResult,
    check_context_requirements,
    format_context_prompt,
)
from .executor import (
    RemediationExecutor,
    RemediationResult,
)
from .github import (
    enable_branch_protection,
)

__all__ = [
    # GitHub
    "enable_branch_protection",
    # Executor
    "RemediationExecutor",
    "RemediationResult",
    # Context Validator
    "ContextCheckResult",
    "check_context_requirements",
    "format_context_prompt",
]
