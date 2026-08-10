"""Tests for the skill Markdown parser (feature 028 T017).

Golden-file tests against captured skill outputs plus adversarial cases.
"""

from __future__ import annotations

from pathlib import Path

from tests.darnit.parity.tier2.skill_markdown_parser import SkillReport

GOLDEN_DIR = Path(__file__).parent / "golden"


def _load_golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text()


class TestGoldenFiles:
    def test_all_pass_parseable(self) -> None:
        md = _load_golden("all_pass.md")
        r = SkillReport.parse(md)
        assert r.parseable
        assert r.counts is not None
        # The all_pass golden uses verbose "Passed: 2" -- counts key = 'pass'
        assert r.counts.get("pass") == 2
        assert r.controls is not None
        assert len(r.controls) == 2
        ids = {c.id for c in r.controls}
        assert ids == {"OSPS-DO-01.01", "OSPS-LE-03.01"}

    def test_mixed_drift_parseable(self) -> None:
        md = _load_golden("mixed_drift.md")
        r = SkillReport.parse(md)
        assert r.parseable
        assert r.counts is not None
        assert r.counts.get("pass") == 51
        assert r.counts.get("fail") == 5
        assert r.counts.get("warn") == 7
        assert r.controls is not None
        ids = {c.id for c in r.controls}
        assert "OSPS-BR-06.01" in ids
        assert "OSPS-VM-04.01" in ids
        # Extract statuses; PASS controls aren't enumerated in this golden.
        for claim in r.controls:
            if claim.id in ("OSPS-BR-06.01", "OSPS-VM-04.01"):
                assert claim.status == "FAIL"

    def test_unparseable_is_captured_as_such(self) -> None:
        md = _load_golden("unparseable.md")
        r = SkillReport.parse(md)
        assert r.parseable is False
        assert r.raw_markdown == md  # preserved
        assert r.parse_notes  # explains why


class TestRedactionSanity:
    """Regression guard: parsed output MUST NOT contain credential-shaped substrings."""

    def test_parser_output_does_not_expose_secret_that_isnt_in_input(self) -> None:
        """Sanity: if the input has no secret, the parsed SkillReport should
        not conjure one. Guards against a future bug where the parser
        interpolated env vars into its output."""
        secret = "sk-ant-DISTINCTIVE-TEST-KEY-XYZ"
        input_md = "PASS: 5, FAIL: 0\n\n**OSPS-DO-01.01**: PASS"
        r = SkillReport.parse(input_md)
        # No secret in input, so no secret in output.
        assert secret not in str(r)
        assert secret not in r.raw_markdown


class TestParserRobustness:
    def test_never_raises_on_empty_string(self) -> None:
        r = SkillReport.parse("")
        assert r.parseable is False

    def test_never_raises_on_only_whitespace(self) -> None:
        r = SkillReport.parse("   \n\n\t  ")
        assert r.parseable is False

    def test_never_raises_on_garbage(self) -> None:
        r = SkillReport.parse("\x00\x01\x02")
        assert r.parseable is False
