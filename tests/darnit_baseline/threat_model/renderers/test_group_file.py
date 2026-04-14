"""Tests for the per-class detail file renderer (T017)."""

from __future__ import annotations

from darnit_baseline.threat_model.discovery_models import (
    CandidateFinding,
    CodeSnippet,
    FindingGroup,
    FindingSource,
    Location,
)
from darnit_baseline.threat_model.models import StrideCategory
from darnit_baseline.threat_model.renderers.group_file import render_group_file

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


def _instance_table_data_rows(output: str) -> list[str]:
    """Extract data rows from the All Instances table."""
    lines = output.splitlines()
    in_section = False
    table_rows: list[str] = []
    header_seen = 0
    for line in lines:
        if "## All Instances" in line:
            in_section = True
            header_seen = 0
            continue
        if in_section:
            if line.startswith("|"):
                header_seen += 1
                if header_seen > 2:
                    table_rows.append(line)
            elif line.startswith("#") and table_rows:
                break
            elif not line.startswith("|") and header_seen > 2:
                # End of table (e.g. blank line or footnote)
                break
    return table_rows


# ---------------------------------------------------------------------------
# T017 tests
# ---------------------------------------------------------------------------


class TestT017GroupFile:
    """Per-class detail file rendering (T017)."""

    def test_has_class_name_heading(self) -> None:
        group = _make_group(title="Command Injection")
        output = render_group_file(group, {})
        assert output.startswith("# Command Injection\n")

    def test_shows_stride_category(self) -> None:
        group = _make_group(category=StrideCategory.TAMPERING)
        output = render_group_file(group, {})
        assert "Tampering" in output

    def test_mitigation_section_present(self) -> None:
        hint = "Use parameterized APIs."
        group = _make_group(mitigation_hint=hint)
        output = render_group_file(group, {})
        assert "## Mitigation" in output
        assert hint in output

    def test_mitigation_fallback_when_no_hint(self) -> None:
        group = _make_group(mitigation_hint="")
        output = render_group_file(group, {})
        assert "## Mitigation" in output
        assert "No specific guidance" in output

    def test_representative_snippets_max_3(self) -> None:
        group = _make_group(n_findings=10)
        output = render_group_file(group, {})
        details_count = output.count("<details>")
        assert details_count <= 3

    def test_instance_table_row_count_equals_findings(self) -> None:
        group = _make_group(n_findings=7)
        output = render_group_file(group, {})
        rows = _instance_table_data_rows(output)
        assert len(rows) == 7

    def test_status_defaults_to_unmitigated(self) -> None:
        group = _make_group(n_findings=4)
        output = render_group_file(group, {})
        rows = _instance_table_data_rows(output)
        for row in rows:
            assert "Unmitigated" in row

    def test_no_per_row_code_blocks(self) -> None:
        group = _make_group(n_findings=5)
        output = render_group_file(group, {})
        rows = _instance_table_data_rows(output)
        for row in rows:
            assert "```" not in row
