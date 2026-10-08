"""A user-authored project file is never destroyed (feature 042, US6, FR-019, FR-020, SC-005)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from darnit.config.framework_schema import HandlerInvocation, ProjectUpdateRemediationConfig
from darnit.config.framework_schema import RemediationConfig as RemediationSpec
from darnit.config.resolver import update_config_after_file_create
from darnit.remediation.executor import RemediationExecutor, plan_project_update
from darnit.server.tools.project_data import confirm_project_data_impl
from darnit_baseline.tools import audit_openssf_baseline

from .conftest import assert_unchanged, snapshot, write_operator_config

OWNER = "example-org"
POLICY = {"OSPS-VM-02.01": "security.policy"}

UNPARSEABLE_DARNIT_YAML = """\
# Claims maintained by hand.
controls:
  OSPS-BR-02.01:
    status: n/a
    reason: [No releases yet
"""

HAND_WRITTEN_PROJECT_YAML = """\
# Maintained by hand. Keep this comment.
name: hand-project  # the project's name
description: Written by hand
repositories:
  - https://github.com/example-org/hand
x-local-notes: keep me
security:
  contact: security@hand.example.net  # the security team
governance:
  maintainers:
    path: MAINTAINERS.md
# closing comment
"""

HAND_WRITTEN_WITH_POLICY = """\
# Maintained by hand. Keep this comment.
name: hand-project  # the project's name
description: Written by hand
repositories:
  - https://github.com/example-org/hand
x-local-notes: keep me
security:
  contact: security@hand.example.net  # the security team
  policy:
    path: SECURITY.md
governance:
  maintainers:
    path: MAINTAINERS.md
# closing comment
"""

HAND_WRITTEN_DARNIT_YAML = """\
# Claims maintained by hand.
controls:
  OSPS-BR-02.01:
    status: n/a
    reason: No releases yet  # until 1.0
    asserted_by: '@maintainer'
"""


def _invalid_project_file(repo: Path) -> Path:
    return repo


def _unparseable_extension_file(repo: Path) -> Path:
    (repo / ".project" / "darnit.yaml").write_text(UNPARSEABLE_DARNIT_YAML, encoding="utf-8")
    return repo


INVALID = {
    "R-hand": ("R-hand", _invalid_project_file, "maturity_log"),
    "unparseable darnit.yaml": ("R-legacy", _unparseable_extension_file, "darnit.yaml: unreadable"),
}


@pytest.fixture(params=list(INVALID))
def invalid_repo(request: pytest.FixtureRequest, scratch_repo: Callable[[str], Path]) -> tuple[Path, str]:
    name, prepare, error = INVALID[request.param]
    return prepare(scratch_repo(name)), error


def _identity(repo: Path) -> str:
    return f"github.com/{OWNER}/{repo.name.lower()}"


def _hand_written(tmp_path: Path) -> Path:
    repo = tmp_path / "hand"
    (repo / ".project").mkdir(parents=True)
    (repo / ".project" / "project.yaml").write_text(HAND_WRITTEN_PROJECT_YAML, encoding="utf-8")
    (repo / ".project" / "darnit.yaml").write_text(HAND_WRITTEN_DARNIT_YAML, encoding="utf-8")
    return repo


@pytest.mark.integration
class TestInvalidFilesAreNotWritten:
    def test_audit_leaves_the_files_and_reports_the_errors(self, invalid_repo: tuple[Path, str]) -> None:
        repo, error = invalid_repo
        before = snapshot(repo)

        payload = audit_openssf_baseline(local_path=str(repo), level=1, output_format="json")
        markdown = audit_openssf_baseline(local_path=str(repo), level=1)

        assert_unchanged(repo, before)
        warnings = json.loads(payload[payload.index("{") :]).get("warnings", [])
        assert any(error in warning for warning in warnings), warnings
        assert error in markdown

    @pytest.mark.parametrize("trusted", [True, False])
    def test_confirmation_is_refused_with_the_errors(
        self, invalid_repo: tuple[Path, str], tmp_path: Path, trusted: bool
    ) -> None:
        repo, error = invalid_repo
        write_operator_config(tmp_path / "operator.toml", trusted=[_identity(repo)] if trusted else [])
        before = snapshot(repo)

        message = confirm_project_data_impl(
            local_path=str(repo),
            framework_name="openssf-baseline",
            owner=OWNER,
            repo=repo.name.lower(),
            governance_model="bdfl",
        )

        assert_unchanged(repo, before)
        assert "governance_model: refused" in message
        assert error in message

    def test_review_rejection_is_refused(self, invalid_repo: tuple[Path, str], tmp_path: Path) -> None:
        repo, error = invalid_repo
        write_operator_config(tmp_path / "operator.toml", trusted=[_identity(repo)])
        before = snapshot(repo)

        message = confirm_project_data_impl(
            local_path=str(repo),
            framework_name="openssf-baseline",
            owner=OWNER,
            repo=repo.name.lower(),
            reject_stored=["maintainers"],
        )

        assert_unchanged(repo, before)
        assert "maintainers: refused" in message

    def test_project_update_is_refused_with_the_errors(self, invalid_repo: tuple[Path, str]) -> None:
        repo, error = invalid_repo
        before = snapshot(repo)

        with pytest.raises(ValueError, match=error):
            plan_project_update(str(repo), {"security.policy.path": "SECURITY.md"})

        assert_unchanged(repo, before)

    def test_applied_remediation_reports_the_refused_update(self, invalid_repo: tuple[Path, str]) -> None:
        repo, error = invalid_repo
        project_files = {p: d for p, d in snapshot(repo).items() if p.startswith(".project")}
        spec = RemediationSpec(
            handlers=[HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Security\n")],
            project_update=ProjectUpdateRemediationConfig(set={"security.policy.path": "SECURITY.md"}),
        )

        result = RemediationExecutor(local_path=str(repo), owner=OWNER, repo=repo.name).execute(
            "TEST-01", spec, dry_run=False
        )

        assert result.details["project_update"].startswith("failed:")
        assert error in result.details["project_update"]
        assert {p: d for p, d in snapshot(repo).items() if p.startswith(".project")} == project_files

    def test_file_reference_sync_is_refused(self, invalid_repo: tuple[Path, str]) -> None:
        repo, _ = invalid_repo
        (repo / "SECURITY.md").write_text("# Security\n", encoding="utf-8")
        before = snapshot(repo)

        assert update_config_after_file_create(str(repo), "OSPS-VM-02.01", "SECURITY.md", POLICY) is False
        assert_unchanged(repo, before)


def _apply_update(repo: Path, updates: dict) -> object:
    spec = RemediationSpec(handlers=[HandlerInvocation(handler="project_update", updates=updates)])
    return RemediationExecutor(local_path=str(repo), owner=OWNER, repo="hand").execute("T", spec, dry_run=False)


@pytest.mark.unit
class TestTargetedFieldsOnly:
    def test_applied_remediation_changes_only_the_targeted_field(self, tmp_path: Path) -> None:
        repo = _hand_written(tmp_path)
        spec = RemediationSpec(
            handlers=[HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Security\n")],
            project_update=ProjectUpdateRemediationConfig(set={"security.policy.path": "SECURITY.md"}),
        )

        result = RemediationExecutor(local_path=str(repo), owner=OWNER, repo="hand").execute(
            "TEST-01", spec, dry_run=False
        )

        assert result.details["project_update"] == "applied"
        assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == HAND_WRITTEN_WITH_POLICY
        assert (repo / ".project" / "darnit.yaml").read_text(encoding="utf-8") == HAND_WRITTEN_DARNIT_YAML

    def test_a_string_value_is_written_as_a_path_reference(self, tmp_path: Path) -> None:
        repo = _hand_written(tmp_path)

        assert _apply_update(repo, {"security.policy": "SECURITY.md"}).changed

        assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == HAND_WRITTEN_WITH_POLICY

    def test_file_reference_sync_changes_only_the_targeted_field(self, tmp_path: Path) -> None:
        repo = _hand_written(tmp_path)

        assert update_config_after_file_create(str(repo), "OSPS-VM-02.01", "SECURITY.md", POLICY) is True

        assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == HAND_WRITTEN_WITH_POLICY
        assert (repo / ".project" / "darnit.yaml").read_text(encoding="utf-8") == HAND_WRITTEN_DARNIT_YAML

    def test_an_absent_project_directory_gets_only_what_is_needed(self, tmp_path: Path) -> None:
        assert _apply_update(tmp_path, {"security.policy.path": "SECURITY.md"}).changed

        assert sorted(p.name for p in (tmp_path / ".project").iterdir()) == ["project.yaml"]
        assert yaml.safe_load((tmp_path / ".project" / "project.yaml").read_text(encoding="utf-8")) == {
            "name": tmp_path.name,
            "security": {"policy": {"path": "SECURITY.md"}},
        }


@pytest.mark.unit
def test_no_product_code_rewrites_whole_project_files() -> None:
    import ast

    packages = Path(__file__).resolve().parents[3] / "packages"
    callers = sorted(
        path.relative_to(packages).as_posix()
        for path in packages.glob("*/src/**/*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", None)) == "save_project_config"
    )

    assert callers == []
