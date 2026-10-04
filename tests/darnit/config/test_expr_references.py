"""Load-time check of expression references (feature 044, US1 scenario 6, FR-003).

An expression may use only the names its step type provides
(``expression_names``, framework-design 3.0.3 and 3.7). A reference to
anything else, a syntax error, or an ``expr`` on a step type that accepts
none fails loading, naming the control, the step, and the reference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config import load_framework_config
from darnit.config.control_loader import validate_step_authority
from darnit.config.framework_schema import HandlerInvocation
from darnit.core.errors import AuthorityViolation
from darnit.sieve.cel_evaluator import CELCompilationError, expression_free_names

REPO_ROOT = Path(__file__).resolve().parents[3]
SHIPPED_STEP_EXPRESSIONS = 21


def _validate(**step) -> None:
    validate_step_authority("expr-fw", "EXPR-01", [HandlerInvocation(**step)])


def _shipped_tomls() -> list[Path]:
    packages = REPO_ROOT / "packages"
    nested = sorted(packages.glob("*/src/*/*.toml"))
    top = sorted(p for p in packages.glob("*/*.toml") if p.name != "pyproject.toml")
    return nested + top


@pytest.mark.unit
class TestFreeNames:
    @pytest.mark.parametrize(
        ("expr", "names"),
        [
            ("output.any_match", {"output"}),
            ('!output.json.exists(f, f.ident == "template-injection")', {"output"}),
            ("response.body.assets.exists(a, a.name.matches('x'))", {"response"}),
            ("type(response.body.license) == map && type(response.body.x) == string", {"response"}),
            ('file_exists("README.md") && json_path(output.json, "a") == 1', {"output"}),
            ("size(output.items.filter(i, i > 0).map(j, j + offset)) > 0", {"output", "offset"}),
            ("output.items.all(x, x > 0) && x", {"output", "x"}),
            ('project.ci_provider == "github"', {"project"}),
            ("has(response.body.enabled)", {"response"}),
            ('{"k": value}.k == 1', {"value"}),
        ],
    )
    def test_collects_free_names(self, expr: str, names: set[str]) -> None:
        assert expression_free_names(expr) == frozenset(names)

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(CELCompilationError):
            expression_free_names("output.((")


@pytest.mark.unit
class TestLoadTimeReferences:
    def test_name_the_step_type_does_not_provide(self) -> None:
        with pytest.raises(AuthorityViolation) as excinfo:
            _validate(handler="exec", command=["true"], expr="response.body.x == 1")

        text = str(excinfo.value)
        for fragment in ("EXPR-01", "pass[0]:exec", "'response'"):
            assert fragment in text, (fragment, text)

    def test_misspelled_name(self) -> None:
        with pytest.raises(AuthorityViolation, match="'ouput'"):
            _validate(handler="exec", command=["true"], expr="ouput.exit_code == 0")

    def test_syntax_error(self) -> None:
        with pytest.raises(AuthorityViolation, match=r"pass\[0\]:exec.*does not compile"):
            _validate(handler="exec", command=["true"], expr="output.((")

    def test_macro_bound_variable_is_accepted(self) -> None:
        _validate(handler="exec", command=["true"], output_format="json", expr='output.json.exists(f, f.ident == "x")')

    def test_project_is_accepted_on_a_post_step_expression(self) -> None:
        _validate(handler="regex", files=["README.md"], pattern="x", expr='project.ci_provider == "github"')

    def test_gh_api_names(self) -> None:
        _validate(handler="gh_api", endpoint="/repos/o/r", expr="response.body.private == false")
        with pytest.raises(AuthorityViolation, match="'output'"):
            _validate(handler="gh_api", endpoint="/repos/o/r", expr="output.exit_code == 0")

    def test_step_type_without_expression_names(self) -> None:
        with pytest.raises(AuthorityViolation, match=r"pass\[0\]:file_exists.*does not accept expr"):
            _validate(handler="file_exists", files=["README.md"], expr="output.found")


@pytest.fixture(scope="module")
def plugin_step_types() -> None:
    import importlib

    import darnit_csl.handlers
    from darnit_gittuf.implementation import GittufImplementation
    from darnit_reproducibility.implementation import ReproducibilityImplementation

    from darnit_baseline.implementation import OSPSBaselineImplementation
    from darnit_example.implementation import ExampleHygieneImplementation

    importlib.reload(darnit_csl.handlers)
    OSPSBaselineImplementation().register_handlers()
    for implementation in (ExampleHygieneImplementation, GittufImplementation, ReproducibilityImplementation):
        implementation().register_sieve_handlers()


@pytest.mark.unit
@pytest.mark.usefixtures("plugin_step_types")
def test_every_shipped_expression_loads() -> None:
    count = 0
    for path in _shipped_tomls():
        framework = load_framework_config(path)
        for control_id, control in framework.controls.items():
            steps = list(control.passes or [])
            count += sum(1 for step in steps if "expr" in (step.model_extra or {}))
            validate_step_authority(framework.metadata.name, control_id, steps)
    assert count == SHIPPED_STEP_EXPRESSIONS
