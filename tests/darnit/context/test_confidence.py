"""Unit tests for context detection confidence scoring (darnit.context.confidence)."""

from __future__ import annotations

import pytest

from darnit.context.confidence import (
    SIGNAL_WEIGHTS,
    CombinedConfidence,
    ContextSignal,
    SignalSource,
    _calculate_agreement,
    _list_agreement,
    _normalize_list_values,
    _scalar_agreement,
    _values_equal,
    calculate_confidence,
    format_confidence_explanation,
)


@pytest.mark.unit
class TestSignalSourceAndWeights:
    """Tests for SignalSource enumeration and configured weights."""

    def test_signal_source_enum_values(self) -> None:
        expected = {
            "user_confirmed",
            "explicit_file",
            "project_manifest",
            "git_history",
            "github_api",
            "pattern_match",
        }
        actual = {s.value for s in SignalSource}
        assert actual == expected

    def test_signal_weights_monotonic_ordering(self) -> None:
        assert SIGNAL_WEIGHTS[SignalSource.USER_CONFIRMED] == 1.0
        assert SIGNAL_WEIGHTS[SignalSource.EXPLICIT_FILE] == 0.9
        assert SIGNAL_WEIGHTS[SignalSource.PROJECT_MANIFEST] == 0.8
        assert SIGNAL_WEIGHTS[SignalSource.GITHUB_API] == 0.7
        assert SIGNAL_WEIGHTS[SignalSource.GIT_HISTORY] == 0.6
        assert SIGNAL_WEIGHTS[SignalSource.PATTERN_MATCH] == 0.5


@pytest.mark.unit
class TestCalculateConfidenceEmptyAndSingle:
    """Tests for base cases: empty and single-signal calculations."""

    def test_empty_signals_list_defaults(self) -> None:
        result = calculate_confidence([])
        assert result.confidence == 0.0
        assert result.value is None
        assert result.signals == []
        assert result.agreement_factor == 0.0
        assert "No detection signals available" in result.reasoning

    def test_single_signal_weighted_confidence(self) -> None:
        signal = ContextSignal(
            source=SignalSource.EXPLICIT_FILE,
            value="Apache-2.0",
            raw_confidence=0.9,
            method="LICENSE file header",
        )
        result = calculate_confidence([signal])
        expected_conf = 0.9 * 0.9  # 0.81
        assert pytest.approx(result.confidence) == expected_conf
        assert result.value == "Apache-2.0"
        assert result.agreement_factor == 1.0
        assert "Single source (explicit_file): 81% confidence" in result.reasoning


@pytest.mark.unit
class TestCalculateConfidenceMultipleSignals:
    """Tests for multi-signal combinations, agreement boosts, and conflict penalties."""

    def test_strong_agreement_boost(self) -> None:
        s1 = ContextSignal(source=SignalSource.EXPLICIT_FILE, value="MIT", raw_confidence=1.0)
        s2 = ContextSignal(source=SignalSource.PROJECT_MANIFEST, value="MIT", raw_confidence=1.0)

        result = calculate_confidence([s1, s2])
        # base confidence = (1.0 * 0.9 + 1.0 * 0.8) / (0.9 + 0.8) = 1.7 / 1.7 = 1.0
        # agreement factor = 1.0 -> +10% boost clamped at 1.0
        assert result.confidence == 1.0
        assert result.agreement_factor == 1.0
        assert "+10% agreement boost" in result.reasoning

    def test_conflict_penalty(self) -> None:
        # primary value from highest weighted signal (EXPLICIT_FILE weight 0.9)
        s1 = ContextSignal(source=SignalSource.EXPLICIT_FILE, value="MIT", raw_confidence=0.8)
        # 3 conflicting signals with different values
        s2 = ContextSignal(source=SignalSource.PROJECT_MANIFEST, value="Apache-2.0", raw_confidence=0.8)
        s3 = ContextSignal(source=SignalSource.PATTERN_MATCH, value="BSD-3-Clause", raw_confidence=0.8)
        s4 = ContextSignal(source=SignalSource.PATTERN_MATCH, value="GPL-3.0", raw_confidence=0.8)

        result = calculate_confidence([s1, s2, s3, s4])
        # agreement = 1 match out of 4 = 0.25 (< 0.3) -> triggers -15% conflict penalty
        assert result.agreement_factor == 0.25
        assert "-15% conflict penalty" in result.reasoning

    def test_moderate_agreement_boost(self) -> None:
        # List maintainers: partial overlap yielding moderate agreement (between 0.5 and 0.8)
        s1 = ContextSignal(source=SignalSource.EXPLICIT_FILE, value=["alice", "bob"], raw_confidence=0.8)
        s2 = ContextSignal(source=SignalSource.GIT_HISTORY, value=["alice"], raw_confidence=0.8)

        # primary set: {'alice', 'bob'}
        # s1 similarity: 2/2 = 1.0; s2 similarity: 1/2 = 0.5 -> avg agreement = 0.75
        result = calculate_confidence([s1, s2])
        assert 0.5 <= result.agreement_factor < 0.8
        assert "+5% agreement boost" in result.reasoning


@pytest.mark.unit
class TestAgreementHelpers:
    """Tests for scalar and list normalization and agreement metrics."""

    def test_values_equal_normalization(self) -> None:
        assert _values_equal("MIT", "mit")
        assert _values_equal("  Apache-2.0  ", "apache-2.0")
        assert not _values_equal("MIT", "BSD")
        assert _values_equal(123, 123)
        assert not _values_equal(123, 456)

    def test_normalize_list_values_strips_at_and_lowercases(self) -> None:
        raw = ["@Alice", "@bob", "Charlie", "", None, 42]
        normalized = _normalize_list_values(raw)  # type: ignore[arg-type]
        assert normalized == ["alice", "bob", "charlie"]

    def test_scalar_agreement_exact_and_partial(self) -> None:
        s1 = ContextSignal(source=SignalSource.EXPLICIT_FILE, value="MIT")
        s2 = ContextSignal(source=SignalSource.PATTERN_MATCH, value="mit")
        s3 = ContextSignal(source=SignalSource.GITHUB_API, value="Apache-2.0")

        assert _scalar_agreement([s1, s2, s3], "MIT") == pytest.approx(2 / 3)
        assert _scalar_agreement([], "MIT") == 0.0

    def test_list_agreement_jaccard(self) -> None:
        s1 = ContextSignal(source=SignalSource.EXPLICIT_FILE, value=["@alice", "@bob"])
        s2 = ContextSignal(source=SignalSource.GITHUB_API, value=["@bob", "@charlie"])

        # primary value: ['alice', 'bob']
        # s1: {'alice', 'bob'} -> intersection 2, union 2 = 1.0
        # s2: {'bob', 'charlie'} -> intersection 1, union 3 = 0.3333...
        # avg = (1.0 + 1/3) / 2 = 2/3 = 0.6666...
        agreement = _list_agreement([s1, s2], ["alice", "bob"])
        assert pytest.approx(agreement) == 2 / 3

    def test_calculate_agreement_dispatcher_and_edge_cases(self) -> None:
        assert _calculate_agreement([], "val") == 0.0
        assert _calculate_agreement([ContextSignal(SignalSource.USER_CONFIRMED, "val")], None) == 0.0
        assert _calculate_agreement([ContextSignal(SignalSource.USER_CONFIRMED, "val")], "val") == 1.0


@pytest.mark.unit
class TestFormatConfidenceExplanation:
    """Tests for markdown output formatting of CombinedConfidence."""

    def test_format_explanation_full(self) -> None:
        result = CombinedConfidence(
            confidence=0.85,
            value="Apache-2.0",
            signals=[
                ContextSignal(
                    source=SignalSource.EXPLICIT_FILE,
                    value="Apache-2.0",
                    raw_confidence=0.9,
                    method="Found LICENSE.md",
                ),
            ],
            agreement_factor=0.4,
            reasoning="base confidence: 85% | agreement: 40%",
        )

        md = format_confidence_explanation(result)
        assert "**Confidence: 85%**" in md
        assert "**Detection sources:**" in md
        assert "- explicit_file: 90% raw (weight: 90%)" in md
        assert "Method: Found LICENSE.md" in md
        assert "**Reasoning:** base confidence: 85% | agreement: 40%" in md
        assert "**Agreement:** 40%" in md
        assert "⚠️ Sources have conflicting values - please verify" in md
