"""Report format tests (feature 026 T030-T033).

Contract report-format.md RF-1..RF-8.
"""

from __future__ import annotations

import json

import pytest

from darnit.harness.report import (
    HarnessReport,
    HarnessSummary,
    PendingFeedbackEntry,
)


@pytest.fixture
def sample_report() -> HarnessReport:
    return HarnessReport(
        target={"local_path": "/tmp/repo", "owner": "acme", "repo": "widget"},
        summary=HarnessSummary(total=3, **{"pass": 1, "fail": 1, "warn": 1, "n_a": 0, "error": 0}),
        controls=[
            {
                "id": "OSPS-AC-01.01",
                "status": "PASS",
                "authority": "dispositive",
                "level": 1,
                "details": "gh api reports MFA",
                "evidence": {},
            },
            {
                "id": "OSPS-BR-06.01",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 2,
                "details": "no signed releases found",
                "evidence": {},
            },
            {
                "id": "STAGE1-REF-SECURITY-01",
                "status": "WARN",
                "authority": "suggestive",
                "level": 1,
                "details": "LLM proposal captured; no dispositive PASS",
                "evidence": {"llm_extract_prompt": "..."},
            },
        ],
        pending_feedback=[
            PendingFeedbackEntry(
                control_id="STAGE1-REF-SECURITY-01",
                context_key="security_contact",
                question="Who is the security contact?",
            ),
        ],
        answer_sources_used=["project_yaml", "--answers /tmp/answers.yaml"],
        llm_calls={"total": 1, "provider": "anthropic:claude-sonnet-5"},
        exit_class=1,
    )


class TestJsonReport:
    def test_json_report_shape(self, sample_report: HarnessReport) -> None:
        """RF-1 + RF-3: valid JSON with `pass` (not `pass_`) key, per-control authority."""
        js = sample_report.to_json()
        data = json.loads(js)

        assert "harness_version" in data
        assert data["harness_version"] == "1.0"
        assert data["summary"]["pass"] == 1
        assert data["summary"]["fail"] == 1
        # RF-3: `pass_` alias should NOT appear
        assert "pass_" not in data["summary"]

        # Every control has authority (RF-1)
        for control in data["controls"]:
            assert "authority" in control
            assert control["authority"] in {"dispositive", "suggestive", "asserted"}

    def test_json_hides_api_key(
        self,
        sample_report: HarnessReport,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RF-4: API key MUST NOT appear anywhere in the JSON output."""
        secret = "SECRET_TOKEN_XYZ_123"
        monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
        js = sample_report.to_json()
        assert secret not in js

    def test_json_exit_class_not_in_body(self, sample_report: HarnessReport) -> None:
        """RF-8: exit_class is NOT in the JSON body (lives in exit code + stderr)."""
        js = sample_report.to_json()
        data = json.loads(js)
        assert "exit_class" not in data

    def test_json_answer_sources_lists_all(self, sample_report: HarnessReport) -> None:
        """RF-5: every consulted source appears in resolver order."""
        js = sample_report.to_json()
        data = json.loads(js)
        assert data["answer_sources_used"] == ["project_yaml", "--answers /tmp/answers.yaml"]


class TestMarkdownReport:
    def test_markdown_has_section_headings_in_order(self, sample_report: HarnessReport) -> None:
        """RF-1 section ordering per contract report-format.md."""
        md = sample_report.to_markdown()
        expected_order = [
            "# Darnit Harness Report",
            "## Summary",
            "## Failed Controls",
            "## Warned or Pending Controls",
            "## Passed Controls",
            "## Answer Sources",
            "## LLM Calls",
        ]
        positions = [md.find(h) for h in expected_order]
        assert all(p >= 0 for p in positions), (
            f"Missing heading in Markdown output. Found positions: {list(zip(expected_order, positions))}"
        )
        # Positions must be strictly increasing.
        for a, b in zip(positions, positions[1:]):
            assert a < b, (
                f"Section order violated: {expected_order[positions.index(a)]!r} before {expected_order[positions.index(b)]!r}"
            )

    def test_markdown_control_lines_include_authority(self, sample_report: HarnessReport) -> None:
        """RF-1: every control mention includes authority in parentheses."""
        md = sample_report.to_markdown()
        assert "OSPS-AC-01.01 PASS (dispositive)" in md
        assert "OSPS-BR-06.01 FAIL (dispositive)" in md
        assert "STAGE1-REF-SECURITY-01 WARN (suggestive)" in md

    def test_markdown_empty_section_renders_none(self) -> None:
        """RF-7: empty section renders as heading + 'None.'"""
        report = HarnessReport(
            target={"local_path": "/tmp"},
            summary=HarnessSummary(
                total=0,
                **{"pass": 0, "fail": 0, "warn": 0, "n_a": 0, "error": 0},
            ),
            controls=[],
            pending_feedback=[],
            answer_sources_used=[],
            llm_calls={"total": 0, "provider": "anthropic:claude-sonnet-5"},
            exit_class=0,
        )
        md = report.to_markdown()
        # All three control sections empty -> all should say "None."
        assert "## Failed Controls" in md
        assert "## Warned or Pending Controls" in md
        assert "## Passed Controls" in md
        # Count "None." occurrences: 3 (Failed, Warned, Passed) + 1 (Answer Sources) = 4
        assert md.count("None.") == 4

    def test_markdown_hides_api_key(
        self,
        sample_report: HarnessReport,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RF-4: API key MUST NOT appear in Markdown output either."""
        secret = "SECRET_TOKEN_XYZ_MARKDOWN"
        monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
        md = sample_report.to_markdown()
        assert secret not in md
