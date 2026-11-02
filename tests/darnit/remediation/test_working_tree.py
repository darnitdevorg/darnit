"""Unit tests for working-tree snapshot and diffing utilities (darnit.remediation.working_tree)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from darnit.remediation import git_state, working_tree
from darnit.remediation.plan import FileChange, content_digest


class TestTreeDiff:
    """Tests for the TreeDiff dataclass and representability."""

    def test_representable_when_no_deleted_or_binary(self) -> None:
        diff = working_tree.TreeDiff(
            changes=[
                FileChange(
                    path="a.txt",
                    action="modify",
                    content="new\n",
                    before_digest=content_digest(b"old\n"),
                )
            ]
        )
        assert diff.representable is True

    def test_not_representable_when_files_deleted(self) -> None:
        diff = working_tree.TreeDiff(deleted=["removed.txt"])
        assert diff.representable is False

    def test_not_representable_when_binary_files_present(self) -> None:
        diff = working_tree.TreeDiff(not_text=["image.png"])
        assert diff.representable is False

    def test_default_empty_fields(self) -> None:
        diff = working_tree.TreeDiff()
        assert diff.changes == []
        assert diff.deleted == []
        assert diff.not_text == []
        assert diff.representable is True


class TestAllFiles:
    """Tests for all_files filesystem traversal."""

    def test_lists_files_recursively_excluding_git(self, tmp_path: Path) -> None:
        (tmp_path / "root.txt").write_bytes(b"root\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "child.txt").write_bytes(b"child\n")

        # Create a .git directory that should be ignored
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")

        found = working_tree.all_files(tmp_path)
        assert found == ["root.txt", "sub/child.txt"]

    def test_empty_directory(self, tmp_path: Path) -> None:
        assert working_tree.all_files(tmp_path) == []


class TestVisibleFiles:
    """Tests for visible_files tracked and untracked file discovery."""

    def test_outside_git_work_tree_returns_all_files(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_bytes(b"content\n")
        found = working_tree.visible_files(tmp_path)
        assert found == ["file.txt"]

    def test_in_git_work_tree_returns_tracked_and_untracked(self, temp_git_repo: Path) -> None:
        # README.md is already tracked by the fixture
        (temp_git_repo / "new.py").write_bytes(b"print(1)\n")

        found = working_tree.visible_files(temp_git_repo)
        assert "README.md" in found
        assert "new.py" in found

    def test_git_ls_files_error_raises_git_state_error(
        self, temp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run_git(_root: object, cmd: str, *args: object, **_kw: object) -> MagicMock:
            if cmd == "rev-parse":
                return MagicMock(returncode=0, stdout="true\n")
            if cmd == "ls-files":
                return MagicMock(returncode=1, stderr="fatal error\n")
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(git_state, "run_git", fake_run_git)

        with pytest.raises(git_state.GitStateError, match="git ls-files failed"):
            working_tree.visible_files(temp_git_repo)


class TestEscapingSymlinks:
    """Tests for escaping_symlinks security path traversal detection (framework-design 4.4)."""

    def test_non_symlink_paths_are_not_escaping(self, tmp_path: Path) -> None:
        (tmp_path / "safe.txt").write_bytes(b"safe\n")
        assert working_tree.escaping_symlinks(tmp_path, ["safe.txt"]) == []

    def test_absolute_symlink_is_always_reported_as_escaping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absolute target symlinks are reported even if pointing inside root."""
        (tmp_path / "inside_target.txt").write_bytes(b"target\n")
        link_path = tmp_path / "abs_link.txt"
        link_path.write_bytes(b"placeholder\n")

        monkeypatch.setattr(os.path, "islink", lambda p: p == str(link_path))
        monkeypatch.setattr(os, "readlink", lambda _: "/absolute/target/path")

        escaping = working_tree.escaping_symlinks(tmp_path, ["abs_link.txt"])
        assert escaping == ["abs_link.txt"]

    def test_symlink_resolving_outside_repo_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A link that resolves outside root is caught by within_repository."""
        link_path = tmp_path / "escaping_link.txt"
        link_path.write_bytes(b"placeholder\n")

        monkeypatch.setattr(os.path, "islink", lambda p: p == str(link_path))
        monkeypatch.setattr(os, "readlink", lambda _: "../outside.txt")
        monkeypatch.setattr("darnit.remediation.working_tree.within_repository", lambda *_a: False)

        escaping = working_tree.escaping_symlinks(tmp_path, ["escaping_link.txt"])
        assert escaping == ["escaping_link.txt"]

    def test_safe_relative_symlink_inside_repo(self, tmp_path: Path) -> None:
        (tmp_path / "target.txt").write_bytes(b"target\n")
        link = tmp_path / "link.txt"
        try:
            link.symlink_to("target.txt")
        except OSError as e:
            pytest.skip(f"Symlinks not supported on host: {e}")

        escaping = working_tree.escaping_symlinks(tmp_path, ["link.txt"])
        assert escaping == []

    def test_escaping_symlink_on_filesystem(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside_target.txt"
        outside.write_bytes(b"outside\n")
        link = tmp_path / "escaping.txt"
        try:
            link.symlink_to(outside)
        except OSError as e:
            pytest.skip(f"Symlinks not supported on host: {e}")

        escaping = working_tree.escaping_symlinks(tmp_path, ["escaping.txt"])
        assert escaping == ["escaping.txt"]


class TestIgnored:
    """Tests for ignored files discovery via git check-ignore."""

    def test_outside_git_work_tree_returns_empty_set(self, tmp_path: Path) -> None:
        assert working_tree.ignored(tmp_path, ["foo.txt"]) == set()

    def test_empty_paths_returns_empty_set(self, temp_git_repo: Path) -> None:
        assert working_tree.ignored(temp_git_repo, []) == set()

    def test_matches_gitignore_entries(self, temp_git_repo: Path) -> None:
        (temp_git_repo / ".gitignore").write_bytes(b"*.log\nbuild/\n")
        ignored = working_tree.ignored(temp_git_repo, ["app.py", "debug.log", "test.txt"])
        assert "debug.log" in ignored
        assert "app.py" not in ignored

    def test_git_check_ignore_error_raises_git_state_error(
        self, temp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run_git(_root: object, cmd: str, *args: object, **_kw: object) -> MagicMock:
            if cmd == "rev-parse":
                return MagicMock(returncode=0, stdout="true\n")
            if cmd == "check-ignore":
                return MagicMock(returncode=128, stderr="git error\n")
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(git_state, "run_git", fake_run_git)

        with pytest.raises(git_state.GitStateError, match="git check-ignore failed"):
            working_tree.ignored(temp_git_repo, ["some_file.txt"])


class TestUserChanged:
    """Tests for user_changed uncommitted file tracking."""

    def test_outside_git_returns_empty_set(self, tmp_path: Path) -> None:
        assert working_tree.user_changed(tmp_path) == set()

    def test_returns_modified_and_untracked_files(self, temp_git_repo: Path) -> None:
        (temp_git_repo / "README.md").write_bytes(b"modified\n")
        (temp_git_repo / "untracked.py").write_bytes(b"print(2)\n")

        changed = working_tree.user_changed(temp_git_repo)
        assert "README.md" in changed
        assert "untracked.py" in changed

    def test_clean_repo_returns_empty_set(self, temp_git_repo: Path) -> None:
        changed = working_tree.user_changed(temp_git_repo)
        assert changed == set()

    def test_git_status_error_raises_git_state_error(
        self, temp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run_git(_root: object, cmd: str, *args: object, **_kw: object) -> MagicMock:
            if cmd == "rev-parse":
                return MagicMock(returncode=0, stdout="true\n")
            if cmd == "status":
                return MagicMock(returncode=1, stderr="fatal: corrupted repository\n")
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(git_state, "run_git", fake_run_git)

        with pytest.raises(git_state.GitStateError, match="git status failed"):
            working_tree.user_changed(temp_git_repo)


class TestDigests:
    """Tests for digests calculation."""

    def test_computes_sha256_digests(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"hello\n")
        (tmp_path / "b.txt").write_bytes(b"world\n")

        found = working_tree.digests(tmp_path, ["a.txt", "b.txt"])

        assert found["a.txt"] == content_digest(b"hello\n")
        assert found["b.txt"] == content_digest(b"world\n")

    def test_skips_missing_files(self, tmp_path: Path) -> None:
        found = working_tree.digests(tmp_path, ["missing.txt"])
        assert found == {}


class TestCopyFiles:
    """Tests for copy_files with directory creation and symlink preservation."""

    def test_copies_files_preserving_structure(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        (src / "sub" / "deep").mkdir(parents=True)
        (src / "sub" / "deep" / "data.json").write_bytes(b'{"ok": true}')

        working_tree.copy_files(src, dst, ["sub/deep/data.json"])

        target = dst / "sub" / "deep" / "data.json"
        assert target.exists()
        assert target.read_bytes() == b'{"ok": true}'


class TestDiff:
    """Tests for diff snapshot comparison."""

    def test_identical_files_produce_empty_diff(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"unchanged\n")
        digest = content_digest(b"unchanged\n")
        before = {"a.txt": digest}

        result = working_tree.diff(tmp_path, before, ["a.txt"])

        assert result.changes == []
        assert result.deleted == []
        assert result.not_text == []
        assert result.representable is True

    def test_created_file_produces_create_action(self, tmp_path: Path) -> None:
        (tmp_path / "new.txt").write_bytes(b"brand new\n")
        before: dict[str, str] = {}

        result = working_tree.diff(tmp_path, before, ["new.txt"])

        assert len(result.changes) == 1
        change = result.changes[0]
        assert change.path == "new.txt"
        assert change.action == "create"
        assert change.content == "brand new\n"
        assert change.before_digest is None

    def test_modified_file_produces_modify_action(self, tmp_path: Path) -> None:
        (tmp_path / "edited.txt").write_bytes(b"new content\n")
        before = {"edited.txt": content_digest(b"old content\n")}

        result = working_tree.diff(tmp_path, before, ["edited.txt"])

        assert len(result.changes) == 1
        change = result.changes[0]
        assert change.path == "edited.txt"
        assert change.action == "modify"
        assert change.content == "new content\n"
        assert change.before_digest == before["edited.txt"]

    def test_deleted_file_recorded_in_deleted(self, tmp_path: Path) -> None:
        before = {"removed.txt": content_digest(b"content\n")}
        result = working_tree.diff(tmp_path, before, [])

        assert result.deleted == ["removed.txt"]
        assert result.changes == []
        assert result.representable is False

    def test_binary_file_recorded_in_not_text(self, tmp_path: Path) -> None:
        (tmp_path / "binary.bin").write_bytes(b"\x80\x81\xff\xfe\x00")
        before = {"binary.bin": content_digest(b"\x00")}

        result = working_tree.diff(tmp_path, before, ["binary.bin"])

        assert result.not_text == ["binary.bin"]
        assert result.changes == []
        assert result.representable is False
