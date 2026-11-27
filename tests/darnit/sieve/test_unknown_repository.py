"""A step that names ``$OWNER``/``$REPO`` does not run when that value is unknown (#334).

A checkout with no git remote has no owner or name. Substituting "" would
ask about ``--repo /`` or ``/repos//name``, and the answer says nothing
about this repository, so ``exec`` and ``mcp`` steps stop with ERROR
``unavailable`` before anything runs, as ``gh_api`` already did.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from darnit.sieve import builtin_handlers
from darnit.sieve.builtin_handlers import exec_handler, mcp_handler
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus


def _ctx(owner: str = "", repo: str = "", **extra: Any) -> HandlerContext:
    return HandlerContext(local_path=".", owner=owner, repo=repo, default_branch="main", control_id="T-01", **extra)


@pytest.fixture
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(builtin_handlers.subprocess, "run", run)
    return calls


class TestExec:
    RELEASES = ["gh", "release", "list", "--repo", "$OWNER/$REPO", "--limit", "1"]

    @pytest.mark.parametrize(
        ("owner", "repo", "missing"), [("", "", "$OWNER and $REPO"), ("", "r", "$OWNER"), ("o", "", "$REPO")]
    )
    def test_unknown_identity_is_error_and_runs_nothing(
        self, no_subprocess: list[list[str]], owner: str, repo: str, missing: str
    ) -> None:
        result = exec_handler({"command": self.RELEASES}, _ctx(owner, repo))
        assert no_subprocess == []
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "unavailable"
        assert f"needs {missing}," in result.message
        assert result.evidence == {"command": self.RELEASES}

    def test_unknown_identity_never_proves_a_declared_failure(self, no_subprocess: list[list[str]]) -> None:
        result = exec_handler({"command": self.RELEASES, "fail_exit_codes": [1]}, _ctx())
        assert no_subprocess == []
        assert result.status == HandlerResultStatus.ERROR

    def test_known_identity_is_substituted(self, no_subprocess: list[list[str]]) -> None:
        result = exec_handler({"command": self.RELEASES}, _ctx("octo", "hello"))
        assert no_subprocess == [["gh", "release", "list", "--repo", "octo/hello", "--limit", "1"]]
        assert result.status == HandlerResultStatus.PASS

    def test_command_that_needs_no_identity_still_runs(self, no_subprocess: list[list[str]]) -> None:
        result = exec_handler({"command": ["git", "-C", "$PATH", "status"]}, _ctx())
        assert no_subprocess == [["git", "-C", ".", "status"]]
        assert result.status == HandlerResultStatus.PASS


class _NoCallPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def call_tool(self, server: str, tool: str, args: dict[str, Any], timeout: float) -> Any:
        self.calls.append((server, tool, args))
        raise AssertionError("the MCP tool must not be called")


class TestMcp:
    def test_unknown_identity_is_error_and_calls_nothing(self) -> None:
        pool = _NoCallPool()
        config = {"server": "scorecard", "tool": "check", "args": {"repo": "github.com/$OWNER/$REPO", "depth": 1}}
        result = mcp_handler(config, _ctx(mcp_pool=pool))
        assert pool.calls == []
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "unavailable"
        assert "MCP tool scorecard/check needs $OWNER and $REPO," in result.message
