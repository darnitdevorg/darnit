"""get_pending_data shows candidates as data, never as ready-to-run answers (feature 042, US3).

FR-013: no command template or answer mapping contains a candidate value.
FR-014: configuration examples are format hints, never answers.
FR-015: every allowed value of a choice key is reachable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from darnit.config.context_keys import value_digest
from darnit.config.context_schema import (
    ContextDefinition,
    ContextPromptRequest,
    Origin,
    OriginKind,
    ResolvedValue,
    Standing,
)
from darnit_baseline.tools import _build_context_question, _context_key_order, get_pending_data

MAINTAINERS = ["@alice", "@bob"]
CONTACT = "security@realcorp.io"


def _definitions() -> dict[str, ContextDefinition]:
    from darnit.config.context_storage import framework_definitions
    from darnit.config.merger import load_framework_by_name

    return framework_definitions(load_framework_by_name("openssf-baseline"))


def _request(key: str, candidate: ResolvedValue | None = None) -> ContextPromptRequest:
    definition = _definitions()[key]
    return ContextPromptRequest(
        key=key,
        definition=definition,
        control_ids=definition.affects,
        candidate=candidate or ResolvedValue(key=key, standing=Standing.UNKNOWN),
        priority=len(definition.affects),
    )


def _candidate(key: str, value: object, method: str = "MAINTAINERS.md") -> ResolvedValue:
    return ResolvedValue(
        key=key,
        standing=Standing.CANDIDATE,
        value=value,
        origin=Origin(kind=OriginKind.SIEVE_HINT, method=method, confidence=0.95),
    )


def _payload(pending: list[ContextPromptRequest]) -> dict:
    with patch("darnit.config.context_storage.get_pending_context", return_value=pending):
        result = get_pending_data(local_path="/tmp/repo", owner="example-org", repo="repo", limit=0)
    return _parse(result)


def _parse(result: str) -> dict:
    """The JSON after the agent directive, if any."""
    return json.loads(result.split("\n---\n", 1)[-1])


def _without_candidates(payload: dict) -> str:
    """The payload as text with every question's ``candidate`` removed."""
    stripped = dict(payload)
    stripped["questions"] = [{k: v for k, v in q.items() if k != "candidate"} for q in payload["questions"]]
    return json.dumps(stripped)


@pytest.mark.unit
class TestCandidateAsData:
    def test_candidate_carries_value_origin_digest_and_label(self) -> None:
        question = _build_context_question(_request("maintainers", _candidate("maintainers", MAINTAINERS)))

        assert question["input_type"] == "confirm"
        assert question["candidate"] == {
            "value": MAINTAINERS,
            "origin": {"kind": "sieve_hint", "method": "MAINTAINERS.md", "confidence": 0.95},
            "digest": value_digest("maintainers", MAINTAINERS),
            "label": "UNCONFIRMED candidate - show it to the person; do not confirm without their answer",
        }

    def test_question_without_candidate_has_none(self) -> None:
        question = _build_context_question(_request("governance_model"))

        assert question["candidate"] is None

    def test_candidate_value_appears_only_in_the_candidate(self) -> None:
        payload = _payload(
            [
                _request("maintainers", _candidate("maintainers", MAINTAINERS)),
                _request("security_contact", _candidate("security_contact", CONTACT, "SECURITY.md")),
            ]
        )

        text = _without_candidates(payload)
        for value in [*MAINTAINERS, CONTACT]:
            assert value not in text

    def test_command_template_is_placeholder_only(self) -> None:
        question = _build_context_question(_request("maintainers", _candidate("maintainers", MAINTAINERS)))

        assert question["command_template"] == (
            'confirm_project_data(accept_candidates={"maintainers": "<candidate digest if the person accepts it>"}, '
            "owner=..., repo=...)  OR  confirm_project_data(maintainers=<the person's answer>, owner=..., repo=...)"
        )
        assert question["candidate"]["digest"] not in question["command_template"]

    def test_enum_candidate_is_not_in_template_or_mapping(self) -> None:
        payload = _payload([_request("ci_provider", _candidate("ci_provider", "gitlab", ".gitlab-ci.yml"))])

        [question] = payload["questions"]
        assert "gitlab" not in question["command_template"]
        assert "gitlab" not in json.dumps(payload.get("answer_mapping", []))


@pytest.mark.unit
class TestAcceptByDigest:
    def test_yes_maps_to_a_digest_placeholder(self) -> None:
        payload = _payload([_request("maintainers", _candidate("maintainers", MAINTAINERS))])

        [mapping] = payload["answer_mapping"]
        assert mapping["value_map"]["Yes"] == {"accept_candidates": {"maintainers": "<candidate.digest>"}}

    def test_mapping_never_carries_a_ready_digest(self) -> None:
        payload = _payload([_request("maintainers", _candidate("maintainers", MAINTAINERS))])

        digest = payload["questions"][0]["candidate"]["digest"]
        assert digest not in json.dumps(payload["answer_mapping"])
        assert digest not in json.dumps(payload["ask_user_batch"])

    def test_questions_with_candidates_are_returned_with_the_batch(self) -> None:
        """The agent fills the placeholder from the question's candidate, so the question is in the response."""
        payload = _payload([_request("maintainers", _candidate("maintainers", MAINTAINERS))])

        assert payload["ask_user_batch"]
        assert payload["questions"][0]["candidate"]["digest"] == value_digest("maintainers", MAINTAINERS)


@pytest.mark.unit
class TestEveryAllowedValueReachable:
    @pytest.mark.parametrize("key", ["governance_model", "ci_provider", "platform"])
    def test_allowed_values_lists_the_whole_vocabulary(self, key: str) -> None:
        question = _build_context_question(_request(key))

        assert question["allowed_values"] == _definitions()[key].values

    @pytest.mark.parametrize("key", ["governance_model", "ci_provider"])
    def test_selector_omitted_when_more_than_four_values(self, key: str) -> None:
        question = _build_context_question(_request(key))

        assert "ask_user" not in question
        for value in _definitions()[key].values:
            assert value in question["prompt"]

    def test_selector_lists_every_value_when_four_or_fewer(self) -> None:
        question = _build_context_question(_request("platform"))

        labels = [option["label"] for option in question["ask_user"]["options"]]
        assert labels == _definitions()["platform"].values

    def test_questions_without_selector_are_still_returned(self) -> None:
        payload = _payload([_request("governance_model"), _request("has_releases")])

        assert [q["key"] for q in payload["questions"]] == ["governance_model", "has_releases"]
        assert [m["context_key"] for m in payload["answer_mapping"]] == ["has_releases"]

    def test_non_enum_has_no_allowed_values(self) -> None:
        assert _build_context_question(_request("maintainers"))["allowed_values"] is None


@pytest.mark.unit
class TestExamplesAreHintsOnly:
    @pytest.mark.parametrize("key", ["maintainers", "security_contact"])
    def test_examples_are_a_format_hint_and_not_options(self, key: str) -> None:
        examples = _definitions()[key].examples
        question = _build_context_question(_request(key))

        assert question["format_hint"] == " or ".join(examples)
        assert "ask_user" not in question
        for example in examples:
            assert example not in question["command_template"]

    def test_examples_are_not_offered_in_the_payload(self) -> None:
        pending = [_request(key) for key in ("maintainers", "security_contact", "governance_model", "ci_provider")]
        payload = _payload(pending)

        offered = json.dumps({k: v for k, v in payload.items() if k != "questions"})
        templates = json.dumps([q["command_template"] for q in payload["questions"]])
        for request in pending:
            for example in request.definition.examples:
                assert f'"{example}"' not in offered
                assert example not in templates


@pytest.mark.unit
class TestOrder:
    def test_order_is_every_framework_key_in_definition_order(self) -> None:
        assert _context_key_order() == list(_definitions())
        assert "platform" in _context_key_order()


@pytest.fixture
def offline_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "offline-bin"
    bin_dir.mkdir()
    (bin_dir / "gh").symlink_to(shutil.which("false"))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.mark.integration
def test_detected_maintainer_appears_only_in_the_candidate(tmp_path: Path, offline_gh: None) -> None:
    repo = tmp_path / "r-maint"
    repo.mkdir()
    (repo / "MAINTAINERS.md").write_text("# Maintainers\n\n- Alice Example <alice@realcorp.io> @alice\n")
    (repo / "SECURITY.md").write_text("# Security\n\nReport vulnerabilities to security@realcorp.io.\n")
    git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=repo, check=True)

    result = get_pending_data(local_path=str(repo), owner="example-org", repo="r-maint", limit=0)
    payload = _parse(result)

    by_key = {q["key"]: q for q in payload["questions"]}
    assert "@alice" in by_key["maintainers"]["candidate"]["value"]
    assert "@alice" not in _without_candidates(payload)
    assert "@alice" not in result.split("\n---\n", 1)[0]
