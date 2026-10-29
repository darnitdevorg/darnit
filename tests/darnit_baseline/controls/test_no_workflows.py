"""#584: controls that audit GitHub Actions workflows, on a repository without any.

OSPS-BR-01.01, OSPS-BR-01.02, and OSPS-AC-04.02 run while ``ci_provider`` is
unconfirmed. Without workflow files zizmor exits 3 and ``grep`` exits 2, and
the controls used to end ``WARN [unexpected_exit]`` with a generic message and
log an ``unexpected_exit`` WARNING per command. ``github_workflows_present``
now runs first: it ends them WARN with its reason, and neither command runs.
With workflow files present every decision is the one the controls give
without that step, one step index later; so is BR-01.01's with only a
standalone action definition, which zizmor's template-injection audit reads.

Commands are answered by a stand-in for ``subprocess.run`` with the exit
codes and stderr the real tools give (#584), so the tests do not depend on
zizmor, ``grep``, or ``sh`` being installed.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from darnit.cli import format_result_text
from darnit.config import load_framework_config
from darnit.config.control_loader import control_from_framework
from darnit.sieve import builtin_handlers
from darnit.sieve.builtin_handlers import _classify_exec_failure
from darnit.sieve.handler_registry import reset_sieve_handler_registry
from darnit.sieve.models import CheckContext, ControlSpec, SieveResult
from darnit.sieve.orchestrator import SieveOrchestrator
from darnit_baseline.github_workflows import NO_WORKFLOWS_MESSAGE, NO_WORKFLOWS_OR_ACTIONS_MESSAGE

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_TOML = REPO_ROOT / "packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml"
CONTROLS = ("OSPS-BR-01.01", "OSPS-BR-01.02", "OSPS-AC-04.02")
# BR-01.01's zizmor audit (template-injection) also reads action definitions.
NOTHING_TO_AUDIT = {
    "OSPS-BR-01.01": NO_WORKFLOWS_OR_ACTIONS_MESSAGE,
    "OSPS-BR-01.02": NO_WORKFLOWS_MESSAGE,
    "OSPS-AC-04.02": NO_WORKFLOWS_MESSAGE,
}
GUARD = "github_workflows_present"
EXEC_LOGGER = builtin_handlers.logger.name

ZIZMOR_NO_INPUTS = (3, "", "fatal: no audit was performed\nerror: no inputs collected\n")
GREP_NO_DIRECTORY = (2, "", "grep: .github/workflows/: No such file or directory\n")
# `! grep -rEq ... .github/workflows 2>/dev/null` exits 0 when grep exits 2.
SH_NEGATED_GREP = (0, "", "")
NO_WORKFLOW_TOOLS = {"zizmor": ZIZMOR_NO_INPUTS, "grep": GREP_NO_DIRECTORY, "sh": SH_NEGATED_GREP}

WORKFLOW = "name: ci\non: push\npermissions: read-all\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"


@pytest.fixture(autouse=True)
def _baseline_handlers():
    reset_sieve_handler_registry()
    from darnit.core.discovery import get_implementation

    impl = get_implementation("openssf-baseline")
    assert impl is not None
    impl.register_handlers()


class Tools:
    """``outcomes[executable] = (exit_code, stdout, stderr)``, or None for not installed; ``calls`` records each run."""

    def __init__(self) -> None:
        self.outcomes: dict[str, tuple[int, str, str] | None] = {}
        self.calls: list[str] = []


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch) -> Tools:
    """Stand-in for ``subprocess.run`` for the stubbed executables; other commands run for real."""
    stub = Tools()
    real_run = subprocess.run

    def run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] in stub.outcomes:
            stub.calls.append(cmd[0])
            outcome = stub.outcomes[cmd[0]]
            if outcome is None:
                raise FileNotFoundError(cmd[0])
            code, stdout, stderr = outcome
            return subprocess.CompletedProcess(cmd, code, stdout, stderr)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(builtin_handlers.subprocess, "run", run)
    return stub


def _shipped(control_id: str) -> ControlSpec:
    framework = load_framework_config(BASELINE_TOML)
    return control_from_framework(
        control_id, framework.controls[control_id].model_copy(deep=True), framework=framework.metadata.name
    )


def _without_guard(spec: ControlSpec) -> ControlSpec:
    steps = [s for s in spec.metadata["handler_invocations"] if s.handler != GUARD]
    return dataclasses.replace(spec, metadata={**spec.metadata, "handler_invocations": steps})


def _verify(spec: ControlSpec, repo: Path, project: dict[str, Any] | None = None) -> SieveResult:
    context = CheckContext(
        owner="example-org",
        repo="example",
        local_path=str(repo),
        default_branch="main",
        control_id=spec.control_id,
        project_context=dict(project or {}),
    )
    return SieveOrchestrator(stop_on_llm=False).verify(spec, context)


def _decision(result: SieveResult) -> tuple:
    return (result.status, result.message, result.error_class, result.error, result.concluded_by, result.authority)


def _steps(result: SieveResult) -> list[tuple]:
    return [(a.checks_performed, a.result.outcome, a.result.message) for a in result.pass_history]


def _exec_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == EXEC_LOGGER and r.levelno >= logging.WARNING and "could not complete" in r.getMessage()
    ]


def _with_workflow(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / name).write_text(WORKFLOW, encoding="utf-8")
    return repo


def _no_github(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# example\n", encoding="utf-8")
    return repo


def _empty_workflows(tmp_path: Path) -> Path:
    repo = _no_github(tmp_path)
    (repo / ".github" / "workflows").mkdir(parents=True)
    return repo


def _no_yaml_workflows(tmp_path: Path) -> Path:
    repo = _empty_workflows(tmp_path)
    (repo / ".github" / "workflows" / "README.md").write_text("CI lives elsewhere\n", encoding="utf-8")
    return repo


NO_WORKFLOW_REPOS = {"no-github-dir": _no_github, "empty-workflows": _empty_workflows, "no-yaml": _no_yaml_workflows}


@pytest.mark.parametrize("layout", sorted(NO_WORKFLOW_REPOS))
@pytest.mark.parametrize("control_id", CONTROLS)
class TestNoWorkflowFiles:
    def test_warn_says_there_is_nothing_to_audit(self, control_id, layout, tmp_path, tools) -> None:
        tools.outcomes.update(NO_WORKFLOW_TOOLS)

        result = _verify(_shipped(control_id), NO_WORKFLOW_REPOS[layout](tmp_path))

        assert result.status == "WARN"
        assert result.message == NOTHING_TO_AUDIT[control_id]
        assert result.error_class is None
        assert result.error is None
        assert (result.concluded_by, result.resolving_pass_index) == (GUARD, 0)
        assert [a.checks_performed for a in result.pass_history] == [[f"handler:{GUARD}"]]

    def test_no_command_runs_and_nothing_is_logged(self, control_id, layout, tmp_path, tools, caplog) -> None:
        tools.outcomes.update(NO_WORKFLOW_TOOLS)
        caplog.set_level(logging.WARNING)

        _verify(_shipped(control_id), NO_WORKFLOW_REPOS[layout](tmp_path))

        assert tools.calls == []
        assert _exec_warnings(caplog) == []
        assert "unexpected_exit" not in caplog.text

    def test_without_the_step_it_was_unexpected_exit(self, control_id, layout, tmp_path, tools, caplog) -> None:
        """The #584 report, reproduced with the step removed, so the assertions above are not vacuous."""
        tools.outcomes.update(NO_WORKFLOW_TOOLS)
        caplog.set_level(logging.WARNING)

        before = _verify(_without_guard(_shipped(control_id)), NO_WORKFLOW_REPOS[layout](tmp_path))

        assert (before.status, before.error_class, before.concluded_by) == ("WARN", "unexpected_exit", "none")
        assert before.message == "Could not automatically verify - manual verification required"
        assert tools.calls
        assert any("error_class=unexpected_exit" in m for m in _exec_warnings(caplog))

    def test_text_line_names_the_reason_without_an_error_class(self, control_id, layout, tmp_path, tools) -> None:
        tools.outcomes.update(NO_WORKFLOW_TOOLS)

        line = format_result_text(_verify(_shipped(control_id), NO_WORKFLOW_REPOS[layout](tmp_path)).to_legacy_dict())

        assert f"{control_id}: WARN - No GitHub Actions workflow files" in line
        assert "[" not in line.split(" - ", 1)[0]

    def test_tools_not_installed(self, control_id, layout, tmp_path, tools) -> None:
        tools.outcomes.update({"zizmor": None, "grep": None, "sh": None})

        result = _verify(_shipped(control_id), NO_WORKFLOW_REPOS[layout](tmp_path))

        assert (result.status, result.message, result.error_class) == ("WARN", NOTHING_TO_AUDIT[control_id], None)
        assert tools.calls == []


@pytest.mark.parametrize("control_id", CONTROLS)
class TestApplicability:
    def test_unconfirmed_ci_provider_is_not_pass_fail_or_na(self, control_id, tmp_path, tools) -> None:
        tools.outcomes.update(NO_WORKFLOW_TOOLS)

        result = _verify(_shipped(control_id), _no_github(tmp_path), project={})

        assert result.status not in ("PASS", "FAIL", "N/A")
        assert result.status == "WARN"

    @pytest.mark.parametrize("provider", ["gitlab", "none"])
    def test_confirmed_non_github_provider_is_na(self, control_id, provider, tmp_path, tools) -> None:
        tools.outcomes.update(NO_WORKFLOW_TOOLS)

        result = _verify(_shipped(control_id), _no_github(tmp_path), project={"ci_provider": provider})

        assert result.status == "N/A"
        assert result.pass_history == []
        assert tools.calls == []

    def test_confirmed_github_without_workflows_warns(self, control_id, tmp_path, tools) -> None:
        tools.outcomes.update(NO_WORKFLOW_TOOLS)

        result = _verify(_shipped(control_id), _no_github(tmp_path), project={"ci_provider": "github"})

        assert (result.status, result.message) == ("WARN", NOTHING_TO_AUDIT[control_id])


# Tool answers on a repository with a workflow file.
WORKFLOW_SCENARIOS = {
    "zizmor-clean": {"zizmor": (0, "[]", ""), "grep": (1, "", ""), "sh": (0, "", "")},
    "zizmor-template-injection": {
        "zizmor": (14, json.dumps([{"ident": "template-injection"}]), ""),
        "grep": (1, "", ""),
        "sh": (1, "", ""),
    },
    "zizmor-excessive-permissions": {
        "zizmor": (14, json.dumps([{"ident": "excessive-permissions"}]), ""),
        "grep": (1, "", ""),
        "sh": (0, "", ""),
    },
    "zizmor-no-findings-document": {"zizmor": (0, "", ""), "grep": (1, "", ""), "sh": (0, "", "")},
    "zizmor-unexpected-exit": {"zizmor": (2, "", "error: unrecognized input"), "grep": (1, "", ""), "sh": (0, "", "")},
    "tools-missing": {"zizmor": None, "grep": None, "sh": None},
    "grep-match-647": {"zizmor": (0, "[]", ""), "grep": (0, ".github/workflows/ci.yml\n", ""), "sh": (0, "", "")},
}


@pytest.mark.parametrize("scenario", sorted(WORKFLOW_SCENARIOS))
@pytest.mark.parametrize("name", ["ci.yml", "ci.yaml"])
@pytest.mark.parametrize("control_id", CONTROLS)
class TestWorkflowFilesPresent:
    def test_decision_is_unchanged_one_step_later(self, control_id, name, scenario, tmp_path, tools, caplog) -> None:
        tools.outcomes.update(WORKFLOW_SCENARIOS[scenario])
        spec = _shipped(control_id)
        repo = _with_workflow(tmp_path, name)
        caplog.set_level(logging.WARNING)

        before = _verify(_without_guard(spec), repo)
        before_calls, before_logs = list(tools.calls), _exec_warnings(caplog)
        tools.calls.clear()
        caplog.clear()
        after = _verify(spec, repo)

        assert _decision(after) == _decision(before)
        shift = None if before.resolving_pass_index is None else before.resolving_pass_index + 1
        assert after.resolving_pass_index == shift
        assert after.pass_history[0].checks_performed == [f"handler:{GUARD}"]
        assert after.pass_history[0].result.outcome.value == "inconclusive"
        assert _steps(after)[1:] == _steps(before)
        assert tools.calls == before_calls
        assert _exec_warnings(caplog) == before_logs


class TestKnownResultsWithWorkflows:
    """Spot checks of the pairs above, so an unchanged-but-wrong pair cannot pass."""

    @pytest.mark.parametrize("control_id", ["OSPS-BR-01.01", "OSPS-AC-04.02"])
    def test_clean_zizmor_passes_at_the_zizmor_step(self, control_id, tmp_path, tools) -> None:
        tools.outcomes.update(WORKFLOW_SCENARIOS["zizmor-clean"])

        result = _verify(_shipped(control_id), _with_workflow(tmp_path, "ci.yml"))

        assert (result.status, result.concluded_by, result.resolving_pass_index) == ("PASS", "exec", 1)

    @pytest.mark.parametrize("control_id", ["OSPS-BR-01.01", "OSPS-AC-04.02"])
    def test_zizmor_unexpected_exit_keeps_its_class(self, control_id, tmp_path, tools) -> None:
        tools.outcomes.update(WORKFLOW_SCENARIOS["zizmor-unexpected-exit"])

        result = _verify(_shipped(control_id), _with_workflow(tmp_path, "ci.yml"))

        assert (result.status, result.error_class) == ("WARN", "unexpected_exit")

    def test_grep_match_is_still_unexpected_exit(self, tmp_path, tools) -> None:
        """#647 is out of scope: grep exit 0 keeps its current mapping."""
        tools.outcomes.update(WORKFLOW_SCENARIOS["grep-match-647"])

        result = _verify(_shipped("OSPS-BR-01.02"), _with_workflow(tmp_path, "ci.yml"))

        assert (result.status, result.error_class, result.concluded_by) == ("WARN", "unexpected_exit", "none")

    def test_grep_no_match_is_undetermined_warn(self, tmp_path, tools) -> None:
        tools.outcomes.update(WORKFLOW_SCENARIOS["zizmor-clean"])

        result = _verify(_shipped("OSPS-BR-01.02"), _with_workflow(tmp_path, "ci.yaml"))

        assert (result.status, result.error_class, result.concluded_by) == ("WARN", None, "none")

    @pytest.mark.parametrize("control_id", CONTROLS)
    def test_missing_tools_stay_error(self, control_id, tmp_path, tools) -> None:
        tools.outcomes.update(WORKFLOW_SCENARIOS["tools-missing"])

        result = _verify(_shipped(control_id), _with_workflow(tmp_path, "ci.yml"))

        assert (result.status, result.error_class) == ("ERROR", "missing_tool")


# A composite action with the injection zizmor's template-injection audit reports.
ACTION = (
    "name: greet\nruns:\n  using: composite\n  steps:\n"
    '    - run: echo "${{ github.event.issue.title }}"\n      shell: bash\n'
)


def _with_action(tmp_path: Path, path: str, empty_workflows: bool = False) -> Path:
    repo = _no_github(tmp_path)
    if empty_workflows:
        (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(ACTION, encoding="utf-8")
    return repo


ACTION_REPOS = {
    "root-action.yml": lambda tmp: _with_action(tmp, "action.yml"),
    "nested-action.yaml": lambda tmp: _with_action(tmp, ".github/actions/setup/action.yaml"),
    "action-and-empty-workflows": lambda tmp: _with_action(tmp, "action.yml", empty_workflows=True),
}
# Tool answers on a repository whose only GitHub Actions input is an action
# definition; `sh -c '! grep ... .github/workflows 2>/dev/null'` exits 0.
ACTION_SCENARIOS = {
    "zizmor-clean": {"zizmor": (0, "[]", ""), "sh": SH_NEGATED_GREP},
    "zizmor-template-injection": {
        "zizmor": (13, json.dumps([{"ident": "template-injection"}]), ""),
        "sh": SH_NEGATED_GREP,
    },
    "zizmor-other-finding": {"zizmor": (12, json.dumps([{"ident": "unpinned-uses"}]), ""), "sh": SH_NEGATED_GREP},
    "zizmor-no-findings-document": {"zizmor": (0, "", ""), "sh": SH_NEGATED_GREP},
    "zizmor-missing": {"zizmor": None, "sh": SH_NEGATED_GREP},
}


@pytest.mark.parametrize("layout", sorted(ACTION_REPOS))
class TestStandaloneActionDefinitions:
    """zizmor collects action.yml/action.yaml from the whole tree and its template-injection audit reads them."""

    @pytest.mark.parametrize("scenario", sorted(ACTION_SCENARIOS))
    def test_br_01_01_decision_is_unchanged_one_step_later(self, layout, scenario, tmp_path, tools, caplog) -> None:
        tools.outcomes.update(ACTION_SCENARIOS[scenario])
        spec = _shipped("OSPS-BR-01.01")
        repo = ACTION_REPOS[layout](tmp_path)
        caplog.set_level(logging.WARNING)

        before = _verify(_without_guard(spec), repo)
        before_calls, before_logs = list(tools.calls), _exec_warnings(caplog)
        tools.calls.clear()
        caplog.clear()
        after = _verify(spec, repo)

        assert _decision(after) == _decision(before)
        shift = None if before.resolving_pass_index is None else before.resolving_pass_index + 1
        assert after.resolving_pass_index == shift
        assert after.pass_history[0].checks_performed == [f"handler:{GUARD}"]
        assert after.pass_history[0].result.outcome.value == "inconclusive"
        assert _steps(after)[1:] == _steps(before)
        assert tools.calls == before_calls
        assert "zizmor" in tools.calls
        assert _exec_warnings(caplog) == before_logs

    def test_br_01_01_template_injection_in_an_action_is_fail(self, layout, tmp_path, tools) -> None:
        tools.outcomes.update(ACTION_SCENARIOS["zizmor-template-injection"])

        result = _verify(_shipped("OSPS-BR-01.01"), ACTION_REPOS[layout](tmp_path))

        assert (result.status, result.concluded_by, result.resolving_pass_index) == ("FAIL", "exec", 1)
        assert result.error_class is None

    def test_br_01_01_clean_action_passes_at_the_zizmor_step(self, layout, tmp_path, tools) -> None:
        tools.outcomes.update(ACTION_SCENARIOS["zizmor-clean"])

        result = _verify(_shipped("OSPS-BR-01.01"), ACTION_REPOS[layout](tmp_path))

        assert (result.status, result.concluded_by, result.resolving_pass_index) == ("PASS", "exec", 1)

    def test_br_01_01_zizmor_missing_is_still_error(self, layout, tmp_path, tools) -> None:
        tools.outcomes.update(ACTION_SCENARIOS["zizmor-missing"])

        result = _verify(_shipped("OSPS-BR-01.01"), ACTION_REPOS[layout](tmp_path))

        assert (result.status, result.error_class) == ("ERROR", "missing_tool")

    @pytest.mark.parametrize("control_id", ["OSPS-BR-01.02", "OSPS-AC-04.02"])
    def test_workflow_only_audits_still_warn_without_running(self, layout, control_id, tmp_path, tools, caplog) -> None:
        """excessive-permissions reads workflows only and grep reads .github/workflows/ only."""
        tools.outcomes.update(NO_WORKFLOW_TOOLS)
        caplog.set_level(logging.WARNING)

        result = _verify(_shipped(control_id), ACTION_REPOS[layout](tmp_path))

        assert (result.status, result.message, result.error_class) == ("WARN", NO_WORKFLOWS_MESSAGE, None)
        assert (result.concluded_by, result.resolving_pass_index) == (GUARD, 0)
        assert tools.calls == []
        assert _exec_warnings(caplog) == []


@pytest.mark.parametrize("path", [".github/dependabot.yml", ".pre-commit-config.yaml", ".git/x/action.yml"])
def test_br_01_01_inputs_template_injection_does_not_read_still_warn(path, tmp_path, tools, caplog) -> None:
    """zizmor may collect these, but its template-injection audit reads only workflows and actions."""
    tools.outcomes.update(NO_WORKFLOW_TOOLS)
    caplog.set_level(logging.WARNING)
    repo = _no_github(tmp_path)
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text("version: 2\n", encoding="utf-8")

    result = _verify(_shipped("OSPS-BR-01.01"), repo)

    assert (result.status, result.message, result.concluded_by) == ("WARN", NO_WORKFLOWS_OR_ACTIONS_MESSAGE, GUARD)
    assert tools.calls == []
    assert _exec_warnings(caplog) == []


def test_562_classification_is_unchanged() -> None:
    assert _classify_exec_failure(GREP_NO_DIRECTORY[2], 2, "grep") == "unexpected_exit"
    assert _classify_exec_failure(ZIZMOR_NO_INPUTS[2], 3, "zizmor") == "unexpected_exit"
