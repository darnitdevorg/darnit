"""``file_create.project_reference``: schema, plan, and apply in the executor (feature 043, T040, framework-design 4.3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from darnit.config.framework_schema import HandlerInvocation, RemediationConfig
from darnit.config.resolver import update_config_after_file_create
from darnit.remediation.executor import RemediationExecutor
from tests.conftest_helpers import snapshot

OWNER, REPO = "example-org", "example"
EMPTY = "name: repo\n"
RECORDED = "name: repo\nsecurity:\n  policy:\n    path: SECURITY.md\n"


def _config(reference: str | None = "security.policy") -> RemediationConfig:
    fields = {"project_reference": reference} if reference else {}
    return RemediationConfig(
        handlers=[HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Security\n", **fields)]
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / ".project").mkdir(parents=True)
    (path / ".project" / "project.yaml").write_text(EMPTY, encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _execute(repo: Path, config: RemediationConfig, *, dry_run: bool):
    return RemediationExecutor(local_path=str(repo), owner=OWNER, repo=REPO).execute("C-1", config, dry_run=dry_run)


def _note(result) -> dict:
    [entry] = result.details["handlers"]
    return entry["project_reference"]


@pytest.mark.unit
@pytest.mark.parametrize("reference", ["security.nope", "security", "a.b.c", 3, "dependencies.docs"])
def test_schema_rejects_a_reference_that_is_no_project_path_field(reference) -> None:
    with pytest.raises(ValidationError, match="project_reference"):
        RemediationConfig(handlers=[HandlerInvocation(handler="file_create", path="X.md", project_reference=reference)])


@pytest.mark.unit
@pytest.mark.parametrize("reference", ["security.policy", "governance.maintainers", "legal.license"])
def test_schema_accepts_project_path_fields(reference: str) -> None:
    RemediationConfig(handlers=[HandlerInvocation(handler="file_create", path="X.md", project_reference=reference)])


@pytest.mark.integration
def test_preview_lists_the_reference_write_and_changes_nothing(repo: Path) -> None:
    before = snapshot(repo)

    result = _execute(repo, _config(), dry_run=True)

    assert snapshot(repo) == before
    [item] = result.plan
    assert [(c.path, c.action) for c in item.file_changes] == [("SECURITY.md", "create"), (".project/project.yaml", "modify")]
    assert item.file_changes[1].content == RECORDED


@pytest.mark.integration
def test_apply_records_the_reference_through_the_run_manifest(repo: Path) -> None:
    result = _execute(repo, _config(), dry_run=False)

    assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == RECORDED
    assert [c.path for c in result.file_changes] == ["SECURITY.md", ".project/project.yaml"]
    assert _note(result) == {"reference": "security.policy", "path": "SECURITY.md", "recorded": True}


@pytest.mark.integration
def test_a_project_file_with_user_changes_is_not_written(repo: Path) -> None:
    edited = "name: repo  # local edit\n"
    (repo / ".project" / "project.yaml").write_text(edited, encoding="utf-8")

    result = _execute(repo, _config(), dry_run=False)

    assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == edited
    assert _note(result)["recorded"] is False
    assert "uncommitted changes" in _note(result)["reason"]


@pytest.mark.integration
def test_an_equal_reference_needs_no_write(repo: Path) -> None:
    (repo / ".project" / "project.yaml").write_text(RECORDED, encoding="utf-8")
    subprocess.run(["git", "commit", "-q", "-am", "policy"], cwd=repo, check=True)

    result = _execute(repo, _config(), dry_run=False)

    assert [c.path for c in result.file_changes] == ["SECURITY.md"]
    assert _note(result)["recorded"] is True


@pytest.mark.integration
def test_no_declaration_records_nothing(repo: Path) -> None:
    result = _execute(repo, _config(None), dry_run=False)

    assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == EMPTY
    assert [c.path for c in result.file_changes] == ["SECURITY.md"]


@pytest.mark.unit
def test_file_reference_sync_keeps_a_different_existing_reference(tmp_path: Path) -> None:
    (tmp_path / ".project").mkdir()
    existing = "name: repo\nsecurity:\n  policy:\n    path: docs/SECURITY.md\n"
    (tmp_path / ".project" / "project.yaml").write_text(existing, encoding="utf-8")

    assert update_config_after_file_create(str(tmp_path), "C-1", "SECURITY.md", {"C-1": "security.policy"}) is False
    assert (tmp_path / ".project" / "project.yaml").read_text(encoding="utf-8") == existing
