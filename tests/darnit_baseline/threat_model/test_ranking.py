"""Tests for darnit_baseline.threat_model.ranking."""

from __future__ import annotations

import pytest

from darnit_baseline.threat_model.discovery_models import (
    CandidateFinding,
    CodeSnippet,
    DataFlowStep,
    DataFlowTrace,
    FindingSource,
    Location,
    TrimmedOverflow,
)
from darnit_baseline.threat_model.models import StrideCategory
from darnit_baseline.threat_model.ranking import (
    apply_cap,
    confidence_for,
    rank_findings,
    severity_for,
)


def _loc(line: int = 10) -> Location:
    return Location(file="x.py", line=line, column=1, end_line=line, end_column=10)


def _snippet(line: int = 10) -> CodeSnippet:
    return CodeSnippet(lines=("x = 1",), start_line=line, marker_line=line)


def _mk(
    *,
    category: StrideCategory = StrideCategory.TAMPERING,
    source: FindingSource = FindingSource.TREE_SITTER_STRUCTURAL,
    severity: int = 6,
    confidence: float = 0.75,
    query_id: str = "q",
    line: int = 10,
    with_taint: bool = False,
) -> CandidateFinding:
    data_flow = None
    if source == FindingSource.OPENGREP_TAINT or with_taint:
        src_loc = _loc(line=line)
        data_flow = DataFlowTrace(
            source=DataFlowStep(location=src_loc, content="source"),
            intermediate=(),
            sink=DataFlowStep(location=src_loc, content="sink"),
        )
        if source != FindingSource.OPENGREP_TAINT:
            source = FindingSource.OPENGREP_TAINT
    return CandidateFinding(
        category=category,
        title="test finding",
        source=source,
        primary_location=_loc(line=line),
        related_assets=(),
        code_snippet=_snippet(line=line),
        severity=severity,
        confidence=confidence,
        rationale="test",
        query_id=query_id,
        data_flow=data_flow,
    )


class TestSeverityFor:
    def test_tampering_with_taint_is_highest(self) -> None:
        assert severity_for(StrideCategory.TAMPERING, has_taint_trace=True) == 9

    def test_tampering_without_taint(self) -> None:
        assert severity_for(StrideCategory.TAMPERING, has_taint_trace=False) == 6

    def test_repudiation_is_lowest(self) -> None:
        assert severity_for(StrideCategory.REPUDIATION, has_taint_trace=False) == 2


class TestConfidenceFor:
    def test_taint_is_1_0(self) -> None:
        assert confidence_for(FindingSource.OPENGREP_TAINT) == 1.0

    def test_opengrep_pattern_is_0_9(self) -> None:
        assert confidence_for(FindingSource.OPENGREP_PATTERN) == 0.9

    def test_structural_constructor_is_0_9(self) -> None:
        assert confidence_for(FindingSource.TREE_SITTER_STRUCTURAL, query_intent="constructor_call") == 0.9

    def test_structural_decorator_is_0_85(self) -> None:
        assert confidence_for(FindingSource.TREE_SITTER_STRUCTURAL, query_intent="decorator") == 0.85

    def test_structural_bare_call_is_0_6(self) -> None:
        assert confidence_for(FindingSource.TREE_SITTER_STRUCTURAL, query_intent="bare_call") == 0.6


class TestRankFindings:
    def test_orders_by_severity_times_confidence_desc(self) -> None:
        low = _mk(severity=3, confidence=0.5, query_id="low")  # 1.5
        high = _mk(severity=9, confidence=1.0, query_id="high")  # 9.0
        mid = _mk(severity=6, confidence=0.75, query_id="mid")  # 4.5
        ranked = rank_findings([low, high, mid])
        assert [f.query_id for f in ranked] == ["high", "mid", "low"]

    def test_is_stable_on_ties(self) -> None:
        a = _mk(severity=5, confidence=0.5, query_id="a")
        b = _mk(severity=5, confidence=0.5, query_id="b")
        ranked = rank_findings([b, a])
        # Same key → deterministic tiebreak on query_id
        assert [f.query_id for f in ranked] == ["a", "b"]


class TestApplyCap:
    def test_under_cap_returns_all_without_overflow(self) -> None:
        findings = [_mk(query_id=f"q{i}", line=i + 1) for i in range(5)]
        emitted, overflow = apply_cap(findings, max_findings=10)
        assert len(emitted) == 5
        assert overflow.total == 0
        assert overflow.by_category == {}

    def test_over_cap_returns_all_with_overflow_hint(self) -> None:
        # 10 findings, cap = 5. All 10 are returned; overflow describes
        # the 5 findings below the display threshold.
        findings = [_mk(severity=s, confidence=1.0, query_id=f"q{s}", line=s) for s in range(1, 11)]
        emitted, overflow = apply_cap(findings, max_findings=5)
        assert len(emitted) == 10  # No findings dropped
        assert overflow.total == 5  # 5 below display threshold
        assert overflow.by_category == {StrideCategory.TAMPERING: 5}

    def test_diversity_tiebreak_reorders_for_underrepresented(self) -> None:
        """If one category numerically dominates, the top N (display set)
        should have underrepresented categories promoted.  All findings are
        still returned."""
        # 8 tampering findings with severity 7, plus 2 spoofing findings with
        # severity 5. Cap = 5. The first 5 returned should have spoofing
        # promoted. All 10 findings are returned.
        tampering = [
            _mk(
                category=StrideCategory.TAMPERING,
                severity=7,
                confidence=1.0,
                query_id=f"t{i}",
                line=i + 1,
            )
            for i in range(8)
        ]
        spoofing = [
            _mk(
                category=StrideCategory.SPOOFING,
                severity=5,
                confidence=1.0,
                query_id=f"s{i}",
                line=i + 100,
            )
            for i in range(2)
        ]
        emitted, _ = apply_cap(tampering + spoofing, max_findings=5)
        assert len(emitted) == 10  # All returned
        # The first 5 (display set) should have spoofing promoted
        top5_categories = [f.category for f in emitted[:5]]
        tampering_count = top5_categories.count(StrideCategory.TAMPERING)
        assert tampering_count <= 3, (
            f"category-diversity rebalance should cap tampering at 60% of top 5; "
            f"got {tampering_count} ({top5_categories})"
        )

    def test_diversity_leaves_single_category_alone_when_no_swap_possible(
        self,
    ) -> None:
        """If only one category exists, rebalance cannot demote to anything.
        All findings are returned."""
        findings = [_mk(query_id=f"q{i}", line=i + 1) for i in range(8)]
        emitted, overflow = apply_cap(findings, max_findings=3)
        assert len(emitted) == 8  # All returned
        assert overflow.total == 5  # 5 below display threshold

    def test_zero_cap_returns_all_with_no_overflow(self) -> None:
        """With cap=0, all findings are returned and overflow is empty
        (zero-cap means 'no display threshold')."""
        findings = [_mk(query_id=f"q{i}", line=i + 1) for i in range(3)]
        emitted, overflow = apply_cap(findings, max_findings=0)
        assert len(emitted) == 3
        assert overflow.total == 0


class TestTrimmedOverflowInvariant:
    def test_total_matches_sum_of_by_category(self) -> None:
        ov = TrimmedOverflow(
            by_category={
                StrideCategory.TAMPERING: 2,
                StrideCategory.SPOOFING: 1,
            },
            total=3,
        )
        assert ov.total == 3

    def test_mismatched_total_raises(self) -> None:
        with pytest.raises(ValueError, match="total"):
            TrimmedOverflow(by_category={StrideCategory.TAMPERING: 1}, total=5)


class TestCandidateFindingInvariants:
    def test_severity_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            _mk(severity=11)

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            _mk(confidence=1.5)

    def test_taint_source_requires_data_flow(self) -> None:
        with pytest.raises(ValueError, match="data_flow"):
            CandidateFinding(
                category=StrideCategory.TAMPERING,
                title="x",
                source=FindingSource.OPENGREP_TAINT,
                primary_location=_loc(),
                related_assets=(),
                code_snippet=_snippet(),
                severity=9,
                confidence=1.0,
                rationale="x",
                query_id="q",
                data_flow=None,
            )

    def test_marker_line_must_match_primary_location(self) -> None:
        """The snippet's marker line must point at the finding's anchor line."""
        with pytest.raises(ValueError, match="marker_line"):
            CandidateFinding(
                category=StrideCategory.TAMPERING,
                title="x",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=_loc(line=42),
                related_assets=(),
                code_snippet=CodeSnippet(lines=("x = 1",), start_line=10, marker_line=10),
                severity=6,
                confidence=0.75,
                rationale="x",
                query_id="q",
            )


class TestSubprocessTieredScoring:
    """Verify three-tier subprocess scoring produces correct ranking order.

    The tiers (static, parameterized, dynamic, shell) use direct severity
    and confidence values assigned in ``_build_subprocess_finding`` rather
    than the generic ``severity_for``/``confidence_for`` matrix.
    """

    @staticmethod
    def _mk_tier(
        tier: str,
        severity: int,
        confidence: float,
        query_id: str,
        line: int,
    ) -> CandidateFinding:
        return _mk(
            severity=severity,
            confidence=confidence,
            query_id=query_id,
            line=line,
        )

    def test_static_lt_parameterized_lt_dynamic_lt_shell(self) -> None:
        static = self._mk_tier("static", severity=1, confidence=0.2, query_id="static", line=1)
        param = self._mk_tier("parameterized", severity=4, confidence=0.6, query_id="param", line=2)
        dynamic = self._mk_tier("dynamic", severity=6, confidence=0.8, query_id="dynamic", line=3)
        shell = self._mk_tier("shell", severity=8, confidence=0.9, query_id="shell", line=4)

        static_score = static.severity * static.confidence  # 0.2
        param_score = param.severity * param.confidence  # 2.4
        dynamic_score = dynamic.severity * dynamic.confidence  # 4.8
        shell_score = shell.severity * shell.confidence  # 7.2

        assert static_score < param_score < dynamic_score < shell_score

    def test_ranking_order_matches_tiers(self) -> None:
        static = self._mk_tier("static", severity=1, confidence=0.2, query_id="static", line=1)
        param = self._mk_tier("parameterized", severity=4, confidence=0.6, query_id="param", line=2)
        dynamic = self._mk_tier("dynamic", severity=6, confidence=0.8, query_id="dynamic", line=3)
        shell = self._mk_tier("shell", severity=8, confidence=0.9, query_id="shell", line=4)

        ranked = rank_findings([static, param, dynamic, shell])
        assert [f.query_id for f in ranked] == ["shell", "dynamic", "param", "static"]

    def test_static_below_display_threshold_when_higher_tiers_exist(self) -> None:
        """With a cap of 3, the static finding should be below the display
        threshold (overflow hint) while still being in the returned list."""
        static = self._mk_tier("static", severity=1, confidence=0.2, query_id="static", line=1)
        param = self._mk_tier("parameterized", severity=4, confidence=0.6, query_id="param", line=2)
        dynamic = self._mk_tier("dynamic", severity=6, confidence=0.8, query_id="dynamic", line=3)
        shell = self._mk_tier("shell", severity=8, confidence=0.9, query_id="shell", line=4)

        emitted, overflow = apply_cap([static, param, dynamic, shell], max_findings=3)
        assert len(emitted) == 4  # All findings returned
        # Static is last (below display threshold)
        top3_ids = {f.query_id for f in emitted[:3]}
        assert "static" not in top3_ids
        assert overflow.total == 1
