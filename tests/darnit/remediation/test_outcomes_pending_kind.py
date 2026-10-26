"""What a changed control awaits: ``pending_kind`` and ``awaiting`` (#681; framework-design 15.4, 15.5)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from darnit.remediation.plan import (
    OUTCOME_KINDS,
    ErrorInfo,
    FileChange,
    RemediationOutcome,
    RemediationRun,
    summarize,
)

PASS = {"status": "PASS"}
FAIL = {"status": "FAIL"}
WARN = {"status": "WARN"}
ERROR = {"status": "ERROR", "error": {"class": "evaluation", "cause": "x"}}
JUDGMENT = {"status": "PENDING", "pending": {"kind": "llm_judgment"}}
CONFIRMATION = {"status": "PENDING", "pending": {"kind": "confirmation"}}
NO_KIND = {"status": "PENDING"}
CHANGED = ("fixed", "changed_not_passing", "changed_not_verified")


def _outcome(kind: str, recheck: dict | None = None, pending_kind: str | None = None, control_id: str = "C-1"):
    fields: dict[str, Any] = {"control_id": control_id, "kind": kind, "recheck": recheck, "pending_kind": pending_kind}
    if kind in CHANGED:
        fields["file_changes"] = [FileChange(path="DOC.md", action="create", content="# Doc\n")]
    if kind == "error" or (kind == "changed_not_verified" and recheck is None):
        fields["error"] = ErrorInfo(error_class="crashed", cause="x")
    return RemediationOutcome(**fields)


ACCEPTED = [
    ("fixed", PASS, None),
    ("changed_not_passing", FAIL, None),
    ("changed_not_passing", WARN, None),
    ("changed_not_passing", JUDGMENT, "llm_judgment"),
    ("changed_not_passing", CONFIRMATION, "confirmation"),
    ("changed_not_verified", ERROR, None),
    ("changed_not_verified", None, None),
    ("unchanged", None, None),
    ("needs_approval", None, None),
    ("needs_confirmation", None, None),
    ("manual", None, None),
    ("error", None, None),
]

REJECTED = [
    ("changed_not_passing", JUDGMENT, None),
    ("changed_not_passing", CONFIRMATION, None),
    ("changed_not_passing", JUDGMENT, "confirmation"),
    ("changed_not_passing", CONFIRMATION, "llm_judgment"),
    ("changed_not_passing", NO_KIND, None),
    ("changed_not_passing", NO_KIND, "llm_judgment"),
    ("changed_not_passing", FAIL, "llm_judgment"),
    ("changed_not_passing", WARN, "confirmation"),
    ("fixed", PASS, "llm_judgment"),
    ("changed_not_verified", ERROR, "llm_judgment"),
    ("changed_not_verified", None, "confirmation"),
    ("unchanged", None, "llm_judgment"),
    ("needs_approval", None, "llm_judgment"),
    ("needs_confirmation", None, "confirmation"),
    ("manual", None, "llm_judgment"),
    ("error", None, "confirmation"),
]


def _run(**overrides: Any) -> RemediationRun:
    data: dict[str, Any] = {
        "run_id": "01JABCDEFGHJKMNPQRSTVWXYZ0",
        "repository": "github.com/o/r",
        "mode": "apply",
        "policy": {"platform": "prompt", "high_impact": "prompt"},
        "operator_config_digest": None,
    }
    data.update(overrides)
    return RemediationRun.model_validate(data)


@pytest.mark.unit
class TestPendingKind:
    def test_the_cases_cover_every_outcome_kind(self) -> None:
        assert {kind for kind, _, _ in ACCEPTED} == set(OUTCOME_KINDS)
        assert {kind for kind, _, _ in REJECTED} == set(OUTCOME_KINDS)

    @pytest.mark.parametrize(("kind", "recheck", "pending_kind"), ACCEPTED)
    def test_accepted(self, kind: str, recheck: dict | None, pending_kind: str | None) -> None:
        assert _outcome(kind, recheck, pending_kind).pending_kind == pending_kind

    @pytest.mark.parametrize(("kind", "recheck", "pending_kind"), REJECTED)
    def test_rejected(self, kind: str, recheck: dict | None, pending_kind: str | None) -> None:
        with pytest.raises(ValidationError):
            _outcome(kind, recheck, pending_kind)

    def test_an_unknown_pending_kind_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _outcome("changed_not_passing", {"status": "PENDING", "pending": {"kind": "other"}}, "other")

    def test_awaiting_is_still_changed_and_not_fixed(self) -> None:
        outcome = _outcome("changed_not_passing", JUDGMENT, "llm_judgment")

        assert outcome.changed
        assert outcome.kind != "fixed"

    def test_summary_counts_are_unchanged(self) -> None:
        outcomes = [
            _outcome("changed_not_passing", JUDGMENT, "llm_judgment", "A"),
            _outcome("changed_not_passing", FAIL, None, "B"),
            _outcome("fixed", PASS, None, "C"),
        ]

        counts = summarize(outcomes)

        assert counts["changed_not_passing"] == 2
        assert counts["fixed"] == 1
        assert set(counts) == set(OUTCOME_KINDS)

    def test_fixed_still_needs_a_passing_recheck(self) -> None:
        for recheck in (JUDGMENT, CONFIRMATION):
            with pytest.raises(ValidationError):
                _outcome("fixed", recheck, None)


@pytest.mark.unit
class TestAwaiting:
    def test_derived_from_outcomes_sorted_with_empty_keys_omitted(self) -> None:
        run = _run(
            outcomes=[
                _outcome("changed_not_passing", JUDGMENT, "llm_judgment", "B"),
                _outcome("changed_not_passing", JUDGMENT, "llm_judgment", "A"),
                _outcome("changed_not_passing", WARN, None, "C"),
                _outcome("fixed", PASS, None, "D"),
            ]
        )

        assert run.awaiting == {"llm_judgment": ["A", "B"]}

    def test_both_kinds(self) -> None:
        run = _run(
            outcomes=[
                _outcome("changed_not_passing", CONFIRMATION, "confirmation", "X"),
                _outcome("changed_not_passing", JUDGMENT, "llm_judgment", "Y"),
            ]
        )

        assert run.awaiting == {"confirmation": ["X"], "llm_judgment": ["Y"]}

    def test_a_supplied_value_must_match(self) -> None:
        outcomes = [_outcome("changed_not_passing", JUDGMENT, "llm_judgment", "A")]

        assert _run(outcomes=outcomes, awaiting={"llm_judgment": ["A"]}).awaiting == {"llm_judgment": ["A"]}
        with pytest.raises(ValidationError):
            _run(outcomes=outcomes, awaiting={"confirmation": ["A"]})

    def test_a_preview_awaits_nothing(self) -> None:
        assert _run(mode="preview").awaiting == {}

    def test_json_round_trip_keeps_pending_kind_and_awaiting(self) -> None:
        run = _run(outcomes=[_outcome("changed_not_passing", CONFIRMATION, "confirmation", "A")])

        data = run.model_dump(mode="json")
        again = RemediationRun.model_validate(data)

        assert data["awaiting"] == {"confirmation": ["A"]}
        assert data["outcomes"][0]["pending_kind"] == "confirmation"
        assert again == run
