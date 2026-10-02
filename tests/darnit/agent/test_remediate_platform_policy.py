"""``darnit run`` platform changes follow the operator policy (feature 043 T030; contracts section 4)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from darnit.agent.graph import remediate
from darnit.agent.state import AuditState
from darnit.config.operator.schema import RemediationSettings
from darnit.core.utils import RecordedGhApi, set_gh_api_responder
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
