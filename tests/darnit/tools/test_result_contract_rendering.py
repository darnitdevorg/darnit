"""Reports render ERROR causes, PENDING kinds, and PASS candidates (feature 041, T051)."""

from __future__ import annotations

from typing import Any

import pytest

from darnit.cli import format_results_text
from darnit.harness.report import HarnessReport, HarnessSummary
from darnit.tools.audit import calculate_compliance, format_results_markdown, summarize_results

CANDIDATE = {
    "verdict": "pass",
    "reasoning": "The README explains installation and usage.",
    "cited_evidence": ["## Installation", "pip install example"],
    "model": "claude-sonnet-5",
    "model_version": "2026-08-01",
    "evidence_digest": "sha256:abc",
    "source": "mcp_agent",
}


def _results() -> list[dict[str, Any]]:
    return [
        {
            "id": "OSPS-AC-03.01",
            "status": "ERROR",
            "level": 1,
            "details": "gh api repos/o/r/branches/main/protection: HTTP 403",
            "authority": "dispositive",
            "concluded_by": "gh_api",
            "error_class": "auth",
            "error": {"class": "auth", "cause": "gh api repos/o/r/branches/main/protection: HTTP 403"},
        },
        {
            "id": "OSPS-GV-01.01",
            "status": "PENDING",
            "level": 1,
            "details": "LLM consultation required",
            "authority": "suggestive",
            "concluded_by": "none",
            "pending": {"kind": "llm_judgment"},
        },
        {
            "id": "OSPS-DO-01.01",
            "status": "PENDING",
            "level": 1,
            "details": "PASS candidate from a model judgment; not compliant until an operator confirms it",
            "authority": "suggestive",
            "concluded_by": "none",
            "pending": {"kind": "confirmation"},
            "candidate": dict(CANDIDATE),
        },
        {
            "id": "OSPS-VM-02.01",
            "status": "FAIL",
            "level": 1,
            "details": "Model finding: the policy denies having a process",
            "authority": "suggestive",
            "concluded_by": "llm_judgment",
        },
        {
            "id": "OSPS-DO-02.01",
            "status": "PASS",
            "level": 1,
            "details": "PASS candidate confirmed by @operator",
            "authority": "asserted",
            "concluded_by": "confirmation",
            "candidate": dict(CANDIDATE),
            "confirmation": {
                "confirmed_by": "@operator",
                "confirmed_at": "2026-09-27T00:00:00+00:00",
                "expires_at": "2027-09-27T00:00:00+00:00",
            },
        },
    ]


def _markdown(results: list[dict[str, Any]]) -> str:
    return format_results_markdown(
        owner="o",
        repo="r",
        results=results,
        summary=summarize_results(results),
        compliance=calculate_compliance(results, 1),
        level=1,
    )


def _block(markdown: str, control_id: str) -> str:
    lines = markdown.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"- **{control_id}**"))
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith("  ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _sections(markdown: str) -> dict[str, str]:
    """Detailed-results sections keyed by status (the word after the icon in each ``###`` heading)."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in markdown.splitlines():
        if line.startswith("### "):
            words = line.split()
            current = words[2] if len(words) > 2 else None
            sections.setdefault(current, [])
        elif line.startswith("## "):
            current = None
        elif current is not None:
            sections[current].append(line)
    return {status: "\n".join(lines) for status, lines in sections.items()}


@pytest.mark.unit
class TestAuditMarkdown:
    def test_error_names_its_class_and_says_it_is_not_a_finding(self) -> None:
        block = _block(_markdown(_results()), "OSPS-AC-03.01")

        assert "`[auth]`" in block
        assert "*Could not measure* (`auth`); this is not a finding about the project" in block

    def test_error_cause_is_shown_when_it_differs_from_details(self) -> None:
        results = _results()
        results[0]["details"] = "Branch protection could not be read"

        block = _block(_markdown(results), "OSPS-AC-03.01")

        assert block.endswith("this is not a finding about the project: gh api repos/o/r/branches/main/protection: HTTP 403")

    def test_pending_judgment_names_its_kind(self) -> None:
        block = _block(_markdown(_results()), "OSPS-GV-01.01")

        assert "*Awaiting a model judgment*" in block
        assert "at most make this a PASS candidate" in block

    def test_candidate_is_labelled_not_compliant_with_model_and_excerpt_count(self) -> None:
        markdown = _markdown(_results())
        block = _block(markdown, "OSPS-DO-01.01")

        assert (
            "*PASS candidate, not compliant until confirmed*: model judgment by "
            "`claude-sonnet-5 2026-08-01` (mcp_agent), 2 cited excerpt(s)"
        ) in block
        assert "only on the operator's explicit instruction" in block
        assert "confirm_project_data(" not in markdown

    def test_candidate_is_grouped_with_pending_not_pass(self) -> None:
        sections = _sections(_markdown(_results()))

        assert "OSPS-DO-01.01" not in sections["PASS"]
        assert "OSPS-DO-01.01" in sections["PENDING"]

    def test_model_finding_and_asserted_pass_are_labelled(self) -> None:
        markdown = _markdown(_results())

        assert "*Model finding*" in _block(markdown, "OSPS-VM-02.01")
        assert (
            "*Asserted*: PASS candidate confirmed by @operator at 2026-09-27T00:00:00+00:00 "
            "(expires 2027-09-27T00:00:00+00:00)"
        ) in _block(markdown, "OSPS-DO-02.01")

    def test_summary_and_level_line_split_pending_kinds_and_errors(self) -> None:
        markdown = _markdown(_results())

        assert (
            " Pending | 2 | Awaiting a model judgment (1) or an operator confirmation of a PASS candidate (1); "
            "not compliant until resolved |"
        ) in markdown
        assert (
            " Not Compliant (1 failed, 1 could not be measured, 1 awaiting a model judgment, "
            "1 PASS candidate(s) awaiting confirmation)"
        ) in markdown


@pytest.mark.unit
def test_cli_text_tags_pending_kinds() -> None:
    rendered = format_results_text(_results(), "openssf-baseline")

    assert "OSPS-GV-01.01: PENDING (awaiting a model judgment)" in rendered
    assert "OSPS-DO-01.01: PENDING (PASS candidate, not compliant until confirmed)" in rendered
    assert "OSPS-AC-03.01: ERROR [auth]" in rendered
    assert all(ord(ch) < 128 for line in rendered.splitlines() if "PENDING (" in line for ch in line)


@pytest.mark.unit
def test_harness_markdown_renders_the_same_details() -> None:
    results = _results()
    report = HarnessReport(
        target={"local_path": "/r"},
        summary=HarnessSummary(total=5, **{"pass": 1, "fail": 1, "warn": 2, "n_a": 0, "error": 1}),
        controls=results,
        pending_feedback=[],
        answer_sources_used=[],
        llm_calls={"total": 0, "provider": "none"},
    )

    markdown = report.to_markdown()

    assert "- OSPS-DO-01.01 PENDING (suggestive) -- PASS candidate" in markdown
    assert "*PASS candidate, not compliant until confirmed*" in markdown
    assert "*Awaiting a model judgment*" in markdown
    assert "*Could not measure* (`auth`)" in markdown
    assert "- OSPS-DO-02.01 PASS (asserted)\n  - *Asserted*: PASS candidate confirmed by @operator" in markdown
    non_ascii = [ch for ch in markdown if ord(ch) > 127]
    assert not non_ascii
