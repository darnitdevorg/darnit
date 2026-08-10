"""Adversarial diff tests (feature 028 T025).

Cover SC-004, FR-006a, FR-008, FR-010.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.darnit.parity.tier1.comparator import AuditResult, Control
from tests.darnit.parity.tier2.diff import diff
from tests.darnit.parity.tier2.skill_markdown_parser import (
    SkillControlClaim,
    SkillReport,
)


def _mcp(*controls: Control) -> AuditResult:
    return AuditResult(controls=tuple(controls), source="mcp_tool")


def _parseable_skill(
    *claims: SkillControlClaim,
    counts: dict[str, int] | None = None,
) -> SkillReport:
    return SkillReport(
        parseable=True,
        raw_markdown="stub",
        counts=counts or {"pass": 0, "fail": 0, "warn": 0},
        controls=tuple(claims),
    )


class TestSC004SkillReclassificationCaught:
    def test_warn_control_reclassified_as_pass_is_caught(self) -> None:
        """SC-004: skill says PASS, tool says WARN -> per_control_disagree."""
        mcp = _mcp(Control(id="X", status="WARN", authority="suggestive"))
        skill = _parseable_skill(SkillControlClaim(id="X", status="PASS"))
        report = diff(mcp, skill, "sc004")

        assert report.outcome == "per_control_disagree"
        assert "X" in report.disagreeing_controls

    def test_suggestive_authority_no_license_to_reinterpret(self) -> None:
        """FR-008: even for suggestive-authority controls, the skill has
        NO license to reinterpret the tool's verdict."""
        mcp = _mcp(Control(id="X", status="WARN", authority="suggestive"))
        skill = _parseable_skill(SkillControlClaim(id="X", status="PASS"))
        report = diff(mcp, skill, "auth")
        assert report.outcome == "per_control_disagree"

    def test_dispositive_authority_also_caught(self) -> None:
        mcp = _mcp(Control(id="Y", status="FAIL", authority="dispositive"))
        skill = _parseable_skill(SkillControlClaim(id="Y", status="PASS"))
        report = diff(mcp, skill, "auth-disp")
        assert report.outcome == "per_control_disagree"


class TestFR006AUnparseableSkillOutput:
    def test_unparseable_report_produces_distinct_outcome(self) -> None:
        """FR-006a: unparseable skill output is a DISTINCT failure class,
        NOT lumped in with 'skill and tool disagree'."""
        mcp = _mcp(Control(id="X", status="PASS"))
        skill = SkillReport(
            parseable=False,
            raw_markdown="Sorry, I couldn't complete the audit.",
            counts=None,
            controls=None,
            parse_notes=("could not extract summary counts",),
        )
        report = diff(mcp, skill, "unparse")
        assert report.outcome == "skill_unparseable"
        assert "distinct" in report.diff_markdown.lower() or "unparseable" in report.diff_markdown.lower()


class TestCountsOnlyDisagreement:
    def test_summary_counts_differ_but_per_control_agrees(self) -> None:
        """Counts-only disagreement is its own outcome (weakest signal)."""
        mcp = _mcp(
            Control(id="A", status="PASS"),
            Control(id="B", status="PASS"),
        )
        skill = _parseable_skill(
            SkillControlClaim(id="A", status="PASS"),
            SkillControlClaim(id="B", status="PASS"),
            counts={"pass": 99, "fail": 0, "warn": 0},  # tool has 2; skill claims 99
        )
        report = diff(mcp, skill, "counts")
        assert report.outcome == "counts_disagree"


class TestSuccess:
    def test_full_agreement_is_success(self) -> None:
        mcp = _mcp(
            Control(id="A", status="PASS"),
            Control(id="B", status="FAIL"),
        )
        skill = _parseable_skill(
            SkillControlClaim(id="A", status="PASS"),
            SkillControlClaim(id="B", status="FAIL"),
            counts={"pass": 1, "fail": 1, "warn": 0},
        )
        report = diff(mcp, skill, "green")
        assert report.outcome == "success"


# ---------------------------------------------------------------------------
# FR-010 (MC1): missing API key fail-fast
# ---------------------------------------------------------------------------


class TestFR010MissingApiKey:
    def test_invoke_skill_raises_setup_error_without_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FR-010: invoke_skill MUST raise SetupError when the key is absent."""
        import asyncio

        from tests.darnit.parity.tier2.claude_agent_sdk_client import (
            SetupError,
            invoke_skill,
        )

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(SetupError, match="ANTHROPIC_API_KEY"):
            asyncio.new_event_loop().run_until_complete(
                invoke_skill(fixture_dir=Path.cwd()),
            )

    def test_run_py_exits_3_without_api_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FR-010: run.py subprocess exit code is 3 (SETUP) when key absent.

        The runner also fails setup=3 when no fixtures match, but this test
        forces a real skill invocation by NOT using --dry-run and pointing at
        the actual corpus so the SDK path is exercised.
        """
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        env["PYTHONPATH"] = str(Path.cwd())

        rc = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.darnit.parity.tier2.run",
                "--fixture-glob",
                "all_pass_repo",
                "--artifact-dir",
                str(tmp_path / "artifacts"),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        # 3 = SETUP; the runner should NOT proceed past the credential check.
        assert rc.returncode == 3, f"expected exit 3, got {rc.returncode}\nstderr: {rc.stderr}"
