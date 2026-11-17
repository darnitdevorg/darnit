"""Frameworks are selected by registered name; a framework file in the audited repository is never loaded.

Covers framework-design 14.5: MCP and harness state, and the audit pipeline,
take only registered framework names; a framework file given by path is
refused when it lies inside the audited repository.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from darnit.config.merger import (
    FrameworkSelectionError,
    refuse_framework_inside_checkout,
    require_framework_name,
    resolve_framework_path,
)
from darnit.core.action_plan import HarnessState
from darnit.server.tools.harness_loop import run_next_action_tool, submit_action_result_tool

REGISTERED = "hello"

FRAMEWORK_TOML = """[metadata]
name = "repo-supplied"
display_name = "Repository-supplied framework"
version = "0.1.0"
spec_version = "x"

[controls."X-01.01"]
name = "WritesMarker"
description = "Runs a command."
tags = {{ level = 1, domain = "X" }}

[[controls."X-01.01".passes]]
handler = "exec"
command = ["sh", "-c", "echo ran > '{marker}'"]
"""


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "marker"


@pytest.fixture
def repo(tmp_path: Path, marker: Path) -> Path:
    """A checkout carrying a framework file whose one step writes ``marker``."""
    path = tmp_path / "repo"
    (path / ".darnit").mkdir(parents=True)
    (path / "README.md").write_text("# Project\n", encoding="utf-8")
    (path / ".darnit" / "fw.toml").write_text(FRAMEWORK_TOML.format(marker=marker), encoding="utf-8")
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/o/r.git"], cwd=path, check=True)
    return path


def _state(repo: Path, framework_name: str | None) -> dict:
    return {"local_path": str(repo), "owner": "o", "repo": "r", "framework_name": framework_name}


@pytest.mark.unit
class TestFrameworkName:
    @pytest.mark.parametrize(
        "value",
        [
            "/abs/fw.toml",
            "repo/.darnit/fw.toml",
            ".darnit/fw.toml",
            "fw.toml",
            "./fw",
            "../fw",
            "~/fw",
            "dir\\fw",
            "",
        ],
    )
    def test_path_like_values_are_refused(self, value: str) -> None:
        with pytest.raises(FrameworkSelectionError):
            require_framework_name(value)
        with pytest.raises(FrameworkSelectionError):
            resolve_framework_path(value)

    def test_registered_name_resolves(self) -> None:
        path = resolve_framework_path(REGISTERED)

        assert path is not None and path.name == "hello.toml"

    def test_unregistered_name_resolves_to_nothing(self) -> None:
        assert resolve_framework_path("no-such-framework") is None

    def test_harness_state_refuses_a_path(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="framework_name"):
            HarnessState(local_path=str(tmp_path), framework_name=str(tmp_path / "fw.toml"))


@pytest.mark.unit
class TestInsideCheckout:
    def test_file_inside_is_refused(self, repo: Path) -> None:
        with pytest.raises(FrameworkSelectionError, match="inside the audited repository"):
            refuse_framework_inside_checkout(repo / ".darnit" / "fw.toml", repo)

    def test_relative_traversal_inside_is_refused(self, repo: Path) -> None:
        with pytest.raises(FrameworkSelectionError):
            refuse_framework_inside_checkout(repo / "sub" / ".." / ".darnit" / "fw.toml", repo)

    def test_symlink_outside_to_a_file_inside_is_refused(self, repo: Path, tmp_path: Path) -> None:
        link = tmp_path / "fw-link.toml"
        link.symlink_to(repo / ".darnit" / "fw.toml")

        with pytest.raises(FrameworkSelectionError):
            refuse_framework_inside_checkout(link, repo)

    def test_file_outside_is_accepted(self, repo: Path, tmp_path: Path) -> None:
        outside = tmp_path / "operator-fw.toml"
        outside.write_text("", encoding="utf-8")

        refuse_framework_inside_checkout(outside, repo)

    def test_sibling_with_common_prefix_is_outside(self, repo: Path, tmp_path: Path) -> None:
        sibling = tmp_path / "repo-other" / "fw.toml"
        sibling.parent.mkdir()
        sibling.write_text("", encoding="utf-8")

        refuse_framework_inside_checkout(sibling, repo)


@pytest.mark.integration
class TestHarnessLoopTools:
    def test_run_next_action_refuses_a_framework_path(self, repo: Path, marker: Path) -> None:
        with pytest.raises(ValueError, match="framework_name"):
            _run(run_next_action_tool(_state(repo, str(repo / ".darnit" / "fw.toml"))))

        assert not marker.exists()

    def test_submit_action_result_refuses_a_framework_path(self, repo: Path, marker: Path) -> None:
        with pytest.raises(ValueError, match="not a framework name"):
            _run(submit_action_result_tool(_state(repo, str(repo / ".darnit" / "fw.toml")), "audit-0", {}))

        assert not marker.exists()

    def test_relative_framework_path_is_refused(self, repo: Path, marker: Path) -> None:
        with pytest.raises(ValueError, match="not a framework name"):
            _run(submit_action_result_tool(_state(repo, ".darnit/fw.toml"), "audit-0", {}))

        assert not marker.exists()

    def test_unregistered_name_is_refused(self, repo: Path, marker: Path) -> None:
        with pytest.raises(ValueError, match="not registered"):
            _run(run_next_action_tool(_state(repo, "repo-supplied")))
        with pytest.raises(ValueError, match="not registered"):
            _run(submit_action_result_tool(_state(repo, "repo-supplied"), "audit-0", {}))

        assert not marker.exists()

    def test_registered_name_runs_the_audit(self, repo: Path, marker: Path) -> None:
        state = _state(repo, REGISTERED)

        plan = _run(run_next_action_tool(state))
        assert plan is not None and plan["step"]["integration"] == "audit"

        new_state = _run(submit_action_result_tool(state, plan["step"]["id"], {}))

        assert new_state["error"] is None
        assert any(r["id"] == "HELLO-01.01" for r in new_state["audit_results"])
        assert not marker.exists()


@pytest.mark.integration
class TestOtherEntryPoints:
    def test_audit_pipeline_refuses_a_framework_path(self, repo: Path, marker: Path) -> None:
        from darnit.tools.audit import run_sieve_audit

        with pytest.raises(FrameworkSelectionError):
            run_sieve_audit("o", "r", str(repo), "main", 1, framework_name=str(repo / ".darnit" / "fw.toml"))

        assert not marker.exists()

    def test_agent_audit_node_refuses_a_framework_path(self, repo: Path, marker: Path) -> None:
        from darnit.agent.graph import audit
        from darnit.agent.state import AuditState

        state = audit(AuditState(local_path=str(repo), owner="o", repo="r", framework_name=".darnit/fw.toml"))

        assert state.error and "not a framework name" in state.error
        assert not marker.exists()

    def test_cli_audit_refuses_a_framework_file_inside_the_repository(self, repo: Path, marker: Path) -> None:
        from darnit.cli import main

        assert main(["audit", str(repo), "--framework", str(repo / ".darnit" / "fw.toml")]) == 1
        assert not marker.exists()

    def test_cli_audit_refuses_a_symlink_into_the_repository(
        self, repo: Path, marker: Path, tmp_path: Path
    ) -> None:
        from darnit.cli import main

        link = tmp_path / "fw-link.toml"
        link.symlink_to(repo / ".darnit" / "fw.toml")

        assert main(["audit", str(repo), "--framework", str(link)]) == 1
        assert not marker.exists()

    def test_cli_audit_still_loads_an_operator_framework_file_outside(
        self, repo: Path, marker: Path, tmp_path: Path
    ) -> None:
        from darnit.cli import main

        outside = tmp_path / "operator" / "fw.toml"
        outside.parent.mkdir()
        outside.write_text((repo / ".darnit" / "fw.toml").read_text(encoding="utf-8"), encoding="utf-8")

        main(["audit", str(repo), "--framework", str(outside)])

        assert marker.exists()

    def test_cli_run_refuses_a_framework_path(self, repo: Path, marker: Path) -> None:
        from darnit.cli import main

        assert main(["run", str(repo), "--framework", str(repo / ".darnit" / "fw.toml")]) == 1
        assert not marker.exists()
