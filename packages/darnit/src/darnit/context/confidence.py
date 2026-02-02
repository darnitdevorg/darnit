"""Confidence scoring for context detection.

This module provides utilities for calculating confidence scores from
multiple detection signals. The confidence score determines whether
the user needs to confirm auto-detected values.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalSource(Enum):
    """Sources of context detection signals.

    Ordered by reliability (higher = more reliable).
    """

    USER_CONFIRMED = "user_confirmed"  # Explicit user confirmation
    EXPLICIT_FILE = "explicit_file"  # MAINTAINERS.md, CODEOWNERS, etc.
    PROJECT_MANIFEST = "project_manifest"  # package.json, pyproject.toml authors
    GIT_HISTORY = "git_history"  # Top contributors from git log
    GITHUB_API = "github_api"  # GitHub collaborators API
    PATTERN_MATCH = "pattern_match"  # README mentions, comments


# Weights by source reliability
SIGNAL_WEIGHTS: dict[SignalSource, float] = {
    SignalSource.USER_CONFIRMED: 1.0,
    SignalSource.EXPLICIT_FILE: 0.9,
    SignalSource.PROJECT_MANIFEST: 0.8,
    SignalSource.GITHUB_API: 0.7,
    SignalSource.GIT_HISTORY: 0.6,
    SignalSource.PATTERN_MATCH: 0.5,
}


@dataclass
class ContextSignal:
    """A signal from a single detection source.

    Attributes:
        source: Where this signal came from
        value: The detected value(s)
        raw_confidence: The confidence from this source alone (0.0-1.0)
        method: Description of detection method
        evidence: Supporting evidence (file paths, API responses, etc.)
    """

    source: SignalSource
    value: Any
    raw_confidence: float = 0.5
    method: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CombinedConfidence:
    """Result of combining multiple signals.

    Attributes:
        confidence: Final combined confidence score (0.0-1.0)
        value: The resolved value (from highest-confidence signal or consensus)
        signals: All signals that contributed
        agreement_factor: How much signals agreed (0.0-1.0)
        reasoning: Human-readable explanation of confidence calculation
    """

    confidence: float
    value: Any
    signals: list[ContextSignal] = field(default_factory=list)
    agreement_factor: float = 1.0
    reasoning: str = ""


def calculate_confidence(signals: list[ContextSignal]) -> CombinedConfidence:
    """Calculate combined confidence from multiple detection signals.

    The algorithm:
    1. Weight each signal by its source reliability
    2. Calculate agreement factor (do signals agree on the same value?)
    3. Boost confidence if multiple independent sources agree
    4. Reduce confidence if sources conflict

    Args:
        signals: List of detection signals

    Returns:
        CombinedConfidence with final score and reasoning
    """
    if not signals:
        return CombinedConfidence(
            confidence=0.0,
            value=None,
            signals=[],
            agreement_factor=0.0,
            reasoning="No detection signals available",
        )

    if len(signals) == 1:
        signal = signals[0]
        weight = SIGNAL_WEIGHTS.get(signal.source, 0.5)
        confidence = signal.raw_confidence * weight
        return CombinedConfidence(
            confidence=confidence,
            value=signal.value,
            signals=signals,
            agreement_factor=1.0,
            reasoning=f"Single source ({signal.source.value}): {confidence:.0%} confidence",
        )

    # Sort signals by weight (highest first)
    sorted_signals = sorted(
        signals,
        key=lambda s: SIGNAL_WEIGHTS.get(s.source, 0.5) * s.raw_confidence,
        reverse=True,
    )

    # Get the primary value (from highest-weighted signal)
    primary_signal = sorted_signals[0]
    primary_value = primary_signal.value

    # Calculate agreement factor
    agreement_factor = _calculate_agreement(signals, primary_value)

    # Calculate weighted confidence
    total_weighted_confidence = 0.0
    total_weight = 0.0

    for signal in signals:
        weight = SIGNAL_WEIGHTS.get(signal.source, 0.5)
        total_weighted_confidence += signal.raw_confidence * weight
        total_weight += weight

    base_confidence = total_weighted_confidence / total_weight if total_weight > 0 else 0.0

    # Boost for multiple agreeing sources
    agreement_boost = 0.0
    if agreement_factor >= 0.8 and len(signals) >= 2:
        agreement_boost = 0.1  # 10% boost for strong agreement
    elif agreement_factor >= 0.5 and len(signals) >= 2:
        agreement_boost = 0.05  # 5% boost for moderate agreement

    # Penalty for conflicting sources
    conflict_penalty = 0.0
    if agreement_factor < 0.3:
        conflict_penalty = 0.15  # 15% penalty for major conflicts

    # Calculate final confidence
    final_confidence = min(1.0, max(0.0, base_confidence + agreement_boost - conflict_penalty))

    # Generate reasoning
    source_names = [s.source.value for s in signals]
    reasoning_parts = [
        f"Combined {len(signals)} signals ({', '.join(source_names)})",
        f"base confidence: {base_confidence:.0%}",
        f"agreement: {agreement_factor:.0%}",
    ]
    if agreement_boost > 0:
        reasoning_parts.append(f"+{agreement_boost:.0%} agreement boost")
    if conflict_penalty > 0:
        reasoning_parts.append(f"-{conflict_penalty:.0%} conflict penalty")
    reasoning_parts.append(f"final: {final_confidence:.0%}")

    return CombinedConfidence(
        confidence=final_confidence,
        value=primary_value,
        signals=signals,
        agreement_factor=agreement_factor,
        reasoning=" | ".join(reasoning_parts),
    )


def _calculate_agreement(signals: list[ContextSignal], primary_value: Any) -> float:
    """Calculate how much signals agree on the primary value.

    For list values (like maintainers), calculates Jaccard similarity.
    For scalar values, calculates exact match percentage.

    Args:
        signals: List of signals
        primary_value: The value to compare against

    Returns:
        Agreement factor (0.0-1.0)
    """
    if not signals or primary_value is None:
        return 0.0

    if len(signals) == 1:
        return 1.0

    if isinstance(primary_value, list):
        return _list_agreement(signals, primary_value)
    else:
        return _scalar_agreement(signals, primary_value)


def _list_agreement(signals: list[ContextSignal], primary_value: list[Any]) -> float:
    """Calculate agreement for list values using Jaccard similarity."""
    if not signals or not primary_value:
        return 0.0

    primary_set = set(_normalize_list_values(primary_value))
    if not primary_set:
        return 0.0

    agreements = []
    for signal in signals:
        if signal.value is None:
            continue

        signal_values = signal.value if isinstance(signal.value, list) else [signal.value]
        signal_set = set(_normalize_list_values(signal_values))

        if not signal_set:
            continue

        # Jaccard similarity: intersection / union
        intersection = primary_set & signal_set
        union = primary_set | signal_set
        if union:
            similarity = len(intersection) / len(union)
            agreements.append(similarity)

    return sum(agreements) / len(agreements) if agreements else 0.0


def _scalar_agreement(signals: list[ContextSignal], primary_value: Any) -> float:
    """Calculate agreement for scalar values using exact match."""
    if not signals:
        return 0.0

    matches = sum(
        1 for s in signals
        if s.value is not None and _values_equal(s.value, primary_value)
    )
    return matches / len(signals)


def _normalize_list_values(values: list[Any]) -> list[str]:
    """Normalize list values for comparison (lowercase, strip @)."""
    normalized = []
    for v in values:
        if isinstance(v, str):
            # Normalize GitHub usernames: lowercase, strip leading @
            s = v.lower().lstrip("@").strip()
            if s:
                normalized.append(s)
    return normalized


def _values_equal(a: Any, b: Any) -> bool:
    """Check if two values are equal (with normalization)."""
    if isinstance(a, str) and isinstance(b, str):
        return a.lower().strip() == b.lower().strip()
    return a == b


def format_confidence_explanation(result: CombinedConfidence) -> str:
    """Format a human-readable explanation of the confidence calculation.

    Args:
        result: The combined confidence result

    Returns:
        Markdown-formatted explanation
    """
    lines = []
    lines.append(f"**Confidence: {result.confidence:.0%}**")
    lines.append("")

    if result.signals:
        lines.append("**Detection sources:**")
        for signal in result.signals:
            weight = SIGNAL_WEIGHTS.get(signal.source, 0.5)
            lines.append(
                f"- {signal.source.value}: "
                f"{signal.raw_confidence:.0%} raw "
                f"(weight: {weight:.0%})"
            )
            if signal.method:
                lines.append(f"  Method: {signal.method}")

    lines.append("")
    lines.append(f"**Reasoning:** {result.reasoning}")

    if result.agreement_factor < 1.0:
        lines.append("")
        lines.append(f"**Agreement:** {result.agreement_factor:.0%}")
        if result.agreement_factor < 0.5:
            lines.append("⚠️ Sources have conflicting values - please verify")

    return "\n".join(lines)


__all__ = [
    "SignalSource",
    "ContextSignal",
    "CombinedConfidence",
    "SIGNAL_WEIGHTS",
    "calculate_confidence",
    "format_confidence_explanation",
]
