"""The next steps an apply result names for controls awaiting a judgment or confirmation (#681; 15.4, 15.9)."""

from __future__ import annotations

import json

import pytest

from darnit.server.procedures import remediation_next_steps

RUN = "01JABCDEFGHJKMNPQRSTVWXYZ0"


def _text(awaiting: dict[str, list[str]], host: str = "github.com") -> str:
    return "\n".join(remediation_next_steps("acme", "widget", host, "/work/widget", awaiting, RUN))


@pytest.mark.unit
class TestRemediationNextSteps:
    def test_nothing_awaits(self) -> None:
        assert remediation_next_steps("acme", "widget", "github.com", "/w", {}, RUN) == []

    def test_awaiting_a_judgment_names_both_tools(self) -> None:
        text = _text({"llm_judgment": ["OSPS-DO-03.01", "OSPS-GV-01.01"]})

        assert 'get_judgment_requests(owner="acme", repo="widget", local_path="/work/widget")' in text
        assert f'get_pass_candidates(owner="acme", repo="widget", local_path="/work/widget", run_id="{RUN}")' in text
        assert "OSPS-DO-03.01, OSPS-GV-01.01" in text
        assert text.index("get_judgment_requests") < text.index("get_pass_candidates")

    def test_awaiting_only_a_confirmation_names_only_the_candidates_tool(self) -> None:
        text = _text({"confirmation": ["OSPS-SA-03.02"]})

        assert "get_judgment_requests" not in text
        assert "get_pass_candidates(" in text
        assert "OSPS-SA-03.02" in text

    def test_a_non_default_host_is_named(self) -> None:
        assert 'host="git.example.org"' in _text({"confirmation": ["X"]}, host="git.example.org")

    def test_ids_only_ascii_and_short(self) -> None:
        steps = remediation_next_steps(
            "a", "b", "github.com", "/w", {"llm_judgment": ["A"], "confirmation": ["B"]}, RUN
        )
        text = json.dumps(steps)

        assert text.isascii()
        assert len(text) < 1_500
        assert "sha256:" not in text
