"""Pattern steps prove only failure; misses are inconclusive (feature 041 US1, FR-001, FR-004)."""

from __future__ import annotations

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.builtin_handlers import regex_handler
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator

PATTERN = {"patterns": {"disclosure": r"(?i)report\s+a\s+vulnerabilit"}}


def _verify(tmp_path, *invocations: HandlerInvocation):
    spec = ControlSpec(
        control_id="PT-01",
        level=1,
        domain="PT",
        name="Pattern",
        description="Pattern",
        metadata={"handler_invocations": list(invocations)},
    )
    ctx = CheckContext(owner="o", repo="r", local_path=str(tmp_path), default_branch="main", control_id="PT-01")
    return SieveOrchestrator().verify(spec, ctx)


class TestHandlerMiss:
    def _ctx(self, tmp_path) -> HandlerContext:
        return HandlerContext(local_path=str(tmp_path))

    def test_miss_is_inconclusive(self, tmp_path) -> None:
        (tmp_path / "SECURITY.md").write_text("We have no security policy.\n")
        result = regex_handler({"files": ["SECURITY.md"], "pattern": PATTERN}, self._ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["any_match"] is False

    def test_miss_with_fail_on_miss_fails(self, tmp_path) -> None:
        (tmp_path / "SECURITY.md").write_text("We have no security policy.\n")
        result = regex_handler(
            {"files": ["SECURITY.md"], "pattern": PATTERN, "fail_on_miss": True}, self._ctx(tmp_path)
        )
        assert result.status == HandlerResultStatus.FAIL

    def test_partial_miss_with_all_required_is_inconclusive(self, tmp_path) -> None:
        (tmp_path / "SECURITY.md").write_text("Report a vulnerability to us.\n")
        pattern = {"patterns": {"disclosure": PATTERN["patterns"]["disclosure"], "email": r"\w+@\w+\.\w+"}}
        result = regex_handler(
            {"files": ["SECURITY.md"], "pattern": pattern, "pass_if_any": False}, self._ctx(tmp_path)
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_match_still_reports_pass(self, tmp_path) -> None:
        (tmp_path / "SECURITY.md").write_text("Please report a vulnerability to sec@example.org\n")
        result = regex_handler({"files": ["SECURITY.md"], "pattern": PATTERN}, self._ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS


class TestOrchestration:
    def test_match_on_content_control_does_not_conclude_pass(self, tmp_path) -> None:
        (tmp_path / "SECURITY.md").write_text("To report a vulnerability: we have no process.\n")
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="pattern", files=["SECURITY.md"], pattern=PATTERN),
            HandlerInvocation(handler="manual", steps=["Read SECURITY.md"]),
        )
        assert result.status == "WARN"
        assert result.evidence["any_match"] is True

    def test_miss_continues_to_next_step(self, tmp_path) -> None:
        (tmp_path / "SECURITY.md").write_text("We have no security policy.\n")
        (tmp_path / "LICENSE").write_text("MIT\n")
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="pattern", files=["SECURITY.md"], pattern=PATTERN),
            HandlerInvocation(handler="file_exists", files=["LICENSE"], existence=True),
        )
        assert result.status == "PASS"
        assert result.concluded_by == "file_exists"

    def test_miss_with_fail_on_miss_concludes_fail(self, tmp_path) -> None:
        (tmp_path / "SECURITY.md").write_text("We have no security policy.\n")
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="pattern", files=["SECURITY.md"], pattern=PATTERN, fail_on_miss=True),
            HandlerInvocation(handler="manual", steps=["Read SECURITY.md"]),
        )
        assert result.status == "FAIL"
        assert result.concluded_by == "pattern"

    def test_existence_pattern_concludes_pass(self, tmp_path) -> None:
        result = _verify(
            tmp_path,
            HandlerInvocation(
                handler="pattern", exclude_files=["**/*.exe"], expr="output.files_found == 0", existence=True
            ),
        )
        assert result.status == "PASS"

    def test_exclude_mode_absence_without_existence_does_not_pass(self, tmp_path) -> None:
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="pattern", exclude_files=["**/*.exe"], expr="output.files_found == 0"),
        )
        assert result.status == "WARN"

    def test_exclude_mode_presence_concludes_fail(self, tmp_path) -> None:
        (tmp_path / "tool.exe").write_bytes(b"MZ")
        result = _verify(
            tmp_path,
            HandlerInvocation(handler="pattern", exclude_files=["**/*.exe"], expr="output.files_found == 0"),
        )
        assert result.status == "FAIL"
