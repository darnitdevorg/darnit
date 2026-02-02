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
        print(f"Maintainers: {result.value}")
    else:
        print(f"Detected (needs confirmation): {result.value}")
        print(f"Confidence: {result.confidence:.0%}")
"""

from .confidence import (
    SIGNAL_WEIGHTS,
    CombinedConfidence,
    ContextSignal,
    SignalSource,
    calculate_confidence,
    format_confidence_explanation,
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
]
