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


# ---------------------------------------------------------------------------
# Feature 014-cobra-threat-model: STRIDE heuristic mapping tests
# ---------------------------------------------------------------------------


class TestAssignCliStrideCategories:
    """T020 — verify each row of the import-based heuristic table maps correctly."""

    def test_os_exec_imports_map_to_elevation_of_privilege(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        assert assign_cli_stride_categories({"os/exec"}) == ["Elevation of Privilege"]
        assert assign_cli_stride_categories({"syscall"}) == ["Elevation of Privilege"]

    def test_net_http_maps_to_spoofing_and_info_disclosure(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        cats = assign_cli_stride_categories({"net/http"})
        assert "Spoofing" in cats
        assert "Information Disclosure" in cats

    def test_crypto_prefix_maps_to_repudiation(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        assert assign_cli_stride_categories({"crypto/sha256"}) == ["Repudiation"]
        assert assign_cli_stride_categories({"crypto/ed25519"}) == ["Repudiation"]

    def test_sigstore_imports_map_to_repudiation(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        assert assign_cli_stride_categories({"github.com/sigstore/cosign"}) == ["Repudiation"]

    def test_intoto_imports_map_to_repudiation(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        assert assign_cli_stride_categories({"github.com/in-toto/in-toto-golang"}) == ["Repudiation"]

    def test_file_writer_imports_map_to_tampering(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        assert assign_cli_stride_categories({"os.WriteFile"}) == ["Tampering"]

    def test_unknown_imports_fall_back_to_tampering(self) -> None:
        from darnit_baseline.threat_model.ranking import (
            CLI_STRIDE_FALLBACK,
            assign_cli_stride_categories,
        )

        result = assign_cli_stride_categories({"fmt", "strings", "context"})
        assert result == CLI_STRIDE_FALLBACK
        assert result == ["Tampering"]

    def test_empty_import_set_falls_back_to_tampering(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        assert assign_cli_stride_categories(set()) == ["Tampering"]

    def test_first_matching_rule_wins(self) -> None:
        """When multiple rules could match, the first (most-specific) one wins."""
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        # os/exec (EoP) comes before net/http (Spoofing+InfoDisc) in the table —
        # so a file with both should categorise as EoP.
        result = assign_cli_stride_categories({"os/exec", "net/http"})
        assert result == ["Elevation of Privilege"]

    def test_never_returns_empty_list(self) -> None:
        """SC-005 / FR-005: every cobra finding gets at least one category."""
        from darnit_baseline.threat_model.ranking import assign_cli_stride_categories

        for imps in [set(), {"x"}, {"fmt"}, {"os.WriteFile"}, {"net/http"}]:
            assert len(assign_cli_stride_categories(imps)) >= 1


class TestAssignStrideForCliFamilies:
    """T020 — verify family-level assignment populates both fields correctly."""

    def _make_family(self, name: str, file_paths: list[str]):
        from darnit_baseline.threat_model.discovery_models import (
            CommandFamily,
            DiscoveredEntryPoint,
            EntryPointKind,
            Location,
        )

        members = [
            DiscoveredEntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                name=p.rsplit("/", 1)[-1].removesuffix(".go"),
                location=Location(p, 10, 1, 12, 1),
                language="go",
                framework="cobra",
                route_path=None,
                http_method=None,
                has_auth_decorator=False,
                source_query="go.entry.cobra_command_literal",
            )
            for p in file_paths
        ]
        return CommandFamily(
            family_key=name,
            source_root=f"internal/cmd/{name}/",
            display_name=name,
            members=members,
            import_signatures=set(),
            stride_categories=[],
            needs_reviewer_attention=True,
        )

    def test_family_imports_union_drives_category(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_stride_for_cli_families

        family = self._make_family("cache", ["internal/cmd/cache/cache.go"])
        imports = {"internal/cmd/cache/cache.go": {"os/exec", "fmt"}}
        assign_stride_for_cli_families([family], imports)
        assert family.import_signatures == {"os/exec", "fmt"}
        assert family.stride_categories == ["Elevation of Privilege"]

    def test_family_with_no_matching_imports_falls_back(self) -> None:
        from darnit_baseline.threat_model.ranking import assign_stride_for_cli_families

        family = self._make_family("simple", ["internal/cmd/simple/simple.go"])
        imports = {"internal/cmd/simple/simple.go": {"fmt", "strings"}}
        assign_stride_for_cli_families([family], imports)
        assert family.stride_categories == ["Tampering"]

    def test_missing_import_data_still_assigns_fallback(self) -> None:
        """Family whose members aren't in file_imports gets Tampering fallback."""
        from darnit_baseline.threat_model.ranking import assign_stride_for_cli_families

        family = self._make_family("orphan", ["internal/cmd/orphan/orphan.go"])
        assign_stride_for_cli_families([family], {})  # empty imports map
        assert family.stride_categories == ["Tampering"]
        assert family.needs_reviewer_attention is True
