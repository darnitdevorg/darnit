"""Remediation plan models and the digest helper (feature 043, data-model.md, T005)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from darnit.remediation.plan import (
    OUTCOME_KINDS,
    Approval,
    FileChange,
    PlanItem,
    RemediationOutcome,
    RemediationRun,
    content_digest,
    digest,
)


def _create(path: str = "SECURITY.md", content: str = "# Security\n") -> FileChange:
    return FileChange(path=path, action="create", content=content)


@pytest.mark.unit
class TestDigest:
    def test_is_sha256_of_canonical_json(self) -> None:
        value = {"b": [1, {"y": 2, "x": 1}], "a": "z"}
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))

        assert digest(value) == "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def test_is_stable_under_dict_reordering(self) -> None:
        assert digest({"a": 1, "b": {"c": 2, "d": 3}}) == digest({"b": {"d": 3, "c": 2}, "a": 1})

    def test_differs_for_different_values(self) -> None:
        assert digest({"a": 1}) != digest({"a": 2})

    def test_content_digest_hashes_the_bytes(self) -> None:
        assert content_digest("abc\n") == "sha256:" + hashlib.sha256(b"abc\n").hexdigest()
        assert content_digest(b"abc\n") == content_digest("abc\n")


@pytest.mark.unit
class TestFileChange:
    def test_create_carries_content_and_its_digest(self) -> None:
        change = _create()

        assert change.after_digest == content_digest("# Security\n")
        assert change.before_digest is None
        assert change.ignored is False
        assert change.changes

    def test_none_requires_a_reason(self) -> None:
        with pytest.raises(ValidationError):
            FileChange(path="SECURITY.md", action="none")

    @pytest.mark.parametrize("reason", ["already_exists", "user_changes_present", "when_not_met"])
    def test_none_reasons(self, reason: str) -> None:
        change = FileChange(path="SECURITY.md", action="none", reason=reason)

        assert not change.changes
        assert change.content is None

    def test_unknown_reason_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FileChange(path="SECURITY.md", action="none", reason="looked_fine")

    @pytest.mark.parametrize("action", ["create", "modify"])
    def test_write_requires_content(self, action: str) -> None:
        with pytest.raises(ValidationError):
            FileChange(path="SECURITY.md", action=action)

    def test_modify_needs_the_state_it_was_planned_against(self) -> None:
        with pytest.raises(ValidationError):
            FileChange(path="SECURITY.md", action="modify", content="x")

    def test_write_has_no_reason(self) -> None:
        with pytest.raises(ValidationError):
            FileChange(path="SECURITY.md", action="create", content="x", reason="already_exists")

    def test_unknown_action_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FileChange(path="SECURITY.md", action="delete", content="x")

    def test_mismatched_after_digest_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FileChange(path="SECURITY.md", action="create", content="x", after_digest=content_digest("y"))

    @pytest.mark.parametrize("path", ["/etc/passwd", "../outside.md", "docs/../../outside.md", ""])
    def test_path_must_stay_inside_the_repository(self, path: str) -> None:
        with pytest.raises(ValidationError):
            _create(path=path)

    def test_extra_fields_are_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            FileChange(path="SECURITY.md", action="create", content="x", mode="0644")

    def test_round_trips_through_json(self) -> None:
        change = FileChange(path="a/b.md", action="modify", content="new\n", before_digest=content_digest("old\n"))

        assert FileChange.model_validate_json(change.model_dump_json()) == change


@pytest.mark.unit
class TestPlanItem:
    def test_digest_is_computed_from_the_item(self) -> None:
        item = PlanItem(control_id="C-1", step="file_create[0]", file_changes=[_create()], previewable=True)

        assert item.digest == digest(item.model_dump(mode="json", exclude={"digest"}))

    def test_digest_is_stable_under_reordering(self) -> None:
        first = PlanItem(control_id="C-1", step="s", change_sets=[{"a": 1, "b": 2}], previewable=True)
        second = PlanItem(control_id="C-1", step="s", change_sets=[{"b": 2, "a": 1}], previewable=True)

        assert first.digest == second.digest

    def test_digest_changes_with_the_content(self) -> None:
        first = PlanItem(control_id="C-1", step="s", file_changes=[_create(content="a")], previewable=True)
        second = PlanItem(control_id="C-1", step="s", file_changes=[_create(content="b")], previewable=True)

        assert first.digest != second.digest

    def test_a_supplied_digest_must_match(self) -> None:
        with pytest.raises(ValidationError):
            PlanItem(control_id="C-1", step="s", previewable=True, digest="sha256:" + "0" * 64)

    def test_round_trips_with_its_digest(self) -> None:
        item = PlanItem(control_id="C-1", step="exec[0]", commands=[["zizmor", "--fix"]], previewable=False)

        assert PlanItem.model_validate(item.model_dump(mode="json")) == item

    def test_extra_fields_are_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            PlanItem(control_id="C-1", step="s", previewable=True, approved=True)


@pytest.mark.unit
class TestRemediationOutcome:
    def test_kind_vocabulary(self) -> None:
        assert set(OUTCOME_KINDS) == {
            "fixed",
            "changed_not_passing",
            "changed_not_verified",
            "unchanged",
            "needs_approval",
            "needs_confirmation",
            "manual",
            "error",
        }

    def test_unknown_kind_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="applied")

    def test_fixed_requires_a_change_and_a_passing_recheck(self) -> None:
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="fixed", recheck={"status": "PASS"})
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="fixed", file_changes=[_create()], recheck={"status": "FAIL"})

        fixed = RemediationOutcome(control_id="C-1", kind="fixed", file_changes=[_create()], recheck={"status": "PASS"})
        assert fixed.kind == "fixed"

    def test_unchanged_target_is_never_fixed(self) -> None:
        none = FileChange(path="SECURITY.md", action="none", reason="already_exists")

        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="fixed", file_changes=[none], recheck={"status": "PASS"})

    def test_changed_not_passing_requires_a_change_and_a_failing_recheck(self) -> None:
        with pytest.raises(ValidationError):
            RemediationOutcome(
                control_id="C-1", kind="changed_not_passing", file_changes=[_create()], recheck={"status": "PASS"}
            )
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="changed_not_passing", recheck={"status": "FAIL"})

    def test_changed_not_verified_requires_a_change(self) -> None:
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="changed_not_verified")

    def test_error_requires_class_and_cause(self) -> None:
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="error")

        outcome = RemediationOutcome(control_id="C-1", kind="error", error={"class": "auth", "cause": "HTTP 403"})
        assert outcome.model_dump(mode="json", by_alias=True)["error"] == {"class": "auth", "cause": "HTTP 403"}

    def test_unknown_error_class_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="error", error={"class": "oops", "cause": "x"})

    def test_platform_change_set_counts_as_a_change(self) -> None:
        outcome = RemediationOutcome(
            control_id="C-1",
            kind="changed_not_verified",
            change_sets=[{"digest": "sha256:x", "operations": [{"method": "PUT"}]}],
        )
        assert outcome.kind == "changed_not_verified"

    def test_empty_change_set_is_not_a_change(self) -> None:
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="changed_not_verified", change_sets=[{"operations": []}])

    def test_extra_fields_are_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            RemediationOutcome(control_id="C-1", kind="unchanged", reason="x", status="applied")


def _run(**overrides) -> RemediationRun:
    data = {
        "run_id": "01JABCDEFGHJKMNPQRSTVWXYZ0",
        "repository": "github.com/o/r",
        "mode": "apply",
        "policy": {"platform": "prompt", "high_impact": "prompt"},
        "operator_config_digest": None,
    }
    data.update(overrides)
    return RemediationRun.model_validate(data)


@pytest.mark.unit
class TestRemediationRun:
    def test_summary_is_computed_from_outcomes(self) -> None:
        run = _run(
            outcomes=[
                {"control_id": "A", "kind": "unchanged", "reason": "already_exists"},
                {"control_id": "B", "kind": "unchanged", "reason": "already_exists"},
                {"control_id": "C", "kind": "manual"},
            ]
        )

        assert run.summary["unchanged"] == 2
        assert run.summary["manual"] == 1
        assert run.summary["fixed"] == 0
        assert set(run.summary) == set(OUTCOME_KINDS)

    def test_a_summary_that_disagrees_with_outcomes_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _run(outcomes=[{"control_id": "A", "kind": "manual"}], summary={"fixed": 1})

    def test_a_matching_summary_round_trips(self) -> None:
        run = _run(outcomes=[{"control_id": "A", "kind": "manual"}])

        assert RemediationRun.model_validate(run.model_dump(mode="json", by_alias=True)) == run

    def test_preview_has_no_outcomes(self) -> None:
        with pytest.raises(ValidationError):
            _run(mode="preview", outcomes=[{"control_id": "A", "kind": "manual"}])

        preview = _run(mode="preview", plan=[{"control_id": "A", "step": "manual[0]", "previewable": True}])
        assert preview.summary == dict.fromkeys(OUTCOME_KINDS, 0)

    def test_policy_values_are_validated(self) -> None:
        with pytest.raises(ValidationError):
            _run(policy={"platform": "always", "high_impact": "prompt"})

    def test_approvals(self) -> None:
        approved_at = datetime(2026, 10, 2, tzinfo=UTC)
        run = _run(approvals=[{"digest": "sha256:x", "approved_by": "alice", "approved_at": approved_at}])

        assert run.approvals == [Approval(digest="sha256:x", approved_by="alice", approved_at=approved_at)]

    def test_extra_fields_are_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            _run(status="ok")
