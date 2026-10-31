"""Integration tests for OSPS-BR-01.02 (SecureBranchNames).

Verifies (fixes #647):
- Grep match (exit code 0) records as inconclusive evidence without an unexpected_exit error class.
- Grep without match (exit code 1) records as PASS without an error class.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config.merger import load_framework_by_name
from darnit.core.plugin import ControlSpec
from darnit.sieve.handler_registry import reset_sieve_handler_registry
from darnit.sieve.models import CheckContext, PassOutcome
from darnit.sieve.orchestrator import SieveOrchestrator


@pytest.fixture(autouse=True)
def _register_baseline_handlers():
    reset_sieve_handler_registry()
    from darnit.core.discovery import get_implementation

    impl = get_implementation("openssf-baseline")
    assert impl is not None, "openssf-baseline implementation not discovered"
    impl.register_handlers()
    yield


def _load_control(control_id: str = "OSPS-BR-01.02") -> ControlSpec:
    config = load_framework_by_name("openssf-baseline")
    control = config.controls[control_id]
    tags = control.tags or {}
    level = control.level if control.level is not None else tags.get("level", 1)
    domain = control.domain if control.domain is not None else tags.get("domain", "UNKNOWN")
    return ControlSpec(
        control_id=control_id,
        name=control.name,
        description=control.description or "",
        level=level,
        domain=domain,
        metadata={"handler_invocations": control.passes, "when": control.when},
    )


def _ctx(tmp_path: Path) -> CheckContext:
    return CheckContext(
        owner="testorg",
        repo="testrepo",
        local_path=str(tmp_path),
        default_branch="main",
        control_id="OSPS-BR-01.02",
        project_context={"platform": "github", "ci_provider": "github"},
    )


class TestSecureBranchNames:
    """OSPS-BR-01.02 execution tests."""

    def test_toml_declares_fail_exit_codes(self) -> None:
        config = load_framework_by_name("openssf-baseline")
        control = config.controls["OSPS-BR-01.02"]
        assert control.passes, "OSPS-BR-01.02 must have passes"
        # github_workflows_present is the first step (#584); the grep step follows it.
        assert control.passes[0].handler == "github_workflows_present"
        exec_step = control.passes[1]
        assert exec_step.handler == "exec"
        assert exec_step.model_extra.get("pass_exit_codes") == [1]
        assert exec_step.model_extra.get("fail_exit_codes") == [0]

    def test_grep_match_records_evidence_without_unexpected_exit(self, tmp_path: Path) -> None:
        """Fixes #647: a match (exit 0) is evidence, not an error."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("run: echo ${{ github.head_ref }}\n", encoding="utf-8")

        ctrl = _load_control("OSPS-BR-01.02")
        result = SieveOrchestrator().verify(ctrl, _ctx(tmp_path))
        assert result.status == "WARN"
        assert result.error_class is None
        # The guard is evidence only when a workflow file exists; the grep step follows it.
        assert result.pass_history[0].checks_performed == ["handler:github_workflows_present"]
        exec_attempt = result.pass_history[1]
        assert exec_attempt.checks_performed == ["handler:exec"]
        assert exec_attempt.result.outcome == PassOutcome.FAIL
        assert exec_attempt.result.evidence.get("exit_code") == 0
        assert "ci.yml" in exec_attempt.result.evidence.get("stdout", "")

    def test_grep_no_match_passes_cleanly(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("run: echo 'safe workflow'\n", encoding="utf-8")

        ctrl = _load_control("OSPS-BR-01.02")
        result = SieveOrchestrator().verify(ctrl, _ctx(tmp_path))
        assert result.status == "WARN"
        assert result.error_class is None
        assert result.pass_history[0].checks_performed == ["handler:github_workflows_present"]
        exec_attempt = result.pass_history[1]
        assert exec_attempt.checks_performed == ["handler:exec"]
        assert exec_attempt.result.outcome == PassOutcome.PASS
        assert exec_attempt.result.evidence.get("exit_code") == 1
