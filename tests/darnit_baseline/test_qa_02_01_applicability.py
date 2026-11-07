"""OSPS-QA-02.01 applies only when the project's package manager supports a dependency list.

Baseline requires the dependency list "when the package management system
supports it", so a script-only project has nothing to list (issue #308). The
control must be skipped on positive evidence of that, and must still run, and
can FAIL, whenever darnit cannot tell.
"""

import tomllib
from importlib.resources import files

import pytest

from darnit.config.when_evaluator import evaluate_when
from darnit.context.auto_detect import collect_auto_context
from darnit.tools.audit import calculate_compliance


def _qa_02_01_when() -> dict:
    toml_path = files("darnit_baseline") / "openssf-baseline.toml"
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    return data["controls"]["OSPS-QA-02.01"]["when"]


def _applies(repo) -> bool:
    context = collect_auto_context(str(repo), include_stored=False)
    return evaluate_when(_qa_02_01_when(), context)


class TestQA0201Applicability:
    def test_script_only_project_is_not_applicable(self, tmp_path):
        (tmp_path / "run.sh").write_text("echo hi")
        assert _applies(tmp_path) is False

    def test_project_with_manifest_is_checked(self, tmp_path):
        (tmp_path / "run.sh").write_text("echo hi")
        (tmp_path / "package.json").write_text("{}")
        assert _applies(tmp_path) is True

    def test_package_managed_project_missing_its_manifest_is_still_checked(self, tmp_path):
        (tmp_path / "run.sh").write_text("echo hi")
        (tmp_path / "index.js").write_text("console.log(1)")
        assert _applies(tmp_path) is True

    @pytest.mark.parametrize(
        "files_in_repo",
        [
            [],  # empty repository
            ["README.md"],  # no code at all
            ["run.sh", "main.c"],  # a language darnit does not classify
        ],
    )
    def test_uncertain_project_is_still_checked(self, tmp_path, files_in_repo):
        for name in files_in_repo:
            (tmp_path / name).write_text("x")
        assert _applies(tmp_path) is True


class TestNotApplicableDoesNotBlockLevel:
    def test_na_control_is_excluded_from_level_one(self):
        results = [
            {"id": "OSPS-QA-02.01", "status": "N/A", "level": 1},
            {"id": "OSPS-QA-01.01", "status": "PASS", "level": 1},
        ]
        assert calculate_compliance(results, level=1) == {1: True}

    def test_failed_control_still_blocks_level_one(self):
        results = [
            {"id": "OSPS-QA-02.01", "status": "FAIL", "level": 1},
            {"id": "OSPS-QA-01.01", "status": "PASS", "level": 1},
        ]
        assert calculate_compliance(results, level=1) == {1: False}
