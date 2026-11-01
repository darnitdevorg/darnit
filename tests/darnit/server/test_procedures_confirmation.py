"""The confirmation procedure get_pass_candidates returns (#681; framework-design 5.4, 15.9)."""

from __future__ import annotations

import json

import pytest

from darnit.server.procedures import confirmation_procedure


def _text(owner: str | None = "acme", repo: str | None = "widget", host: str = "github.com") -> str:
    return "\n".join(confirmation_procedure(owner, repo, host, "/work/widget"))


@pytest.mark.unit
class TestConfirmationProcedure:
    def test_calls_name_the_repository_the_caller_named(self) -> None:
        text = _text()

        assert "confirm_pass_candidate(control_ids=[" in text
        assert 'owner="acme", repo="widget", local_path="/work/widget"' in text
        assert 'get_pass_candidates(owner="acme", repo="widget", local_path="/work/widget"' in text

    def test_an_unnamed_repository_is_a_placeholder(self) -> None:
        text = _text(None, None)

        assert "owner=<owner of the audited repository>" in text
        assert "repo=<name of the audited repository>" in text

    def test_a_non_default_host_is_named(self) -> None:
        assert 'host="git.example.org"' in _text(host="git.example.org")
        assert "host=" not in _text()

    def test_every_candidate_is_shown_before_asking(self) -> None:
        steps = confirmation_procedure("acme", "widget", "github.com", "/w")
        show = next(i for i, s in enumerate(steps) if "verbatim" in s)
        ask = next(i for i, s in enumerate(steps) if "ask_user_batch" in s)

        assert show < ask
        assert "before asking" in steps[show]
        assert "not compliant until you confirm it" in steps[show]

    def test_a_document_remediation_wrote_is_disclosed(self) -> None:
        text = _text()

        assert "remediation" in text
        assert "edited" in text
        assert "your own" in text
        assert "actual practice" in text

    def test_only_named_candidates_are_confirmed(self) -> None:
        text = _text()

        assert 'answered "Confirm"' in text
        for refusal in ("silence", '"Skip for now"', '"Do not confirm"', "names no candidate"):
            assert refusal in text
        assert "confirm all" in text
        assert "Do not pre-fill, recommend" in text

    def test_confirmations_are_said_to_be_local(self) -> None:
        text = _text()

        assert "on this machine" in text
        assert "CI" in text

    def test_holds_no_candidate_value(self) -> None:
        text = _text()

        assert "<" in text
        for value in ("sha256:", "PASS candidate for OSPS", "cited_evidence=["):
            assert value not in text

    def test_procedure_is_short_ascii_steps(self) -> None:
        text = json.dumps(confirmation_procedure("a", "b", "github.com", "/w"))

        assert len(text) < 3_000
        assert text.isascii()
