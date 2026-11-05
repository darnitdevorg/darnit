"""The procedures data and judgment tools return to a coding agent (framework-design 5.4, 7.10)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from darnit.server.procedures import data_collection_procedure, data_next_step, judgment_procedure

SKILLS = Path(__file__).resolve().parents[3] / "packages" / "darnit" / "src" / "darnit" / "skills"


@pytest.mark.unit
class TestProcedures:
    def test_data_calls_name_the_repository_the_caller_named(self) -> None:
        text = "\n".join(data_collection_procedure("acme", "widget", "/work/widget"))

        assert (
            'confirm_project_data(owner="acme", repo="widget", host=<git host of the audited repository; omit for github.com>, local_path="/work/widget"'
            in text
        )
        assert 'get_pending_data(owner="acme", repo="widget", local_path="/work/widget")' in text

    def test_an_unnamed_repository_is_a_placeholder(self) -> None:
        text = "\n".join(data_collection_procedure(None, None, "/work/widget"))

        assert "owner=<owner of the audited repository>" in text
        assert "repo=<name of the audited repository>" in text

    def test_get_pending_data_calls_carry_no_host(self) -> None:
        assert "host=" not in data_next_step("acme", "widget", "/w")
        steps = data_collection_procedure("acme", "widget", "/w")
        pending_calls = re.findall(r"get_pending_data\([^)]*\)", "\n".join(steps))
        assert pending_calls
        assert all("host=" not in call for call in pending_calls)

    def test_confirm_call_names_the_host_as_a_placeholder(self) -> None:
        """get_pending_data takes no host, so step 4 names it as a placeholder, never a detected value (7.10)."""
        step4 = data_collection_procedure("acme", "widget", "/w")[3]

        assert "confirm_project_data(" in step4
        assert "host=<git host of the audited repository; omit for github.com>" in step4

    def test_answers_follow_answer_mapping(self) -> None:
        """A No on a candidate is the typed value, never false; Yes/No maps to booleans only on yes/no questions."""
        step4 = data_collection_procedure("acme", "widget", "/w")[3]

        assert "answer_mapping" in step4
        assert "Yes/No on a yes/no question is true/false" in step4
        assert "No on a candidate, or Other, is the value the person typed" in step4

    def test_a_scoped_collection_stays_scoped(self) -> None:
        steps = data_collection_procedure("acme", "widget", "/w", ["OSPS-GV-01.01"])

        assert (
            'get_pending_data(owner="acme", repo="widget", local_path="/w", control_ids=["OSPS-GV-01.01"])' in steps[4]
        )
        assert "same control_ids" in data_next_step("acme", "widget", "/w")

    def test_judgment_calls_carry_a_non_default_host(self) -> None:
        text = "\n".join(judgment_procedure("acme", "widget", "git.example.org", "/w"))

        assert 'host="git.example.org"' in text
        assert "host=" not in "\n".join(judgment_procedure("acme", "widget", "github.com", "/w"))

    def test_procedures_are_short_ascii_steps(self) -> None:
        for steps in (data_collection_procedure("a", "b", "/w"), judgment_procedure("a", "b", "github.com", "/w")):
            text = json.dumps(steps, ensure_ascii=False)
            assert len(text) < 2_000
            assert text.isascii()


@pytest.mark.unit
def test_no_skill_tells_the_agent_to_follow_another_skill() -> None:
    """A skill defers to the procedure in a tool result, never to another skill's text (which a client may not load)."""
    pattern = re.compile(r"follow\s+(the\s+)?`?/?darnit[:\w-]*`?\s+skill", re.IGNORECASE)
    offenders = [
        f"{path.parent.name}: {match.group(0)}"
        for path in sorted(SKILLS.glob("*/SKILL.md"))
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
