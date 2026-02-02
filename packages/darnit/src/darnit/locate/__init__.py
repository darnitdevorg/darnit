"""Unified evidence location system for darnit.

This package provides:
- UnifiedLocator: Service for locating evidence with .project/ integration
- Tool output normalizer: Converts external tool outputs to CheckOutput contract
- Models: FoundEvidence, LocateResult, CheckOutput

The locate system implements a three-phase lookup:
1. Check .project/ configuration references first
2. Fall back to pattern-based discovery
3. Optionally use LLM hints for investigation fallback

All check adapters (builtin, command, script) must return CheckOutput,
which enables:
- Consistent status reporting (pass/fail/error/inconclusive)
- Evidence tracking for .project/ sync
- Remediation context (issues, suggestions)
"""

from .locator import UnifiedLocator
from .models import (
    CheckOutput,
    # Core models
    FoundEvidence,
    LocateResult,
    create_error_output,
    create_fail_output,
    create_inconclusive_output,
    # Factory functions
    create_pass_output,
)
from .normalizer import (
    extract_jsonpath,
    normalize_scorecard_output,
    normalize_tool_output,
)

__all__ = [
    # Core models
    "FoundEvidence",
    "LocateResult",
    "CheckOutput",
    # Factory functions
    "create_pass_output",
    "create_fail_output",
    "create_error_output",
    "create_inconclusive_output",
    # Locator
    "UnifiedLocator",
    # Normalizer
    "extract_jsonpath",
    "normalize_tool_output",
    "normalize_scorecard_output",
]
