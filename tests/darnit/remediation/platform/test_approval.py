"""Digest-bound approval of platform change sets (feature 043 T019; FR-005, FR-008, R5, SC-002)."""

from __future__ import annotations

import pytest

from darnit.config.operator.schema import RemediationSettings
from darnit.remediation.platform import PlatformRequirement, ResolvedPolicy, apply, plan
from tests.darnit.remediation.platform.conftest import REPO_PATH, _base, _protection, stricter

REPOSITORY = "github.com/o/r"
PROTECTION = f"{REPO_PATH}/branches/main/protection"
AC_03_02 = PlatformRequirement(target="branch_protection", require={"prevent_deletion": True})
PUBLIC = PlatformRequirement(target="repository", require={"visibility": "public"})
PROMPT = ResolvedPolicy(settings=RemediationSettings(), operator_config_digest=None, operator="alice")


def _writes(gh) -> list[tuple]:
    return [(w.method, w.endpoint, w.body) for w in gh.writes]


@pytest.mark.unit
def test_approved_digest_writes_exactly_the_planned_operations(simulated_gh) -> None:
    gh = simulated_gh("stricter")
    [preview] = plan(REPOSITORY, [AC_03_02])

    [result] = apply(REPOSITORY, [AC_03_02], policy=PROMPT, approvals=[preview.change_set.digest])

    assert result.kind == "applied"
    assert _writes(gh) == [(op.method, op.endpoint, op.body) for op in preview.change_set.operations]
    assert result.approval.digest == preview.change_set.digest
    assert result.approval.approved_by == "alice"
    assert result.approval.approved_at is not None


@pytest.mark.unit
def test_digest_from_a_different_observed_state_is_stale(simulated_gh) -> None:
    simulated_gh("stricter")
    [preview] = plan(REPOSITORY, [AC_03_02])
    changed = stricter()
    changed[PROTECTION]["body"]["required_linear_history"] = {"enabled": False}
    gh = simulated_gh(changed)

    [result] = apply(REPOSITORY, [AC_03_02], policy=PROMPT, approvals=[preview.change_set.digest])

    assert result.kind == "unchanged"
    assert result.reason == "stale_preview"
    assert gh.writes == []


@pytest.mark.unit
def test_batch_approval_does_not_cover_a_high_impact_change_set(simulated_gh) -> None:
    simulated_gh(_base(protection=_protection(allow_deletions=True), private=True))
    previews = {p.target.kind: p.change_set for p in plan(REPOSITORY, [AC_03_02, PUBLIC])}
    gh = simulated_gh(_base(protection=_protection(allow_deletions=True), private=True))

    results = apply(REPOSITORY, [AC_03_02, PUBLIC], policy=PROMPT, approvals=[previews["branch_protection"].digest])

    kinds = {r.target.kind: r.kind for r in results}
    assert kinds == {"branch_protection": "applied", "repository": "needs_approval"}
    assert [(w.method, w.endpoint) for w in gh.writes] == [("PUT", PROTECTION)]


@pytest.mark.unit
def test_high_impact_change_set_applies_with_its_own_digest(simulated_gh) -> None:
    simulated_gh("private_repo")
    [preview] = plan(REPOSITORY, [PUBLIC])
    gh = simulated_gh("private_repo")

    [result] = apply(REPOSITORY, [PUBLIC], policy=PROMPT, approvals=[preview.change_set.digest])

    assert result.kind == "applied"
    assert _writes(gh) == [("PATCH", REPO_PATH, {"visibility": "public"})]


@pytest.mark.unit
def test_an_apply_flag_is_not_an_approval(simulated_gh) -> None:
    gh = simulated_gh("stricter")

    [result] = apply(REPOSITORY, [AC_03_02], policy=PROMPT, approvals=["sha256:" + "f" * 64])

    assert result.kind in ("needs_approval", "unchanged")
    assert gh.writes == []


@pytest.mark.unit
@pytest.mark.parametrize(("answer", "kind"), [(True, "applied"), (False, "needs_approval")])
def test_an_approver_is_asked_for_each_change_set(simulated_gh, answer: bool, kind: str) -> None:
    gh = simulated_gh("stricter")
    asked = []

    def approver(change_set) -> bool:
        asked.append(change_set.digest)
        return answer

    [result] = apply(REPOSITORY, [AC_03_02], policy=PROMPT, approver=approver)

    assert asked == [result.change_set.digest]
    assert result.kind == kind
    assert bool(gh.writes) is answer
    assert (result.approval is not None) is answer


@pytest.mark.unit
def test_auto_never_asks(simulated_gh) -> None:
    simulated_gh("stricter")

    def approver(change_set) -> bool:
        raise AssertionError("auto must not ask")

    policy = ResolvedPolicy(settings=RemediationSettings(platform="auto"), operator_config_digest=None, operator="a")
    [result] = apply(REPOSITORY, [AC_03_02], policy=policy, approver=approver)

    assert result.kind == "applied"
