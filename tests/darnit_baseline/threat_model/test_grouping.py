"""Tests for the finding grouping module."""

from __future__ import annotations

import pytest

from darnit_baseline.threat_model.discovery_models import (
    CandidateFinding,
    CodeSnippet,
    FindingGroup,
    FindingSource,
    Location,
)
from darnit_baseline.threat_model.grouping import group_by_query_id
from darnit_baseline.threat_model.models import StrideCategory


def _make_finding(
    query_id: str = "python.sink.dangerous_attr",
    severity: int = 5,
    confidence: float = 0.8,
    title: str = "Test finding",
    category: StrideCategory = StrideCategory.TAMPERING,
    file: str = "src/app.py",
    line: int = 10,
) -> CandidateFinding:
    """Helper to construct a minimal CandidateFinding."""
    return CandidateFinding(
        category=category,
        title=title,
        source=FindingSource.TREE_SITTER_STRUCTURAL,
        primary_location=Location(file=file, line=line, column=1, end_line=line, end_column=20),
        related_assets=(),
        code_snippet=CodeSnippet(lines=("x = 1",), start_line=line, marker_line=line),
        severity=severity,
        confidence=confidence,
        rationale="test rationale",
        query_id=query_id,
    )


class TestGroupByQueryId:
    def test_empty_input(self) -> None:
        assert group_by_query_id([]) == []

    def test_single_finding_single_group(self) -> None:
        f = _make_finding(query_id="python.sink.subprocess_shell")
        groups = group_by_query_id([f])
        assert len(groups) == 1
        assert groups[0].query_id == "python.sink.subprocess_shell"
        assert groups[0].slug == "python-sink-subprocess_shell"
        assert len(groups[0].findings) == 1

    def test_multiple_findings_same_query(self) -> None:
        f1 = _make_finding(query_id="python.sink.dangerous_attr", severity=9)
        f2 = _make_finding(query_id="python.sink.dangerous_attr", severity=5)
        groups = group_by_query_id([f1, f2])
        assert len(groups) == 1
        assert len(groups[0].findings) == 2

    def test_multiple_query_ids(self) -> None:
        f1 = _make_finding(query_id="python.sink.subprocess_shell", severity=9)
        f2 = _make_finding(query_id="python.sink.ssrf", severity=7)
        f3 = _make_finding(query_id="python.sink.subprocess_shell", severity=5)
        groups = group_by_query_id([f1, f2, f3])
        assert len(groups) == 2
        # Sorted by max_severity_score desc — subprocess (9*0.8=7.2) > ssrf (7*0.8=5.6)
        assert groups[0].query_id == "python.sink.subprocess_shell"
        assert groups[1].query_id == "python.sink.ssrf"

    def test_slug_derivation(self) -> None:
        f = _make_finding(query_id="go.entry.selector_string_arg")
        groups = group_by_query_id([f])
        assert groups[0].slug == "go-entry-selector_string_arg"

    def test_class_name_from_highest_severity(self) -> None:
        f1 = _make_finding(query_id="test.q", severity=3, title="Low finding")
        f2 = _make_finding(query_id="test.q", severity=9, title="Critical finding")
        groups = group_by_query_id([f1, f2])
        assert groups[0].class_name == "Critical finding"

    def test_max_severity_score(self) -> None:
        f1 = _make_finding(query_id="test.q", severity=5, confidence=0.8)
        f2 = _make_finding(query_id="test.q", severity=9, confidence=1.0)
        groups = group_by_query_id([f1, f2])
        assert groups[0].max_severity_score == 9.0

    def test_ordering_by_max_severity(self) -> None:
        low = _make_finding(query_id="low.q", severity=2, confidence=0.5)
        high = _make_finding(query_id="high.q", severity=9, confidence=1.0)
        med = _make_finding(query_id="med.q", severity=5, confidence=0.8)
        groups = group_by_query_id([low, high, med])
        assert [g.query_id for g in groups] == ["high.q", "med.q", "low.q"]

    def test_all_findings_share_query_id(self) -> None:
        f1 = _make_finding(query_id="test.q", file="a.py", line=1)
        f2 = _make_finding(query_id="test.q", file="b.py", line=2)
        f3 = _make_finding(query_id="test.q", file="c.py", line=3)
        groups = group_by_query_id([f1, f2, f3])
        for finding in groups[0].findings:
            assert finding.query_id == "test.q"

    def test_mitigation_hint_from_registry(self) -> None:
        f = _make_finding(query_id="python.sink.dangerous_attr")

        class FakeQuery:
            mitigation_hint = "Use parameterized APIs instead."

        registry = {"python.sink.dangerous_attr": FakeQuery()}
        groups = group_by_query_id([f], query_registries=registry)
        assert groups[0].mitigation_hint == "Use parameterized APIs instead."

    def test_mitigation_hint_missing_from_registry(self) -> None:
        f = _make_finding(query_id="unknown.query")
        groups = group_by_query_id([f], query_registries={})
        assert groups[0].mitigation_hint == ""


class TestFindingGroupValidation:
    def test_empty_findings_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one finding"):
            FindingGroup(
                query_id="test.q",
                slug="test-q",
                stride_category=StrideCategory.TAMPERING,
                class_name="Test",
                mitigation_hint="",
                findings=(),
                max_severity_score=0.0,
            )

    def test_mismatched_query_id_raises(self) -> None:
        f = _make_finding(query_id="other.q")
        with pytest.raises(ValueError, match="same query_id"):
            FindingGroup(
                query_id="test.q",
                slug="test-q",
                stride_category=StrideCategory.TAMPERING,
                class_name="Test",
                mitigation_hint="",
                findings=(f,),
                max_severity_score=0.0,
            )

    def test_wrong_slug_raises(self) -> None:
        f = _make_finding(query_id="test.q")
        with pytest.raises(ValueError, match="slug"):
            FindingGroup(
                query_id="test.q",
                slug="wrong_slug",
                stride_category=StrideCategory.TAMPERING,
                class_name="Test",
                mitigation_hint="",
                findings=(f,),
                max_severity_score=0.0,
            )
