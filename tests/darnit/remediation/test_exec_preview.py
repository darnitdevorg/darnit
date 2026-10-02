"""Exec remediation preview in a scratch copy, and apply compared with it (feature 043 US5, T048; framework-design 4.4).

An exec step that declares ``effects = "working_tree"`` and ``offline = true``
is previewed by running it in a scratch copy of the tracked and
untracked-not-ignored files; the difference is its ``FileChange``s and the
checkout is untouched. Apply runs it in the checkout, records what it changed
in the run manifest, and reports any difference from the preview. Without both
declarations the step cannot be previewed exactly: it is not run in plan mode
and needs individual approval.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from darnit.config.framework_schema import FrameworkConfig, HandlerInvocation, RemediationConfig
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationExecutor
from darnit.remediation.plan import FileChange, content_digest
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus, get_sieve_handler_registry
from tests.conftest_helpers import assert_unchanged, snapshot

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

OWNER, REPO = "o", "r"
REPOSITORY = "github.com/o/r"
_GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

FIX = """
from pathlib import Path
Path("a.txt").write_text(Path("a.txt").read_text().replace("old", "new"))
Path("b.txt").write_text("created\\n")
Path("c.txt").write_text(Path("u.txt").read_text())
Path("tool.env").write_text("cache\\n")
"""
SEES_SECRET = """
from pathlib import Path
Path("found.txt").write_text("yes\\n" if Path("secret.env").exists() else "no\\n")
"""
WHERE = """
import os
from pathlib import Path
Path("b.txt").write_text(os.getcwd() + "\\n")
"""
ONLY_IN_CHECKOUT = """
from pathlib import Path
Path("b.txt").write_text("created\\n")
if Path(".git").exists():
    Path("d.txt").write_text(Path("d.txt").read_text() + "tool\\n")
"""
MARK = """
from pathlib import Path
Path("RAN").write_text("ran\\n")
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    (path / ".gitignore").write_text("*.env\n", encoding="utf-8")
    (path / "a.txt").write_text("old\n", encoding="utf-8")
    (path / "d.txt").write_text("committed\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "--no-gpg-sign", "-m", "init")
    (path / "u.txt").write_text("untracked\n", encoding="utf-8")
    (path / "secret.env").write_text("TOKEN=not-a-secret\n", encoding="utf-8")
    return path


def _step(script: str, **declarations) -> HandlerInvocation:
    return HandlerInvocation(handler="exec", command=[sys.executable, "-c", script], **declarations)


def _previewable(script: str) -> RemediationConfig:
    return RemediationConfig(handlers=[_step(script, effects="working_tree", offline=True)])


def _executor(repo: Path, **kwargs) -> RemediationExecutor:
    return RemediationExecutor(local_path=str(repo), owner=OWNER, repo=REPO, **kwargs)


def _changes(changes: list[FileChange]) -> dict[str, tuple[str, str | None]]:
    return {c.path: (c.action, c.content) for c in changes if c.changes}


@pytest.mark.unit
class TestPreview:
    def test_runs_in_a_scratch_copy_and_lists_the_diff(self, repo: Path) -> None:
        before = snapshot(repo)

        result = _executor(repo).execute("T-01", _previewable(FIX), dry_run=True)

        assert_unchanged(repo, before)
        assert manifest.load_run(REPOSITORY, checkout=repo) is None
        [item] = result.plan
        assert item.previewable is True
        assert item.requires_individual_approval is False
        assert item.commands == [[sys.executable, "-c", FIX]]
        assert _changes(item.file_changes) == {
            "a.txt": ("modify", "new\n"),
            "b.txt": ("create", "created\n"),
            "c.txt": ("create", "untracked\n"),
        }
        [modified] = [c for c in item.file_changes if c.path == "a.txt"]
        assert modified.before_digest == content_digest("old\n")

    def test_ignored_files_are_not_copied(self, repo: Path) -> None:
        result = _executor(repo).execute("T-01", _previewable(SEES_SECRET), dry_run=True)

        assert _changes(result.plan[0].file_changes) == {"found.txt": ("create", "no\n")}

    def test_preview_is_stable(self, repo: Path) -> None:
        first = _executor(repo).execute("T-01", _previewable(FIX), dry_run=True)
        second = _executor(repo).execute("T-01", _previewable(FIX), dry_run=True)

        assert first.plan[0].digest == second.plan[0].digest


@pytest.mark.unit
class TestApply:
    def test_apply_equals_the_preview_and_is_recorded(self, repo: Path) -> None:
        planned = _executor(repo).execute("T-01", _previewable(FIX), dry_run=True)

        result = _executor(repo).execute("T-01", _previewable(FIX), dry_run=False)

        assert result.success and result.changed
        assert _changes(result.file_changes) == _changes(planned.plan[0].file_changes)
        assert (repo / "a.txt").read_text(encoding="utf-8") == "new\n"
        run = manifest.load_run(REPOSITORY, result.run_id, checkout=repo)
        assert run is not None
        assert {f.path: f.after_digest for f in run.files} == {
            "a.txt": content_digest("new\n"),
            "b.txt": content_digest("created\n"),
            "c.txt": content_digest("untracked\n"),
        }

    def test_a_diff_that_differs_from_the_preview_is_reported(self, repo: Path) -> None:
        result = _executor(repo).execute("T-01", _previewable(WHERE), dry_run=False)

        assert result.success is False
        assert result.changed is False
        [entry] = result.details["handlers"]
        assert entry["status"] == "error"
        assert "b.txt" in entry["preview_mismatch"]["different"]
        assert "differ from the preview" in entry["message"]

    def test_previewed_path_with_user_changes_is_not_run(self, repo: Path) -> None:
        (repo / "a.txt").write_text("old\nmine\n", encoding="utf-8")

        result = _executor(repo).execute("T-01", _previewable(FIX), dry_run=False)

        assert (repo / "a.txt").read_text(encoding="utf-8") == "old\nmine\n"
        assert not (repo / "b.txt").exists()
        assert result.success is False
        assert FileChange(path="a.txt", action="none", reason="user_changes_present") in result.file_changes
        assert "a.txt" in result.details["handlers"][0]["message"]

    def test_changed_file_with_user_changes_is_a_conflict_and_not_recorded(self, repo: Path) -> None:
        (repo / "d.txt").write_text("committed\nmine\n", encoding="utf-8")

        result = _executor(repo).execute("T-01", _previewable(ONLY_IN_CHECKOUT), dry_run=False)

        assert result.success is False
        assert FileChange(path="d.txt", action="none", reason="user_changes_present") in result.file_changes
        run = manifest.load_run(REPOSITORY, checkout=repo)
        assert run is not None
        assert "d.txt" not in {f.path for f in run.files}


@pytest.mark.unit
class TestNotPreviewable:
    @pytest.mark.parametrize(
        "declarations",
        [{}, {"effects": "working_tree"}, {"offline": True}, {"effects": "working_tree", "offline": False}],
        ids=["none", "effects_only", "offline_only", "online"],
    )
    def test_without_both_declarations_it_is_not_run_in_plan_mode(self, repo: Path, declarations: dict) -> None:
        config = RemediationConfig(handlers=[_step(MARK, **declarations)])
        before = snapshot(repo)

        result = _executor(repo).execute("T-01", config, dry_run=True)

        assert_unchanged(repo, before)
        [item] = result.plan
        assert item.previewable is False
        assert item.requires_individual_approval is True
        assert item.commands == [[sys.executable, "-c", MARK]]

    def test_batch_apply_skips_it_without_its_digest(self, repo: Path) -> None:
        config = RemediationConfig(handlers=[_step(MARK)])
        before = snapshot(repo)

        result = _executor(repo).execute("T-01", config, dry_run=False)

        assert_unchanged(repo, before)
        assert result.changed is False
        assert len(result.needs_approval) == 1

    def test_individually_approved_it_runs_and_its_changes_are_recorded(self, repo: Path) -> None:
        config = RemediationConfig(handlers=[_step(MARK)])
        preview = _executor(repo).execute("T-01", config, dry_run=True)

        result = _executor(repo, approvals=[preview.plan[0].digest]).execute("T-01", config, dry_run=False)

        assert (repo / "RAN").exists()
        assert result.success and result.changed
        run = manifest.load_run(REPOSITORY, result.run_id, checkout=repo)
        assert run is not None
        assert [f.path for f in run.files] == ["RAN"]

    def test_the_handler_itself_refuses_to_run_in_plan_mode(self, repo: Path) -> None:
        handler = get_sieve_handler_registry().get("exec").fn
        context = HandlerContext(local_path=str(repo), owner=OWNER, repo=REPO, mode="plan")

        result = handler({"command": [sys.executable, "-c", MARK]}, context)

        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["previewable"] is False
        assert not (repo / "RAN").exists()


def _framework(step: dict) -> dict:
    return {
        "metadata": {"name": "t", "display_name": "T", "version": "1"},
        "controls": {"T-01": {"name": "T", "description": "t", "remediation": {"handlers": [step]}}},
    }


@pytest.mark.unit
class TestSchema:
    def test_declarations_validate(self) -> None:
        config = FrameworkConfig.model_validate(
            _framework({"handler": "exec", "command": ["zizmor"], "effects": "working_tree", "offline": True})
        )

        extra = config.controls["T-01"].remediation.handlers[0].model_extra
        assert (extra["effects"], extra["offline"]) == ("working_tree", True)

    @pytest.mark.parametrize("fields", [{"effects": "platform"}, {"offline": "yes"}])
    def test_invalid_declarations_fail_validation(self, fields: dict) -> None:
        with pytest.raises(ValidationError):
            FrameworkConfig.model_validate(_framework({"handler": "exec", "command": ["zizmor"], **fields}))


def _toml(tmp_path: Path, command: list[str]) -> Path:
    rendered = ", ".join(f'"{arg}"' for arg in command)
    path = tmp_path / "framework.toml"
    path.write_text(
        '[metadata]\nname = "t"\ndisplay_name = "T"\nversion = "1"\n\n'
        '[controls."T-01"]\nname = "T"\ndescription = "t"\n\n'
        f'[[controls."T-01".remediation.handlers]]\nhandler = "exec"\ncommand = [{rendered}]\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
class TestValidateSync:
    @pytest.mark.parametrize(
        "command",
        [
            ["gh", "api", "-X", "PUT", "/repos/$OWNER/$REPO"],
            ["/usr/bin/curl", "-X", "POST", "https://api.github.com"],
            ["wget", "https://example.com"],
            ["git", "push", "origin", "main"],
            ["git", "-C", "$PATH", "push"],
            ["sh", "-c", "gh api -X PUT /repos/o/r"],
        ],
        ids=["gh", "curl", "wget", "git_push", "git_c_push", "shell_gh"],
    )
    def test_rejects_an_exec_remediation_calling_a_platform_command(self, tmp_path: Path, command: list[str]) -> None:
        from validate_sync import validate_remediation_properties

        result = validate_remediation_properties([_toml(tmp_path, command)])

        assert not result.passed
        assert "T-01" in result.details

    @pytest.mark.parametrize(
        "command",
        [["zizmor", "--fix=all", "--offline", "$PATH"], ["uv", "lock"], ["git", "status"]],
        ids=["zizmor", "uv", "git_status"],
    )
    def test_accepts_a_local_command(self, tmp_path: Path, command: list[str]) -> None:
        from validate_sync import validate_remediation_properties

        result = validate_remediation_properties([_toml(tmp_path, command)])

        assert result.passed, result.details
