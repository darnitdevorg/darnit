"""A step's expression decides or the step is an error (feature 044, US1, framework-design 3.7).

When an expression cannot be evaluated, or is not boolean, the step is a
broken measurement (ERROR, class ``evaluation``) whatever its handler
returned (FR-001). Expressions see the step's output, the usable project
values, and a ``file_exists`` that answers for the audited repository
(FR-002).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from darnit.config import load_framework_config
from darnit.config.context_keys import value_digest
from darnit.config.control_loader import control_from_framework, validate_step_authority
from darnit.config.framework_schema import HandlerInvocation
from darnit.config.operator.schema import OperatorConfig
from darnit.core.errors import AuthorityViolation
from darnit.sieve.handler_registry import HandlerResult, HandlerResultStatus
from darnit.sieve.models import CheckContext, ControlSpec, SieveResult
from darnit.sieve.orchestrator import SieveOrchestrator, _apply_cel_expr
from darnit.tools.audit import _resolve_audit_context
from tests.conftest_helpers import stand_in_tool

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_TOML = REPO_ROOT / "packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml"
CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")

WORKFLOW = """\
name: ci
on: push
permissions: read-all
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""

ZIZMOR_CONTROLS = {
    "OSPS-BR-01.01": "template-injection",
    "OSPS-AC-04.02": "excessive-permissions",
}


def _context(repo: Path, control_id: str, project: dict[str, Any] | None = None) -> CheckContext:
    return CheckContext(
        owner="example-org",
        repo="example",
        local_path=str(repo),
        default_branch="main",
        control_id=control_id,
        usable_project=dict(project or {}),
    )


def _verify(spec: ControlSpec, repo: Path, project: dict[str, Any] | None = None) -> SieveResult:
    return SieveOrchestrator(stop_on_llm=False).verify(spec, _context(repo, spec.control_id, project))


def _shipped(control_id: str) -> ControlSpec:
    framework = load_framework_config(BASELINE_TOML)
    return control_from_framework(
        control_id, framework.controls[control_id].model_copy(deep=True), framework=framework.metadata.name
    )


def _step_control(**step: Any) -> ControlSpec:
    return ControlSpec(
        control_id="TEST-EXPR-01",
        level=1,
        domain="TEST",
        name="Expression",
        description="A single step with an expression",
        metadata={"handler_invocations": [HandlerInvocation(**step)]},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    (root / "README.md").write_text("# example\n", encoding="utf-8")
    return root


@pytest.fixture
def zizmor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def install(stdout: str = "", exit_code: int = 0) -> None:
        stand_in_tool(monkeypatch, bin_dir, "zizmor", stdout=stdout, exit_code=exit_code)

    return install


@pytest.mark.unit
class TestShippedZizmorControls:
    """SC-001: the #479 reproduction for OSPS-BR-01.01 and OSPS-AC-04.02."""

    @pytest.mark.parametrize("control_id", sorted(ZIZMOR_CONTROLS))
    def test_no_findings_document_is_error(self, control_id: str, repo: Path, zizmor) -> None:
        zizmor(stdout="", exit_code=0)

        result = _verify(_shipped(control_id), repo)

        assert result.status == "ERROR"
        assert result.error["class"] == "evaluation"
        assert result.resolving_pass_index == 0
        first = result.pass_history[0].result
        assert first.outcome.value == "error"
        assert first.evidence["expr"].startswith("!output.json.exists")
        assert first.evidence["expr_error"]

    @pytest.mark.parametrize("control_id", sorted(ZIZMOR_CONTROLS))
    def test_matching_finding_is_fail(self, control_id: str, repo: Path, zizmor) -> None:
        # zizmor exits in pass_exit_codes for findings of any kind, so the
        # handler PASSes; the step sets expr_decides, so the false expression
        # is FAIL (FR-015, framework-design 3.7).
        zizmor(stdout=json.dumps([{"ident": ZIZMOR_CONTROLS[control_id]}]), exit_code=14)

        result = _verify(_shipped(control_id), repo)

        assert result.status == "FAIL"
        assert result.resolving_pass_index == 0
        assert result.pass_history[0].result.evidence["json"] == [{"ident": ZIZMOR_CONTROLS[control_id]}]

    @pytest.mark.parametrize("control_id", sorted(ZIZMOR_CONTROLS))
    def test_other_findings_are_pass(self, control_id: str, repo: Path, zizmor) -> None:
        zizmor(stdout=json.dumps([{"ident": "unpinned-uses"}]), exit_code=13)

        result = _verify(_shipped(control_id), repo)

        assert result.status == "PASS"

    @pytest.mark.parametrize("control_id", sorted(ZIZMOR_CONTROLS))
    def test_no_matching_finding_is_pass(self, control_id: str, repo: Path, zizmor) -> None:
        zizmor(stdout="[]", exit_code=0)

        result = _verify(_shipped(control_id), repo)

        assert result.status == "PASS"
        assert result.concluded_by == "exec"


@pytest.mark.unit
class TestEvaluationFailure:
    """FR-001: the handler's verdict never stands on a broken expression."""

    def test_handler_pass_with_evaluation_error_is_error(self) -> None:
        handler = HandlerResult(status=HandlerResultStatus.PASS, message="ok", evidence={"exit_code": 0})

        result = _apply_cel_expr({"handler": "exec", "expr": "output.json.x == 1"}, handler)

        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"
        assert result.evidence["exit_code"] == 0
        assert result.evidence["expr"] == "output.json.x == 1"
        assert result.evidence["expr_error"]

    def test_handler_fail_with_evaluation_error_is_error(self) -> None:
        handler = HandlerResult(status=HandlerResultStatus.FAIL, message="no", evidence={"exit_code": 1})

        result = _apply_cel_expr({"handler": "exec", "expr": "output.json.x == 1"}, handler)

        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"

    @pytest.mark.parametrize("expr", ["output.stdout", "output.exit_code", "[output.exit_code == 0]"])
    def test_non_boolean_is_error(self, expr: str) -> None:
        handler = HandlerResult(
            status=HandlerResultStatus.PASS, message="ok", evidence={"exit_code": 0, "stdout": "true"}
        )

        result = _apply_cel_expr({"handler": "exec", "expr": expr}, handler)

        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"

    def test_compile_error_is_error(self) -> None:
        handler = HandlerResult(status=HandlerResultStatus.PASS, message="ok", evidence={})

        result = _apply_cel_expr({"handler": "exec", "expr": "output.(("}, handler)

        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"

    def test_broken_expression_does_not_conclude_the_control(self, repo: Path) -> None:
        spec = _step_control(handler="exec", command=["true"], expr="output.json.x == 1")

        result = _verify(spec, repo)

        assert result.status == "ERROR"
        assert result.error["class"] == "evaluation"
        assert result.concluded_by == "exec"
        assert result.authority != "asserted"

    def test_later_step_still_runs_after_a_broken_expression(self, repo: Path) -> None:
        spec = ControlSpec(
            control_id="TEST-EXPR-02",
            level=1,
            domain="TEST",
            name="Expression",
            description="A broken expression, then a step that concludes",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="exec", command=["true"], expr="output.json.x == 1"),
                    HandlerInvocation(handler="exec", command=["false"], fail_exit_codes=[1]),
                ]
            },
        )

        result = _verify(spec, repo)

        assert result.status == "FAIL"
        assert result.resolving_pass_index == 1


@pytest.mark.unit
class TestExpressionNames:
    """FR-002: usable project values and a repository-aware file_exists."""

    def test_file_exists_answers_for_the_audited_repository(self, repo: Path) -> None:
        spec = _step_control(handler="exec", command=["true"], expr='file_exists("README.md")')

        assert _verify(spec, repo).status == "PASS"

    def test_file_exists_is_false_for_a_missing_file(self, repo: Path) -> None:
        spec = _step_control(handler="exec", command=["true"], expr='file_exists("MISSING.md")')

        assert _verify(spec, repo).status == "WARN"

    def test_project_value_is_visible(self, repo: Path) -> None:
        spec = _step_control(handler="exec", command=["true"], expr='project.ci_provider == "github"')

        assert _verify(spec, repo, {"ci_provider": "github"}).status == "PASS"

    def test_absent_project_value_is_an_evaluation_error(self, repo: Path) -> None:
        spec = _step_control(handler="exec", command=["true"], expr='project.ci_provider == "github"')

        result = _verify(spec, repo, {})

        assert result.status == "ERROR"
        assert result.error["class"] == "evaluation"


@pytest.mark.unit
class TestExprDecides:
    """FR-015: with expr_decides the expression alone decides on a handler PASS."""

    def _apply(self, status: HandlerResultStatus, expr: str = "output.exit_code == 0") -> HandlerResult:
        handler = HandlerResult(status=status, message="handler", evidence={"exit_code": 0})
        return _apply_cel_expr({"handler": "exec", "expr": expr}, handler, decides=True)

    def test_true_is_pass(self) -> None:
        assert self._apply(HandlerResultStatus.PASS).status == HandlerResultStatus.PASS

    def test_false_is_fail(self) -> None:
        result = self._apply(HandlerResultStatus.PASS, "output.exit_code == 1")

        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["expr"] == "output.exit_code == 1"

    def test_evaluation_error_is_error(self) -> None:
        result = self._apply(HandlerResultStatus.PASS, "output.json.x == 1")

        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"

    @pytest.mark.parametrize(
        "status",
        [
            HandlerResultStatus.FAIL,
            HandlerResultStatus.WARN,
            HandlerResultStatus.INCONCLUSIVE,
            HandlerResultStatus.ERROR,
        ],
    )
    def test_other_handler_results_are_unchanged(self, status: HandlerResultStatus) -> None:
        assert self._apply(status, "output.json.x == 1").status == status

    def test_fail_concludes_only_within_the_effective_set(self, repo: Path) -> None:
        spec = _step_control(
            handler="exec", command=["true"], expr="output.exit_code == 1", expr_decides=True, concludes=["pass"]
        )

        result = _verify(spec, repo)

        assert result.status != "FAIL"
        assert result.pass_history[0].result.outcome.value == "fail"

    @pytest.mark.parametrize(
        ("step", "message"),
        [
            ({"handler": "file_exists", "files": ["README.md"]}, "does not accept expr"),
            ({"handler": "exec", "command": ["true"]}, "has no expr"),
            ({"handler": "gh_api", "endpoint": "/repos/o/r", "expr": "response.body.private"}, "already decides"),
        ],
    )
    def test_invalid_use_fails_loading(self, step: dict[str, Any], message: str) -> None:
        with pytest.raises(AuthorityViolation) as excinfo:
            validate_step_authority("expr-fw", "EXPR-01", [HandlerInvocation(**step, expr_decides=True)])

        text = str(excinfo.value)
        for fragment in ("EXPR-01", f"pass[0]:{step['handler']}", message):
            assert fragment in text, (fragment, text)

    def test_shipped_zizmor_steps_declare_it(self) -> None:
        for control_id in ZIZMOR_CONTROLS:
            assert _shipped(control_id).metadata["handler_invocations"][0].expr_decides is True


def _write_project(repo: Path, darnit: dict[str, Any]) -> None:
    (repo / ".project").mkdir()
    (repo / ".project" / "project.yaml").write_text("name: example\n", encoding="utf-8")
    (repo / ".project" / "darnit.yaml").write_text(yaml.safe_dump(darnit), encoding="utf-8")


@pytest.mark.unit
class TestProjectStanding:
    """US1 scenario 4: an expression sees a project value only once it is usable (042)."""

    EXPR = 'project.ci_provider == "github"'

    @pytest.fixture(autouse=True)
    def _no_ci_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in CI_VARS:
            monkeypatch.delenv(var, raising=False)

    @pytest.fixture
    def bare_repo(self, tmp_path: Path) -> Path:
        root = tmp_path / "bare"
        root.mkdir()
        return root

    def _project_context(self, repo: Path) -> dict[str, Any]:
        operator = OperatorConfig.model_validate({"schema_version": 1})
        return _resolve_audit_context(str(repo), operator=operator).usable()

    def test_confirmed_value_evaluates(self, bare_repo: Path) -> None:
        _write_project(
            bare_repo,
            {
                "context": {"ci_provider": "github"},
                "confirmations": {
                    "ci_provider": {
                        "value_digest": value_digest("ci_provider", "github"),
                        "confirmed_by": "alice",
                        "confirmed_at": "2026-09-01T00:00:00Z",
                        "last_validated": "2026-09-01T00:00:00Z",
                    }
                },
            },
        )
        spec = _step_control(handler="exec", command=["true"], expr=self.EXPR)

        result = _verify(spec, bare_repo, self._project_context(bare_repo))

        assert result.status == "PASS"

    def test_candidate_value_is_an_evaluation_error(self, bare_repo: Path) -> None:
        _write_project(bare_repo, {"context": {"ci_provider": "github"}})
        spec = _step_control(handler="exec", command=["true"], expr=self.EXPR)

        result = _verify(spec, bare_repo, self._project_context(bare_repo))

        assert result.status == "ERROR"
        assert result.error["class"] == "evaluation"


@pytest.mark.unit
class TestProjectBindingInAnAudit:
    """``project`` is the usable values only, not the when-clause context (FR-002, 044 review).

    The audit's when-clause context also merges this run's detections and the
    raw ``.project/project.yaml`` mapper values (``project.governance.maintainers``),
    which are unconfirmed. The second disjunct reads that raw key: before the
    fix it held, so the step passed on an unconfirmed value.
    """

    EXPR = 'size(project.maintainers) > 0 || size(project["project.governance.maintainers"]) > 0'
    MAINTAINERS = ["@alice"]

    @pytest.fixture(autouse=True)
    def _no_ci_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in CI_VARS:
            monkeypatch.delenv(var, raising=False)

    @pytest.fixture
    def maintained_repo(self, tmp_path: Path) -> Path:
        root = tmp_path / "maintained"
        (root / ".project").mkdir(parents=True)
        (root / ".project" / "project.yaml").write_text(
            yaml.safe_dump({"name": "example", "governance": {"maintainers": self.MAINTAINERS}}), encoding="utf-8"
        )
        return root

    def _audit(self, repo: Path) -> dict[str, Any]:
        from darnit.config.operator.loader import LoadedOperatorConfig
        from darnit.tools.audit import run_sieve_audit

        operator = LoadedOperatorConfig(
            config=OperatorConfig.model_validate({"schema_version": 1}),
            source="test",
            digest=None,
            permission_check="ok",
            strict=False,
        )
        results, _summary = run_sieve_audit(
            "example-org",
            "example",
            str(repo),
            "main",
            controls=[_step_control(handler="exec", command=["true"], expr=self.EXPR)],
            apply_user_config=False,
            stop_on_llm=False,
            framework_name="openssf-baseline",
            operator_config=operator,
            write_cache=False,
        )
        (result,) = results
        return result

    def test_unconfirmed_project_yaml_value_is_an_evaluation_error(self, maintained_repo: Path) -> None:
        result = self._audit(maintained_repo)

        assert result["status"] == "ERROR"
        assert result["error"]["class"] == "evaluation"

    def test_confirmed_value_evaluates(self, maintained_repo: Path) -> None:
        (maintained_repo / ".project" / "darnit.yaml").write_text(
            yaml.safe_dump(
                {
                    "context": {"maintainers": self.MAINTAINERS},
                    "confirmations": {
                        "maintainers": {
                            "value_digest": value_digest("maintainers", self.MAINTAINERS),
                            "confirmed_by": "alice",
                            "confirmed_at": "2026-09-01T00:00:00Z",
                            "last_validated": "2026-09-01T00:00:00Z",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        assert self._audit(maintained_repo)["status"] == "PASS"
