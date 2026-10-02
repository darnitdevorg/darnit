"""Plan/apply protocol and the executor as single writer (feature 043, research R6, T008)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from darnit.config.framework_schema import (
    HandlerInvocation,
    ProjectUpdateRemediationConfig,
    RemediationConfig,
)
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationExecutor
from darnit.remediation.plan import FileChange, content_digest
from darnit.sieve.handler_registry import HandlerResult, HandlerResultStatus, get_sieve_handler_registry
from tests.conftest_helpers import snapshot

OWNER, REPO = "example-org", "example"
IDENTITY = f"github.com/{OWNER}/{REPO}"

WORKFLOW = "name: ci\non:\n  push:\n\njobs:\n  build:\n    runs-on: ubuntu-latest\n"


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data" / "darnit"
    monkeypatch.setattr(manifest, "user_data_root", lambda: root)
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / ".github" / "workflows").mkdir(parents=True)
    (path / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    (path / ".github" / "workflows" / "done.yml").write_text("on: push\npermissions: {}\n", encoding="utf-8")
    (path / "EXISTING.md").write_text("mine\n", encoding="utf-8")
    return path


def _executor(repo: Path) -> RemediationExecutor:
    return RemediationExecutor(local_path=str(repo), owner=OWNER, repo=REPO)


def _config(*handlers: HandlerInvocation, **kwargs) -> RemediationConfig:
    return RemediationConfig(handlers=list(handlers), **kwargs)


FILE_CREATE = HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Security\n")
YAML_INJECT = HandlerInvocation(handler="yaml_inject", files=".github/workflows/*.yml", key="permissions", value="{}")
PROJECT_UPDATE = HandlerInvocation(handler="project_update", updates={"security.policy.path": "SECURITY.md"})


@pytest.fixture
def side_effect_handler() -> Iterator[list[str]]:
    """A plugin remediation handler that registers without ``supports_plan``."""
    calls: list[str] = []
    registry = get_sieve_handler_registry()

    def _handler(config, context):
        calls.append(context.mode)
        return HandlerResult(status=HandlerResultStatus.PASS, message="ran")

    registry.register("_side_effect", "deterministic", _handler)
    yield calls
    registry._handlers.pop("_side_effect", None)


@pytest.mark.unit
class TestPlanMode:
    @pytest.mark.parametrize("invocation", [FILE_CREATE, YAML_INJECT, PROJECT_UPDATE], ids=lambda i: i.handler)
    def test_handlers_return_file_changes_and_write_nothing(
        self, repo: Path, data_root: Path, invocation: HandlerInvocation
    ) -> None:
        before = snapshot(repo)

        result = _executor(repo).execute("C-1", _config(invocation), dry_run=True)

        assert snapshot(repo) == before
        assert result.success
        assert result.dry_run
        assert [item.previewable for item in result.plan] == [True]
        changes = result.plan[0].file_changes
        assert changes and any(c.changes for c in changes)
        assert all(isinstance(c, FileChange) for c in changes)
        assert not result.changed
        assert not data_root.exists(), "a preview writes no manifest"

    def test_file_create_plan_carries_the_content(self, repo: Path, data_root: Path) -> None:
        result = _executor(repo).execute("C-1", _config(FILE_CREATE), dry_run=True)

        assert result.plan[0].file_changes == [
            FileChange(path="SECURITY.md", action="create", content="# Security\n")
        ]

    def test_yaml_inject_honors_preview(self, repo: Path, data_root: Path) -> None:
        result = _executor(repo).execute("C-1", _config(YAML_INJECT), dry_run=True)

        by_path = {c.path: c for c in result.plan[0].file_changes}
        assert by_path[".github/workflows/ci.yml"].action == "modify"
        assert "permissions: {}" in by_path[".github/workflows/ci.yml"].content
        assert by_path[".github/workflows/ci.yml"].before_digest == content_digest(WORKFLOW)
        assert by_path[".github/workflows/done.yml"].action == "none"
        assert by_path[".github/workflows/done.yml"].reason == "already_exists"
        assert (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8") == WORKFLOW

    def test_plan_without_plan_support_is_not_previewable_and_not_run(
        self, repo: Path, data_root: Path, side_effect_handler: list[str]
    ) -> None:
        result = _executor(repo).execute(
            "C-1", _config(HandlerInvocation(handler="_side_effect"), FILE_CREATE), dry_run=True
        )

        assert side_effect_handler == []
        assert [(item.step, item.previewable) for item in result.plan] == [
            ("_side_effect[0]", False),
            ("file_create[1]", True),
        ]
        assert result.plan[0].requires_individual_approval

    def test_exec_is_listed_with_its_command(self, repo: Path, data_root: Path) -> None:
        exec_step = HandlerInvocation(handler="exec", command=["zizmor", "--fix", "."])

        result = _executor(repo).execute("C-1", _config(exec_step), dry_run=True)

        assert result.plan[0].previewable is False
        assert result.plan[0].commands == [["zizmor", "--fix", "."]]

    def test_file_create_on_an_existing_file_changes_nothing(self, repo: Path, data_root: Path) -> None:
        step = HandlerInvocation(handler="file_create", path="EXISTING.md", content="theirs\n")

        result = _executor(repo).execute("C-1", _config(step), dry_run=True)

        [change] = result.plan[0].file_changes
        assert (change.action, change.reason) == ("none", "already_exists")

    def test_when_not_met_is_reported(self, repo: Path, data_root: Path) -> None:
        step = HandlerInvocation(handler="file_create", path="GO.md", content="go\n", when={"primary_language": "go"})
        executor = RemediationExecutor(
            local_path=str(repo), owner=OWNER, repo=REPO, context_values={"primary_language": "python"}
        )

        result = executor.execute("C-1", _config(step), dry_run=True)

        [change] = result.plan[0].file_changes
        assert (change.path, change.action, change.reason) == ("GO.md", "none", "when_not_met")
        assert result.details["handlers"] == []

    def test_plan_digests_are_stable(self, repo: Path, data_root: Path) -> None:
        first = _executor(repo).execute("C-1", _config(FILE_CREATE, YAML_INJECT), dry_run=True)
        second = _executor(repo).execute("C-1", _config(FILE_CREATE, YAML_INJECT), dry_run=True)

        assert [i.digest for i in first.plan] == [i.digest for i in second.plan]

    def test_unsafe_remediation_requires_individual_approval(self, repo: Path, data_root: Path) -> None:
        result = _executor(repo).execute("C-1", _config(FILE_CREATE, safe=False), dry_run=True)

        assert result.plan[0].requires_individual_approval


@pytest.mark.unit
class TestApplyMode:
    @pytest.mark.parametrize("invocation", [FILE_CREATE, YAML_INJECT, PROJECT_UPDATE], ids=lambda i: i.handler)
    def test_writes_exactly_the_planned_changes_and_records_them(
        self, repo: Path, data_root: Path, invocation: HandlerInvocation
    ) -> None:
        planned = _executor(repo).execute("C-1", _config(invocation), dry_run=True)
        expected = {c.path: c.content for item in planned.plan for c in item.file_changes if c.changes}
        before = snapshot(repo)

        result = _executor(repo).execute("C-1", _config(invocation), dry_run=False)

        assert result.success
        assert result.changed
        assert {c.path: c.content for c in result.file_changes if c.changes} == expected
        for path, content in expected.items():
            assert (repo / path).read_text(encoding="utf-8") == content
        after = snapshot(repo)
        touched = {p for p in after if before.get(p) != after[p] and after[p] is not None}
        assert touched == set(expected)

        run = manifest.load_run(IDENTITY, result.run_id, checkout=repo)
        assert run is not None
        assert {f.path: f.after_digest for f in run.files} == {
            path: content_digest(content) for path, content in expected.items()
        }

    def test_one_run_per_executor(self, repo: Path, data_root: Path) -> None:
        executor = _executor(repo)
        first = executor.execute("C-1", _config(FILE_CREATE), dry_run=False)
        second = executor.execute(
            "C-2", _config(HandlerInvocation(handler="file_create", path="B.md", content="b\n")), dry_run=False
        )

        assert first.run_id == second.run_id
        run = manifest.load_run(IDENTITY, first.run_id, checkout=repo)
        assert run is not None
        assert [f.path for f in run.files] == ["SECURITY.md", "B.md"]

    def test_existing_file_is_unchanged_and_not_counted(self, repo: Path, data_root: Path) -> None:
        step = HandlerInvocation(handler="file_create", path="EXISTING.md", content="theirs\n")

        result = _executor(repo).execute("C-1", _config(step), dry_run=False)

        assert result.success
        assert not result.changed
        [change] = result.file_changes
        assert (change.action, change.reason) == ("none", "already_exists")
        assert (repo / "EXISTING.md").read_text(encoding="utf-8") == "mine\n"
        assert result.run_id is None
        assert not data_root.exists()

    def test_handler_without_plan_support_runs_in_apply_when_individually_approved(
        self, repo: Path, data_root: Path, side_effect_handler: list[str]
    ) -> None:
        # FR-023 (043 US5) replaced running it in every apply: it now runs only with its own digest.
        config = _config(HandlerInvocation(handler="_side_effect"))
        preview = _executor(repo).execute("C-1", config, dry_run=True)

        result = RemediationExecutor(
            local_path=str(repo), owner=OWNER, repo=REPO, approvals=[preview.plan[0].digest]
        ).execute("C-1", config, dry_run=False)

        assert side_effect_handler == ["apply"]
        assert result.success
        assert not result.changed

    def test_inconclusive_is_not_a_change(self, repo: Path, data_root: Path) -> None:
        result = _executor(repo).execute(
            "C-1", _config(HandlerInvocation(handler="manual", steps=["Do it"])), dry_run=False
        )

        assert result.success
        assert not result.changed

    def test_error_is_not_a_change(self, repo: Path, data_root: Path) -> None:
        result = _executor(repo).execute(
            "C-1", _config(HandlerInvocation(handler="file_create", path="NO_CONTENT.md")), dry_run=False
        )

        assert not result.success
        assert not result.changed
        assert not (repo / "NO_CONTENT.md").exists()

    def test_file_changes_of_a_non_passing_step_are_not_written(self, repo: Path, data_root: Path) -> None:
        registry = get_sieve_handler_registry()

        def _handler(config, context):
            change = FileChange(path="LEAK.md", action="create", content="x")
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="unsure",
                evidence={"file_changes": [change.model_dump(mode="json")]},
            )

        registry.register("_unsure", "deterministic", _handler, supports_plan=True)
        try:
            result = _executor(repo).execute("C-1", _config(HandlerInvocation(handler="_unsure")), dry_run=False)
        finally:
            registry._handlers.pop("_unsure", None)

        assert not (repo / "LEAK.md").exists()
        assert not result.changed

    def test_modify_is_refused_when_the_file_changed_since_planning(self, repo: Path, data_root: Path) -> None:
        registry = get_sieve_handler_registry()
        stale = FileChange(
            path="EXISTING.md", action="modify", content="new\n", before_digest=content_digest("other\n")
        )

        def _handler(config, context):
            return HandlerResult(
                status=HandlerResultStatus.PASS, message="ok", evidence={"file_changes": [stale.model_dump()]}
            )

        registry.register("_stale", "deterministic", _handler, supports_plan=True)
        try:
            result = _executor(repo).execute("C-1", _config(HandlerInvocation(handler="_stale")), dry_run=False)
        finally:
            registry._handlers.pop("_stale", None)

        assert not result.success
        assert not result.changed
        assert (repo / "EXISTING.md").read_text(encoding="utf-8") == "mine\n"

    def test_checkout_without_identity_records_under_a_local_identity(self, repo: Path, data_root: Path) -> None:
        executor = RemediationExecutor(local_path=str(repo), owner="", repo="")
        executor.owner = executor.repo = None

        result = executor.execute("C-1", _config(FILE_CREATE), dry_run=False)

        assert result.changed
        identity = manifest.repository_identity(repo)
        assert identity.startswith(f"{manifest.LOCAL_HOST}/checkout/")
        run = manifest.load_run(identity, result.run_id, checkout=repo)
        assert run is not None
        assert [f.path for f in run.files] == ["SECURITY.md"]

    def test_config_project_update_is_written_by_the_executor(self, repo: Path, data_root: Path) -> None:
        config = _config(
            FILE_CREATE, project_update=ProjectUpdateRemediationConfig(set={"security.policy.path": "SECURITY.md"})
        )

        planned = _executor(repo).execute("C-1", config, dry_run=True)
        assert not (repo / ".project").exists()
        assert "would set" in planned.details["project_update"]

        result = _executor(repo).execute("C-1", config, dry_run=False)

        assert result.details["project_update"] == "applied"
        run = manifest.load_run(IDENTITY, result.run_id, checkout=repo)
        assert run is not None
        assert {f.path for f in run.files} == {"SECURITY.md", ".project/project.yaml"}

    def test_confirmation_is_checked_before_any_write(self, repo: Path, data_root: Path) -> None:
        from darnit.config.framework_schema import TemplateConfig

        executor = RemediationExecutor(
            local_path=str(repo),
            owner=OWNER,
            repo=REPO,
            templates={"needs": TemplateConfig(content="<< context.maintainers >>\n")},
            unconfirmed_keys=["maintainers"],
        )
        config = _config(
            HandlerInvocation(handler="file_create", path="FIRST.md", content="first\n"),
            HandlerInvocation(handler="file_create", path="SECOND.md", template="needs"),
        )

        result = executor.execute("C-1", config, dry_run=False)

        assert result.confirmation_required == "maintainers"
        assert not (repo / "FIRST.md").exists()
        assert not data_root.exists()
