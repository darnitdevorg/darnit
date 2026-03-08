"""Context detection infrastructure for darnit framework.

This module provides progressive context detection using a sieve pattern:
1. DETERMINISTIC: Check explicit sources (MAINTAINERS.md, CODEOWNERS)
2. HEURISTIC: Pattern matching (git history, manifests)
3. API: External services (GitHub)
4. COMBINE: Aggregate signals with confidence scoring

The goal is to auto-detect values with confidence scores so users
see suggested values instead of empty prompts.

Example:
    from darnit.context import get_context_sieve

    sieve = get_context_sieve()
    result = sieve.detect("maintainers", "/path/to/repo", "owner", "repo")

    if result.is_high_confidence:
        # Confidence >= 90%, safe to use directly
        maintainers = result.value
    else:
        # Lower confidence, show to user for confirmation
        suggested = result.value
        confidence = result.confidence  # e.g., 0.75 for 75%
"""

from .collection import (
    coerce_context_value,
    parse_codeowners,
    parse_json_path,
    parse_markdown_list,
    parse_yaml_path,
    resolve_context_value,
    validate_context_value,
)
from .confidence import (
    SIGNAL_WEIGHTS,
    CombinedConfidence,
    ContextSignal,
    SignalSource,
    calculate_confidence,
    format_confidence_explanation,
)
from .dot_project import (
    DotProjectReader,
    DotProjectWriter,
    MaintainerEntry,
    MaintainerTeam,
    ProjectConfig,
    SecurityContact,
)
from .dot_project_mapper import DotProjectMapper
from .dot_project_merger import merge_configs
from .dot_project_org import OrgProjectResolver
from .inject import (
    create_check_context_with_project,
    get_project_value,
    has_project_value,
    inject_project_context,
)
from .sieve import (
    ContextDetectionResult,
    ContextSieve,
    get_context_sieve,
)

__all__ = [
    # Confidence scoring
    "SignalSource",
    "ContextSignal",
    "CombinedConfidence",
    "SIGNAL_WEIGHTS",
    "calculate_confidence",
    "format_confidence_explanation",
    # Context sieve
    "ContextSieve",
    "ContextDetectionResult",
    "get_context_sieve",
    # .project/ integration
    "DotProjectReader",
    "DotProjectWriter",
    "ProjectConfig",
    "SecurityContact",
    "MaintainerEntry",
    "MaintainerTeam",
    "DotProjectMapper",
    "OrgProjectResolver",
    "merge_configs",
    "inject_project_context",
    "create_check_context_with_project",
    "get_project_value",
    "has_project_value",
    # Context collection
    "parse_markdown_list",
    "parse_yaml_path",
    "parse_json_path",
    "parse_codeowners",
    "resolve_context_value",
    "validate_context_value",
    "coerce_context_value",
]
