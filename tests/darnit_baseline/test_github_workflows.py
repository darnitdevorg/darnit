"""The ``github_workflows_present`` step type (#584).

WARN with a reason when ``.github/workflows/`` holds no ``.yml``/``.yaml``
file inside the repository (and, with ``actions = true``, the repository
holds no ``action.yml``/``action.yaml``), INCONCLUSIVE otherwise; never PASS
or FAIL.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from darnit.config import load_framework_config
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResultStatus,
    get_sieve_handler_registry,
    reset_sieve_handler_registry,
)
from darnit_baseline.github_workflows import (
    NO_WORKFLOWS_MESSAGE,
    NO_WORKFLOWS_OR_ACTIONS_MESSAGE,
    github_workflows_present_handler,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_TOML = REPO_ROOT / "packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml"
WORKFLOW_CONTROLS = ("OSPS-BR-01.01", "OSPS-BR-01.02", "OSPS-AC-04.02")
ACTIONS = {"actions": True}


def _run(repo: Path, config: dict | None = None):
    ctx = HandlerContext(local_path=str(repo), owner="o", repo="r", default_branch="main", control_id="TEST-01")
    return github_workflows_present_handler(dict(config or {}), ctx)


def _write(path: Path, text: str = "runs:\n  using: composite\n  steps: []\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _workflows(repo: Path) -> Path:
    path = repo / ".github" / "workflows"
    path.mkdir(parents=True)
    return path


class TestNoWorkflowFiles:
    def test_no_github_directory(self, tmp_path: Path) -> None:
        result = _run(tmp_path)

        assert result.status == HandlerResultStatus.WARN
        assert result.message == NO_WORKFLOWS_MESSAGE
        assert result.error_class is None
        assert result.evidence["workflow_files"] == []

    def test_empty_workflows_directory(self, tmp_path: Path) -> None:
        _workflows(tmp_path)

        assert _run(tmp_path).status == HandlerResultStatus.WARN

    def test_workflows_directory_without_yaml_files(self, tmp_path: Path) -> None:
        workflows = _workflows(tmp_path)
        (workflows / "README.md").write_text("no workflows\n", encoding="utf-8")
        (workflows / "ci.yml.disabled").write_text("on: push\n", encoding="utf-8")
        (workflows / "nested.yml").mkdir()

        result = _run(tmp_path)

        assert result.status == HandlerResultStatus.WARN
        assert result.evidence["workflow_files"] == []

    def test_workflows_path_is_a_file(self, tmp_path: Path) -> None:
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "workflows").write_text("not a directory\n", encoding="utf-8")

        assert _run(tmp_path).status == HandlerResultStatus.WARN

    def test_yaml_only_in_a_subdirectory_does_not_count(self, tmp_path: Path) -> None:
        nested = _workflows(tmp_path) / "archive"
        nested.mkdir()
        (nested / "old.yml").write_text("on: push\n", encoding="utf-8")

        assert _run(tmp_path).status == HandlerResultStatus.WARN

    def test_message_says_nothing_to_audit(self) -> None:
        assert "No GitHub Actions workflow files" in NO_WORKFLOWS_MESSAGE
        assert "nothing to audit" in NO_WORKFLOWS_MESSAGE


class TestWorkflowFilesPresent:
    @pytest.mark.parametrize("name", ["ci.yml", "ci.yaml", "Release.YML"])
    def test_workflow_file_is_evidence_only(self, tmp_path: Path, name: str) -> None:
        (_workflows(tmp_path) / name).write_text("on: push\n", encoding="utf-8")

        result = _run(tmp_path)

        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.error_class is None
        assert result.evidence["workflow_files"] == [f".github/workflows/{name}"]

    def test_lists_every_workflow_file(self, tmp_path: Path) -> None:
        workflows = _workflows(tmp_path)
        for name in ("b.yaml", "a.yml", "notes.txt"):
            (workflows / name).write_text("on: push\n", encoding="utf-8")

        result = _run(tmp_path)

        assert result.evidence["workflow_files"] == [".github/workflows/a.yml", ".github/workflows/b.yaml"]


class TestRepositoryBoundary:
    def test_workflow_linked_outside_the_repository_does_not_count(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.yml"
        outside.write_text("on: push\n", encoding="utf-8")
        repo = tmp_path / "repo"
        workflows = _workflows(repo)
        try:
            os.symlink(outside, workflows / "ci.yml")
        except (OSError, NotImplementedError):
            pytest.skip("symbolic links are not available")

        result = _run(repo)

        assert result.status == HandlerResultStatus.WARN
        assert result.evidence["skipped_outside_repository"] == [".github/workflows/ci.yml"]

    def test_action_linked_outside_the_repository_does_not_count(self, tmp_path: Path) -> None:
        outside = _write(tmp_path / "outside" / "action.yml")
        repo = tmp_path / "repo"
        repo.mkdir()
        try:
            os.symlink(outside, repo / "action.yml")
        except (OSError, NotImplementedError):
            pytest.skip("symbolic links are not available")

        result = _run(repo, ACTIONS)

        assert result.status == HandlerResultStatus.WARN
        assert result.evidence["skipped_outside_repository"] == ["action.yml"]


class TestActionDefinitions:
    """``actions = true``: an action definition is something zizmor's template-injection audit reads."""

    @pytest.mark.parametrize(
        "path", ["action.yml", "action.yaml", ".github/actions/setup/action.yml", "tools/greet/action.yaml"]
    )
    def test_action_definition_is_evidence_only(self, tmp_path: Path, path: str) -> None:
        _write(tmp_path / path)

        result = _run(tmp_path, ACTIONS)

        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.error_class is None
        assert result.evidence["workflow_files"] == []
        assert result.evidence["action_files"] == [path]

    def test_with_empty_workflows_directory(self, tmp_path: Path) -> None:
        _workflows(tmp_path)
        _write(tmp_path / "action.yml")

        assert _run(tmp_path, ACTIONS).status == HandlerResultStatus.INCONCLUSIVE

    def test_without_the_setting_action_definitions_do_not_count(self, tmp_path: Path) -> None:
        _write(tmp_path / "action.yml")

        result = _run(tmp_path)

        assert (result.status, result.message) == (HandlerResultStatus.WARN, NO_WORKFLOWS_MESSAGE)
        assert "action_files" not in result.evidence

    @pytest.mark.parametrize("value", [False, "true", 1])
    def test_only_true_enables_the_setting(self, tmp_path: Path, value) -> None:
        _write(tmp_path / "action.yml")

        assert _run(tmp_path, {"actions": value}).status == HandlerResultStatus.WARN

    def test_nothing_to_audit_names_both_inputs(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# example\n", encoding="utf-8")

        result = _run(tmp_path, ACTIONS)

        assert (result.status, result.message) == (HandlerResultStatus.WARN, NO_WORKFLOWS_OR_ACTIONS_MESSAGE)
        assert result.error_class is None
        assert "nothing to audit" in NO_WORKFLOWS_OR_ACTIONS_MESSAGE

    @pytest.mark.parametrize(
        "path",
        [".github/dependabot.yml", ".pre-commit-config.yaml", ".pre-commit-hooks.yaml", "actions.yml", "my-action.yml"],
    )
    def test_other_files_do_not_count(self, tmp_path: Path, path: str) -> None:
        _write(tmp_path / path)

        assert _run(tmp_path, ACTIONS).status == HandlerResultStatus.WARN

    def test_git_directory_is_not_searched(self, tmp_path: Path) -> None:
        _write(tmp_path / ".git" / "modules" / "vendored" / "action.yml")

        assert _run(tmp_path, ACTIONS).status == HandlerResultStatus.WARN

    def test_directory_named_action_yml_does_not_count(self, tmp_path: Path) -> None:
        (tmp_path / "action.yml").mkdir()

        assert _run(tmp_path, ACTIONS).status == HandlerResultStatus.WARN

    def test_workflows_are_reported_without_searching_for_actions(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "ci.yml").write_text("on: push\n", encoding="utf-8")
        _write(tmp_path / "action.yml")

        result = _run(tmp_path, ACTIONS)

        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["workflow_files"] == [".github/workflows/ci.yml"]
        assert "action_files" not in result.evidence


class TestNeverPassOrFail:
    @pytest.mark.parametrize("config", [{}, ACTIONS])
    @pytest.mark.parametrize("files", [[], ["README.md"], ["ci.yml"], ["ci.yaml", "x.txt"], ["action.yml"]])
    def test_outcome_is_warn_or_inconclusive(self, tmp_path: Path, files: list[str], config: dict) -> None:
        workflows = _workflows(tmp_path)
        for name in files:
            (workflows / name).write_text("on: push\n", encoding="utf-8")

        assert _run(tmp_path, config).status in (HandlerResultStatus.WARN, HandlerResultStatus.INCONCLUSIVE)


class TestRegistration:
    @pytest.fixture(autouse=True)
    def _registered(self):
        reset_sieve_handler_registry()
        from darnit.core.discovery import get_implementation

        impl = get_implementation("openssf-baseline")
        assert impl is not None
        impl.register_handlers()

    def test_ceiling_is_fail_only(self) -> None:
        info = get_sieve_handler_registry().get("github_workflows_present")

        assert info is not None
        assert set(info.ceiling) == {"fail"}
        assert info.existence_ceiling is None
        assert set(info.settings) == {"actions"}


class TestShippedSteps:
    @pytest.fixture(scope="class")
    def controls(self):
        return load_framework_config(BASELINE_TOML).controls

    @pytest.mark.parametrize("control_id", WORKFLOW_CONTROLS)
    def test_step_runs_first(self, controls, control_id: str) -> None:
        handlers = [step.handler for step in controls[control_id].passes]

        assert handlers[:2] == ["github_workflows_present", "exec"]
        assert handlers.count("github_workflows_present") == 1
        assert handlers[-1] == "manual"

    @pytest.mark.parametrize(
        ("control_id", "settings"),
        [("OSPS-BR-01.01", ACTIONS), ("OSPS-BR-01.02", {}), ("OSPS-AC-04.02", {})],
    )
    def test_only_br_01_01_counts_action_definitions(self, controls, control_id: str, settings: dict) -> None:
        """BR-01.01's zizmor audit (template-injection) reads actions; AC-04.02's (excessive-permissions)
        and BR-01.02's grep of .github/workflows/ do not."""
        step = controls[control_id].passes[0]

        assert step.model_extra == settings
        assert (step.concludes, step.existence, step.promotion, step.when) == (None, False, None, None)

    def test_no_other_control_uses_it(self, controls) -> None:
        using = sorted(
            cid
            for cid, control in controls.items()
            if any(s.handler == "github_workflows_present" for s in control.passes)
        )

        assert using == sorted(WORKFLOW_CONTROLS)

    def test_br_01_02_grep_step_is_unchanged(self, controls) -> None:
        """#647 stays out of scope: the grep step keeps its exit-code mapping."""
        (grep,) = [s for s in controls["OSPS-BR-01.02"].passes if s.handler == "exec"]

        assert grep.model_extra["command"] == ["grep", "-rln", "github.head_ref", ".github/workflows/"]
        assert grep.model_extra["pass_exit_codes"] == [1]
        assert "fail_exit_codes" not in grep.model_extra
        assert grep.concludes == []
