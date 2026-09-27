"""Presence steps prove absence, not content (feature 041 US1, FR-001)."""

from __future__ import annotations

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator


def _verify(tmp_path, *invocations: HandlerInvocation):
    spec = ControlSpec(
        control_id="PR-01",
        level=1,
        domain="PR",
        name="Presence",
        description="Presence",
        metadata={"handler_invocations": list(invocations)},
    )
    ctx = CheckContext(owner="o", repo="r", local_path=str(tmp_path), default_branch="main", control_id="PR-01")
    return SieveOrchestrator().verify(spec, ctx)


def test_present_file_does_not_conclude_pass_for_content_control(tmp_path) -> None:
    (tmp_path / "README.md").write_text("TODO\n")
    result = _verify(tmp_path, HandlerInvocation(handler="file_exists", files=["README.md"]))
    assert result.status == "WARN"
    assert result.concluded_by == "none"
    assert result.evidence["relative_path"] == "README.md"


def test_present_file_continues_to_next_step(tmp_path) -> None:
    (tmp_path / "README.md").write_text("TODO\n")
    result = _verify(
        tmp_path,
        HandlerInvocation(handler="file_exists", files=["README.md"]),
        HandlerInvocation(handler="manual", steps=["Read the README"]),
    )
    assert result.status == "WARN"
    assert [a.checks_performed for a in result.pass_history] == [["handler:file_exists"], ["handler:manual"]]


def test_missing_file_concludes_fail(tmp_path) -> None:
    result = _verify(
        tmp_path,
        HandlerInvocation(handler="file_exists", files=["README.md"]),
        HandlerInvocation(handler="manual", steps=["Read the README"]),
    )
    assert result.status == "FAIL"
    assert result.authority == "dispositive"
    assert result.concluded_by == "file_exists"
    assert result.resolving_pass_index == 0


def test_existence_requirement_concludes_pass(tmp_path) -> None:
    (tmp_path / "LICENSE").write_text("MIT\n")
    result = _verify(
        tmp_path,
        HandlerInvocation(handler="file_exists", files=["LICENSE"], existence=True),
        HandlerInvocation(handler="manual", steps=["Check the license"]),
    )
    assert result.status == "PASS"
    assert result.authority == "dispositive"
    assert result.concluded_by == "file_exists"


def test_existence_requirement_missing_still_fails(tmp_path) -> None:
    result = _verify(tmp_path, HandlerInvocation(handler="file_exists", files=["LICENSE"], existence=True))
    assert result.status == "FAIL"


def test_existence_narrowed_to_fail_does_not_pass(tmp_path) -> None:
    (tmp_path / "LICENSE").write_text("MIT\n")
    result = _verify(
        tmp_path, HandlerInvocation(handler="file_exists", files=["LICENSE"], existence=True, concludes=["fail"])
    )
    assert result.status == "WARN"
