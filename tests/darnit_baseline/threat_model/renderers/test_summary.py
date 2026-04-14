"""Tests for the SUMMARY.md renderer (T016 + T018a)."""

from __future__ import annotations

from darnit_baseline.threat_model.discovery_models import (
    CandidateFinding,
    CodeSnippet,
    DiscoveryResult,
    FindingGroup,
    FindingSource,
    Location,
)
from darnit_baseline.threat_model.models import StrideCategory
from darnit_baseline.threat_model.renderers.common import GeneratorOptions
from darnit_baseline.threat_model.renderers.summary import render_summary

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_finding(
    query_id: str = "python.sink.dangerous_attr",
    severity: int = 5,
    confidence: float = 0.8,
    title: str = "Test finding",
    category: StrideCategory = StrideCategory.TAMPERING,
    file: str = "src/app.py",
    line: int = 10,
) -> CandidateFinding:
    return CandidateFinding(
        category=category,
        title=title,
        source=FindingSource.TREE_SITTER_STRUCTURAL,
        primary_location=Location(file=file, line=line, column=1, end_line=line, end_column=20),
        related_assets=(),
        code_snippet=CodeSnippet(lines=("x = dangerous_call(input)",), start_line=line, marker_line=line),
        severity=severity,
        confidence=confidence,
        rationale="test rationale",
        query_id=query_id,
    )


def _make_group(
    query_id: str = "python.sink.dangerous_attr",
    n_findings: int = 3,
    severity: int = 7,
    confidence: float = 0.9,
    title: str = "Command Injection",
    category: StrideCategory = StrideCategory.TAMPERING,
    mitigation_hint: str = "Use parameterized APIs.",
) -> FindingGroup:
    findings = tuple(
        _make_finding(
            query_id=query_id,
            severity=severity,
            confidence=confidence,
            title=title,
            category=category,
            file=f"src/file{i}.py",
            line=10 + i,
        )
        for i in range(n_findings)
    )
    return FindingGroup(
        query_id=query_id,
        slug=query_id.replace(".", "-"),
        stride_category=category,
        class_name=title,
        mitigation_hint=mitigation_hint,
        findings=findings,
        max_severity_score=severity * confidence,
    )


_empty_result = DiscoveryResult()


def _table_data_rows(text: str, section_heading: str) -> list[str]:
    """Extract table data rows (lines starting with '|') from a section.

    Skips the header row and the separator (second) row.
    """
    lines = text.splitlines()
    in_section = False
    table_rows: list[str] = []
    header_seen = 0
    for line in lines:
        if section_heading in line:
            in_section = True
            header_seen = 0
            continue
        if in_section:
            if line.startswith("|"):
                header_seen += 1
                if header_seen > 2:
                    # data rows start after header + separator
                    table_rows.append(line)
            elif line.startswith("#") and table_rows:
                # next section reached
                break
    return table_rows


# ---------------------------------------------------------------------------
# T016 tests
# ---------------------------------------------------------------------------


class TestT016Summary:
    """Core SUMMARY.md rendering (T016)."""

    def test_has_required_sections(self) -> None:
        groups = [_make_group()]
        output = render_summary(groups, {}, _empty_result, GeneratorOptions())
        assert "## Executive Summary" in output
        assert "## Top Risks" in output

    def test_top_risks_one_row_per_group(self) -> None:
        groups = [_make_group(query_id=f"python.sink.type{i}", title=f"Finding class {i}") for i in range(5)]
        output = render_summary(groups, {}, _empty_result, GeneratorOptions())
        rows = _table_data_rows(output, "## Top Risks")
        assert len(rows) == 5

    def test_top_risks_cap_at_20(self) -> None:
        groups = [_make_group(query_id=f"python.sink.type{i}", title=f"Finding class {i}") for i in range(25)]
        output = render_summary(groups, {}, _empty_result, GeneratorOptions(top_risks_cap=20))
        rows = _table_data_rows(output, "## Top Risks")
        assert len(rows) <= 20
        assert "5 more" in output

    def test_unmitigated_section_shows_all_groups_when_no_sidecar(self) -> None:
        groups = [_make_group(query_id=f"python.sink.type{i}", title=f"Finding class {i}") for i in range(4)]
        output = render_summary(groups, {}, _empty_result, GeneratorOptions())
        rows = _table_data_rows(output, "## Unmitigated Findings")
        assert len(rows) == 4

    def test_summary_line_count(self) -> None:
        """Summary should stay bounded even with many groups/findings.

        With 30 groups x 10 findings each (300 findings total), the
        top-risks table is capped at 20, but the unmitigated section and
        recommendations sections list all groups/findings. The output
        must remain under 500 lines (a generous bound ensuring it's not
        a runaway).
        """
        groups = [
            _make_group(
                query_id=f"python.sink.type{i}",
                title=f"Finding class {i}",
                n_findings=10,
            )
            for i in range(30)
        ]
        output = render_summary(groups, {}, _empty_result, GeneratorOptions())
        line_count = len(output.splitlines())
        assert line_count <= 500, f"Expected <=500 lines, got {line_count}"


# ---------------------------------------------------------------------------
# T018a tests
# ---------------------------------------------------------------------------


class TestT018aEdgeCases:
    """Edge-case rendering for SUMMARY.md (T018a)."""

    def test_empty_scan_valid_output(self) -> None:
        output = render_summary([], {}, DiscoveryResult(), GeneratorOptions())
        # Valid markdown: starts with a heading
        assert output.startswith("# ")
        # Mentions zero findings
        assert "0" in output
        # No per-group detail file links like "findings/<slug>.md"
        # (the verification-prompt section may generically reference
        # the findings/ directory as an instruction, which is fine)
        import re

        detail_links = re.findall(r"findings/[a-z0-9_-]+\.md", output)
        assert len(detail_links) == 0, f"Expected no detail file links, found {detail_links}"

    def test_single_group_edge_case(self) -> None:
        groups = [_make_group()]
        output = render_summary(groups, {}, _empty_result, GeneratorOptions())

        # Exactly 1 data row in top-risks table
        rows = _table_data_rows(output, "## Top Risks")
        assert len(rows) == 1

        # No overflow line
        assert "more classes" not in output

        # 1 entry in unmitigated section
        unmitigated_rows = _table_data_rows(output, "## Unmitigated Findings")
        assert len(unmitigated_rows) == 1
