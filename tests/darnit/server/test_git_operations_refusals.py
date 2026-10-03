"""Refused repository states, user-change conflicts, and ignored targets (feature 043, US2, FR-010..FR-014)."""

from __future__ import annotations

import subprocess
from functools import partial
from pathlib import Path

import pytest

from darnit.config.framework_schema import HandlerInvocation, RemediationConfig
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationExecutor
from darnit.remediation.git_state import TRAILER_KEY, check_repository_state
from darnit.remediation.plan import FileChange
from darnit.server.tools import git_operations

from .conftest import (
    REMEDIATION_BRANCH,
    SUCCESS,
    BareRemote,
    DirtyRepo,
    ForeignBranchRepo,
    assert_unchanged,
    git,
    snapshot,
)

OWNER, REPO = "example-org", "example"
IDENTITY = f"github.com/{OWNER}/{REPO}"
create_branch = partial(git_operations.create_remediation_branch_impl, owner=OWNER, repo=REPO)
commit_changes = partial(git_operations.commit_remediation_changes_impl, owner=OWNER, repo=REPO)
create_pr = partial(git_operations.create_remediation_pr_impl, owner=OWNER, repo=REPO)
SECURITY = HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Security\n")
CONTRIBUTING = HandlerInvocation(handler="file_create", path="CONTRIBUTING.md", content="# Contributing\n")


@pytest.fixture(autouse=True)
def no_gh(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_gh(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return subprocess.CompletedProcess(["gh", *args], 0, stdout="https://example.invalid/pull/1\n", stderr="")

    monkeypatch.setattr(git_operations, "_gh", fake_gh)
    return calls


def _git_state(repo: Path) -> dict[str, str]:
    git_dir = repo / git(repo, "rev-parse", "--git-dir").stdout.strip()
    return {
        "head": git(repo, "rev-parse", "HEAD").stdout,
        "symbolic": git(repo, "symbolic-ref", "-q", "HEAD", check=False).stdout,
        "refs": git(repo, "for-each-ref", "--format=%(refname) %(objectname)").stdout,
        "status": git(repo, "status", "--porcelain", "--untracked-files=all").stdout,
        "stash": git(repo, "stash", "list").stdout,
        "index": git(repo, "ls-files", "--stage").stdout,
        "merge_head": (git_dir / "MERGE_HEAD").read_text() if (git_dir / "MERGE_HEAD").exists() else "",
    }


def _apply(repo: Path, *handlers: HandlerInvocation, run_id: str | None = None):
    return RemediationExecutor(owner=OWNER, repo=REPO, local_path=str(repo), run_id=run_id).execute(
        "C-1", RemediationConfig(handlers=list(handlers)), dry_run=False
    )


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for relative, content in files.items():
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(content, encoding="utf-8")
    git(repo, "add", "--", *files)
    git(repo, "commit", "-q", "-m", message, "--", *files)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.mark.integration
class TestRefusedStates:
    """framework-design.md 15.7, scenario "Unsafe repository state" (FR-013)."""

    @pytest.mark.parametrize(
        ("fixture", "reason"),
        [
            ("r_detached", "detached"),
            ("r_merging", "merge is in progress"),
            ("r_foreign_branch", TRAILER_KEY),
        ],
    )
    def test_branch_step_is_refused_with_nothing_changed(
        self, request: pytest.FixtureRequest, fixture: str, reason: str
    ) -> None:
        repo: Path = request.getfixturevalue(fixture).path
        files, state = snapshot(repo), _git_state(repo)

        refusal = check_repository_state(repo, REMEDIATION_BRANCH)
        result = create_branch(branch_name=REMEDIATION_BRANCH, local_path=str(repo))

        assert refusal is not None and reason in refusal
        assert result.startswith(("Error", "Conflict")) and reason in result
        assert_unchanged(repo, files)
        assert _git_state(repo) == state
        assert manifest.load_run(IDENTITY) is None

    @pytest.mark.parametrize("fixture", ["r_detached", "r_merging"])
    def test_commit_step_is_refused_with_nothing_changed(self, request: pytest.FixtureRequest, fixture: str) -> None:
        repo: Path = request.getfixturevalue(fixture).path
        run = manifest.start_run(IDENTITY, checkout=repo)
        files, state = snapshot(repo), _git_state(repo)

        result = commit_changes(local_path=str(repo), run_id=run.run_id)

        assert result.startswith(("Error", "Conflict"))
        assert_unchanged(repo, files)
        assert _git_state(repo) == state

    def test_rebase_in_progress_is_refused(self, r_foreign_branch: ForeignBranchRepo) -> None:
        repo = r_foreign_branch.path
        git_dir = repo / git(repo, "rev-parse", "--git-dir").stdout.strip()
        (git_dir / "rebase-merge").mkdir()
        files, state = snapshot(repo), _git_state(repo)

        result = create_branch(branch_name="fix/new", local_path=str(repo))

        assert result.startswith(("Error", "Conflict")) and "rebase" in result
        assert_unchanged(repo, files)
        assert _git_state(repo) == state

    def test_switching_to_an_existing_branch_with_a_dirty_tree_is_refused(self, r_dirty: DirtyRepo) -> None:
        repo = r_dirty.path
        git(repo, "branch", REMEDIATION_BRANCH)
        files, state = snapshot(repo), _git_state(repo)

        result = create_branch(branch_name=REMEDIATION_BRANCH, local_path=str(repo))

        assert result.startswith(("Error", "Conflict")) and "clean working tree" in result
        assert_unchanged(repo, files)
        assert _git_state(repo) == state

    def test_existing_branch_with_only_trailer_commits_is_reused(self, r_foreign_branch: ForeignBranchRepo) -> None:
        repo = r_foreign_branch.path
        git(repo, "checkout", "-q", "-b", "fix/darnit")
        _commit(repo, f"chore: earlier remediation\n\n{TRAILER_KEY}: {manifest.new_run_id()}", {"SECURITY.md": "x\n"})
        git(repo, "checkout", "-q", "main")
        run_id = manifest.new_run_id()

        result = create_branch(branch_name="fix/darnit", local_path=str(repo), run_id=run_id)

        assert result.startswith(SUCCESS), result
        assert git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip() == "fix/darnit"
        run = manifest.load_run(IDENTITY, run_id)
        assert run is not None and run.branch == "fix/darnit"

    def test_pr_refuses_a_branch_that_gained_a_foreign_commit(
        self, r_foreign_branch: ForeignBranchRepo, bare_remote: BareRemote, no_gh: list[list[str]]
    ) -> None:
        repo = r_foreign_branch.path
        bare_remote.attach(repo)
        run_id = manifest.new_run_id()
        assert create_branch(branch_name="fix/darnit", local_path=str(repo), run_id=run_id).startswith(SUCCESS)
        assert _apply(repo, SECURITY, run_id=run_id).changed
        assert commit_changes(local_path=str(repo), run_id=run_id).startswith(SUCCESS)
        _commit(repo, "user work on the remediation branch", {"NOTES.md": "mine\n"})
        remote_before = bare_remote.branches()

        result = create_pr(local_path=str(repo), run_id=run_id)

        assert result.startswith(("Error", "Conflict")) and TRAILER_KEY in result
        assert bare_remote.branches() == remote_before
        assert no_gh == []

    def test_pr_refuses_main(self, r_foreign_branch: ForeignBranchRepo, bare_remote: BareRemote) -> None:
        repo = r_foreign_branch.path
        bare_remote.attach(repo)
        run_id = manifest.new_run_id()
        assert _apply(repo, SECURITY, run_id=run_id).changed
        assert commit_changes(local_path=str(repo), run_id=run_id).startswith(SUCCESS)
        refs = ("for-each-ref", "--format=%(refname) %(objectname)")
        remote_before = git(bare_remote.path, *refs).stdout

        result = create_pr(local_path=str(repo), run_id=run_id)

        assert result.startswith(("Error", "Conflict")) and "main" in result
        assert git(bare_remote.path, *refs).stdout == remote_before

    def test_pr_refuses_the_base_branch_itself(
        self, r_foreign_branch: ForeignBranchRepo, bare_remote: BareRemote, no_gh: list[list[str]]
    ) -> None:
        repo = r_foreign_branch.path
        git(repo, "branch", "-m", "main", "develop")
        bare_remote.attach(repo, push="develop")
        git(repo, "remote", "set-head", "origin", "develop")
        run_id = manifest.new_run_id()
        assert _apply(repo, SECURITY, run_id=run_id).changed
        assert commit_changes(local_path=str(repo), run_id=run_id).startswith(SUCCESS)
        refs = ("for-each-ref", "--format=%(refname) %(objectname)")
        remote_before = git(bare_remote.path, *refs).stdout

        result = create_pr(local_path=str(repo), run_id=run_id)

        assert result.startswith("Error") and "'develop'" in result, result
        assert git(bare_remote.path, *refs).stdout == remote_before
        assert no_gh == []


@pytest.mark.integration
class TestUserChanges:
    """FR-011: a target with uncommitted user changes is not written."""

    def test_modified_target_is_not_written(self, r_dirty: DirtyRepo) -> None:
        repo = r_dirty.path
        overwrite = HandlerInvocation(handler="file_create", path="README.md", content="# Replaced\n", overwrite=True)

        result = _apply(repo, overwrite)

        assert r_dirty.modified.read_text(encoding="utf-8") == r_dirty.modified_content
        assert result.file_changes == [FileChange(path="README.md", action="none", reason="user_changes_present")]
        assert not result.changed
        assert manifest.load_run(IDENTITY) is None

    def test_deleted_tracked_target_is_not_recreated(self, r_dirty: DirtyRepo) -> None:
        repo = r_dirty.path
        (repo / "src" / "app.py").unlink()
        recreate = HandlerInvocation(handler="file_create", path="src/app.py", content="print('darnit')\n")

        result = _apply(repo, recreate, SECURITY)

        assert not (repo / "src" / "app.py").exists()
        assert result.file_changes[0] == FileChange(path="src/app.py", action="none", reason="user_changes_present")
        assert (repo / "SECURITY.md").is_file(), "an unrelated target is still written"
        run = manifest.load_run(IDENTITY)
        assert run is not None and [f.path for f in run.files] == ["SECURITY.md"]

    def test_file_written_earlier_in_the_run_is_not_a_user_change(self, r_dirty: DirtyRepo) -> None:
        repo = r_dirty.path
        executor = RemediationExecutor(owner=OWNER, repo=REPO, local_path=str(repo))
        first = executor.execute("C-1", RemediationConfig(handlers=[SECURITY]), dry_run=False)
        rewrite = HandlerInvocation(
            handler="file_create", path="SECURITY.md", content="# Security v2\n", overwrite=True
        )

        second = executor.execute("C-2", RemediationConfig(handlers=[rewrite]), dry_run=False)

        assert first.changed and second.changed
        assert (repo / "SECURITY.md").read_text(encoding="utf-8") == "# Security v2\n"

    def test_not_a_git_repository_skips_the_check(self, tmp_path: Path) -> None:
        repo = tmp_path / "plain"
        repo.mkdir()

        result = _apply(repo, SECURITY)

        assert result.changed
        assert result.file_changes[0].action == "create" and not result.file_changes[0].ignored


@pytest.mark.integration
class TestIgnoredTargets:
    """FR-014: an ignored target is written but never staged."""

    def test_ignored_target_is_written_and_not_committed(self, r_dirty: DirtyRepo) -> None:
        repo = r_dirty.path
        _commit(repo, "ignore generated", {".gitignore": "generated/\n"})
        report = HandlerInvocation(handler="file_create", path="generated/report.md", content="# Report\n")

        result = _apply(repo, report, SECURITY)
        commit = commit_changes(local_path=str(repo), run_id=result.run_id)

        assert [(c.path, c.ignored) for c in result.file_changes] == [
            ("generated/report.md", True),
            ("SECURITY.md", False),
        ]
        assert (repo / "generated" / "report.md").is_file()
        assert commit.startswith(SUCCESS), commit
        committed = git(repo, "diff-tree", "-r", "--no-commit-id", "--name-only", "HEAD").stdout.split()
        assert committed == ["SECURITY.md"]
        assert git(repo, "ls-files", "--", "generated/report.md").stdout == ""
        assert "generated/report.md" in commit and "ignored" in commit


@pytest.mark.integration
class TestConflicts:
    """A manifest file edited after remediation wrote it is a conflict; nothing is committed."""

    def test_edited_file_is_not_committed_and_conflict_reported(self, r_dirty: DirtyRepo) -> None:
        repo = r_dirty.path
        result = _apply(repo, SECURITY, CONTRIBUTING)
        (repo / "SECURITY.md").write_text("# Security\n\nedited by the user\n", encoding="utf-8")
        files, state = snapshot(repo), _git_state(repo)

        commit = commit_changes(local_path=str(repo), run_id=result.run_id)

        assert commit.startswith(("Error", "Conflict")) and "SECURITY.md" in commit and "conflict" in commit.lower()
        assert_unchanged(repo, files)
        assert _git_state(repo) == state
        run = manifest.load_run(IDENTITY, result.run_id)
        assert run is not None and run.commit is None

    def test_user_staged_changes_are_not_committed(self, r_dirty: DirtyRepo) -> None:
        repo = r_dirty.path
        git(repo, "add", "README.md")
        result = _apply(repo, SECURITY)

        commit = commit_changes(local_path=str(repo), run_id=result.run_id)

        assert commit.startswith(SUCCESS), commit
        committed = git(repo, "diff-tree", "-r", "--no-commit-id", "--name-only", "HEAD").stdout.split()
        assert committed == ["SECURITY.md"]
        assert git(repo, "diff", "--cached", "--name-only").stdout.split() == ["README.md"]
        assert r_dirty.modified.read_text(encoding="utf-8") == r_dirty.modified_content

    def test_unknown_run_is_refused(self, r_dirty: DirtyRepo) -> None:
        files, state = snapshot(r_dirty.path), _git_state(r_dirty.path)

        commit = commit_changes(local_path=str(r_dirty.path))

        assert commit.startswith(("Error", "Conflict")) and "run" in commit
        assert_unchanged(r_dirty.path, files)
        assert _git_state(r_dirty.path) == state


@pytest.mark.integration
class TestCommitStepFailures:
    """A failure after ``git commit`` never reports "Nothing was committed"; one before it changes nothing."""

    def test_unreadable_prefix_fails_before_anything_is_committed(
        self, r_dirty: DirtyRepo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from darnit.remediation import git_state

        repo = r_dirty.path
        result = _apply(repo, SECURITY)
        head = git(repo, "rev-parse", "HEAD").stdout
        real_run_git = git_state.run_git

        def failing_prefix(repo_path, *args, **kwargs):
            if "--show-prefix" in args:
                return subprocess.CompletedProcess(["git", *args], 128, stdout="", stderr="fatal: simulated")
            return real_run_git(repo_path, *args, **kwargs)

        monkeypatch.setattr(git_state, "run_git", failing_prefix)

        commit = commit_changes(local_path=str(repo), run_id=result.run_id)

        assert commit.startswith("Error") and "Nothing was committed" in commit, commit
        assert git(repo, "rev-parse", "HEAD").stdout == head
        assert git(repo, "diff", "--cached", "--name-only").stdout == ""
        run = manifest.load_run(IDENTITY, result.run_id)
        assert run is not None and run.commit is None

    def test_failure_listing_the_commit_still_records_it(
        self, r_dirty: DirtyRepo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = r_dirty.path
        result = _apply(repo, SECURITY)
        real_run_git = git_operations.run_git

        def failing_listing(repo_path, *args, **kwargs):
            if "diff-tree" in args:
                raise OSError("simulated failure after the commit")
            return real_run_git(repo_path, *args, **kwargs)

        monkeypatch.setattr(git_operations, "run_git", failing_listing)

        commit = commit_changes(local_path=str(repo), run_id=result.run_id)

        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        assert "Nothing was committed" not in commit, commit
        assert head[:12] in commit and "simulated failure" in commit, commit
        run = manifest.load_run(IDENTITY, result.run_id)
        assert run is not None and run.commit == head

    def test_failure_recording_the_commit_reports_the_commit(
        self, r_dirty: DirtyRepo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = r_dirty.path
        result = _apply(repo, SECURITY)

        def failing_set_commit(*_args, **_kwargs):
            raise OSError("simulated manifest write failure")

        monkeypatch.setattr(manifest, "set_commit", failing_set_commit)

        commit = commit_changes(local_path=str(repo), run_id=result.run_id)

        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        assert "Nothing was committed" not in commit, commit
        assert head[:12] in commit and "not recorded" in commit, commit
        assert git(repo, "log", "-1", "--format=%B").stdout.count(TRAILER_KEY) == 1

    def test_failure_recording_the_branch_says_the_commit_is_recorded(
        self, r_dirty: DirtyRepo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = r_dirty.path
        result = _apply(repo, SECURITY)

        def failing_set_branch(*_args, **_kwargs):
            raise OSError("simulated manifest write failure")

        monkeypatch.setattr(manifest, "set_branch", failing_set_branch)

        commit = commit_changes(local_path=str(repo), run_id=result.run_id)

        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        assert "recorded it in remediation run" in commit and "branch" in commit, commit
        assert "the commit is not recorded" not in commit, commit
        run = manifest.load_run(IDENTITY, result.run_id)
        assert run is not None and run.commit == head


@pytest.mark.integration
class TestSubdirectoryCheckout:
    """``local_path`` is a subdirectory of the repository: git reports paths from the repository root."""

    def test_user_changes_are_found_relative_to_the_subdirectory(self, r_dirty: DirtyRepo) -> None:
        from darnit.remediation import working_tree

        (r_dirty.path / "src" / "app.py").write_text("print('mine')\n", encoding="utf-8")
        (r_dirty.path / "src" / "new.py").write_text("x = 1\n", encoding="utf-8")

        assert working_tree.user_changed(r_dirty.path / "src") == {"app.py", "new.py"}

    def test_exec_does_not_run_over_a_previewed_path_with_user_changes(self, r_dirty: DirtyRepo) -> None:
        import sys

        src = r_dirty.path / "src"
        rewrite = HandlerInvocation(
            handler="exec",
            command=[sys.executable, "-c", "from pathlib import Path; Path('app.py').write_text('fixed\\n')"],
            effects="working_tree",
            offline=True,
        )
        config = RemediationConfig(handlers=[rewrite])
        preview = RemediationExecutor(owner=OWNER, repo=REPO, local_path=str(src)).execute("C-1", config)
        assert [c.path for c in preview.plan[0].file_changes] == ["app.py"]
        (src / "app.py").write_text("print('mine')\n", encoding="utf-8")

        result = RemediationExecutor(owner=OWNER, repo=REPO, local_path=str(src)).execute(
            "C-1", config, dry_run=False
        )

        assert (src / "app.py").read_text(encoding="utf-8") == "print('mine')\n"
        assert FileChange(path="app.py", action="none", reason="user_changes_present") in result.file_changes
        assert not result.changed

    def test_commit_lists_files_relative_to_the_subdirectory_without_a_false_warning(
        self, r_dirty: DirtyRepo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(git_operations, "validate_local_path", lambda path: (str(Path(path).resolve()), None))
        docs = r_dirty.path / "docs"
        result = _apply(docs, SECURITY)

        commit = commit_changes(local_path=str(docs), run_id=result.run_id)

        assert commit.startswith(SUCCESS), commit
        assert git(r_dirty.path, "diff-tree", "-r", "--no-commit-id", "--name-only", "HEAD").stdout.split() == [
            "docs/SECURITY.md"
        ]
        assert "Warning" not in commit
        assert "  - SECURITY.md" in commit
