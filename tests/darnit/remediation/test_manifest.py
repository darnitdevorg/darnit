"""Operator-side remediation run manifest (feature 043, research R7, T007)."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from darnit.remediation import manifest
from darnit.remediation.plan import content_digest

REPO = "github.com/example-org/example"


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data" / "darnit"
    monkeypatch.setattr(manifest, "user_data_root", lambda: root)
    return root


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    path = tmp_path / "checkout"
    path.mkdir()
    return path


@pytest.mark.unit
class TestStartRun:
    def test_written_under_the_data_root_with_mode_0600(self, data_root: Path, checkout: Path) -> None:
        run = manifest.start_run(REPO, checkout=checkout)

        path = data_root / "remediation" / "github.com" / "example-org" / "example" / f"{run.run_id}.json"
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["run_id"] == run.run_id
        assert stored["repository"] == REPO
        assert stored["files"] == []
        assert stored["change_sets"] == []
        assert stored["branch"] is None
        assert stored["commit"] is None

    def test_path_inside_the_checkout_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        checkout = tmp_path / "checkout"
        root = checkout / ".darnit-data"
        monkeypatch.setattr(manifest, "user_data_root", lambda: root)

        with pytest.raises(ValueError, match="inside the audited repository"):
            manifest.start_run(REPO, checkout=checkout)

        assert not root.exists()

    @pytest.mark.parametrize("repository", ["../../etc", "example", "github.com/../x", "github.com/o/r/../../x"])
    def test_repository_must_be_a_canonical_identity(self, data_root: Path, checkout: Path, repository: str) -> None:
        with pytest.raises(ValueError):
            manifest.start_run(repository, checkout=checkout)

    def test_run_ids_are_unique_and_ordered(self, data_root: Path, checkout: Path) -> None:
        ids = [manifest.start_run(REPO, checkout=checkout).run_id for _ in range(5)]

        assert len(set(ids)) == 5
        assert ids == sorted(ids)

    def test_created_at_is_recorded(self, data_root: Path, checkout: Path) -> None:
        now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

        run = manifest.start_run(REPO, checkout=checkout, now=now)

        assert run.created_at == "2026-10-02T12:00:00Z"


@pytest.mark.unit
class TestRecord:
    def test_file_list_carries_after_digest(self, data_root: Path, checkout: Path) -> None:
        run = manifest.start_run(REPO, checkout=checkout)

        manifest.record_file(REPO, run.run_id, "SECURITY.md", content_digest("# Security\n"), checkout=checkout)
        manifest.record_file(REPO, run.run_id, "docs/A.md", content_digest("a"), checkout=checkout)

        loaded = manifest.load_run(REPO, run.run_id, checkout=checkout)
        assert loaded is not None
        assert [(f.path, f.after_digest) for f in loaded.files] == [
            ("SECURITY.md", content_digest("# Security\n")),
            ("docs/A.md", content_digest("a")),
        ]

    def test_recording_a_path_again_replaces_its_digest(self, data_root: Path, checkout: Path) -> None:
        run = manifest.start_run(REPO, checkout=checkout)

        manifest.record_file(REPO, run.run_id, "A.md", content_digest("1"), checkout=checkout)
        manifest.record_file(REPO, run.run_id, "A.md", content_digest("2"), checkout=checkout)

        loaded = manifest.load_run(REPO, run.run_id, checkout=checkout)
        assert loaded is not None
        assert [(f.path, f.after_digest) for f in loaded.files] == [("A.md", content_digest("2"))]

    @pytest.mark.parametrize("path", ["/etc/passwd", "../x", ""])
    def test_file_path_must_be_repository_relative(self, data_root: Path, checkout: Path, path: str) -> None:
        run = manifest.start_run(REPO, checkout=checkout)

        with pytest.raises(ValueError):
            manifest.record_file(REPO, run.run_id, path, content_digest("x"), checkout=checkout)

    def test_change_sets_branch_and_commit(self, data_root: Path, checkout: Path) -> None:
        run = manifest.start_run(REPO, checkout=checkout)

        manifest.record_change_set(REPO, run.run_id, "sha256:abc", checkout=checkout)
        manifest.record_change_set(REPO, run.run_id, "sha256:abc", checkout=checkout)
        manifest.set_branch(REPO, run.run_id, "fix/compliance", checkout=checkout)
        manifest.set_commit(REPO, run.run_id, "0123abcd", checkout=checkout)

        loaded = manifest.load_run(REPO, run.run_id, checkout=checkout)
        assert loaded is not None
        assert loaded.change_sets == ["sha256:abc"]
        assert loaded.branch == "fix/compliance"
        assert loaded.commit == "0123abcd"

    def test_moving_to_a_new_branch_replaces_the_base_even_when_unresolved(
        self, data_root: Path, checkout: Path
    ) -> None:
        run = manifest.start_run(REPO, checkout=checkout)
        manifest.set_branch(REPO, run.run_id, "fix/a", checkout=checkout, base="origin/main", base_commit="c0ffee")

        manifest.set_branch(REPO, run.run_id, "fix/b", checkout=checkout, base=None, base_commit=None)

        loaded = manifest.load_run(REPO, run.run_id, checkout=checkout)
        assert loaded is not None
        assert (loaded.branch, loaded.base, loaded.base_commit) == ("fix/b", None, None)

    def test_same_branch_without_a_base_keeps_the_recorded_base(self, data_root: Path, checkout: Path) -> None:
        run = manifest.start_run(REPO, checkout=checkout)
        manifest.set_branch(REPO, run.run_id, "fix/a", checkout=checkout, base="origin/main", base_commit="c0ffee")

        manifest.set_branch(REPO, run.run_id, "fix/a", checkout=checkout)

        loaded = manifest.load_run(REPO, run.run_id, checkout=checkout)
        assert loaded is not None
        assert (loaded.base, loaded.base_commit) == ("origin/main", "c0ffee")

    def test_recording_to_an_unknown_run_fails(self, data_root: Path, checkout: Path) -> None:
        with pytest.raises(LookupError):
            manifest.record_file(REPO, manifest.new_run_id(), "A.md", content_digest("x"), checkout=checkout)


@pytest.mark.unit
class TestLoadRun:
    def test_latest_run_is_found_without_a_run_id(self, data_root: Path, checkout: Path) -> None:
        manifest.start_run(REPO, checkout=checkout)
        manifest.start_run("github.com/example-org/other", checkout=checkout)
        latest = manifest.start_run(REPO, checkout=checkout)

        loaded = manifest.load_run(REPO, checkout=checkout)

        assert loaded is not None
        assert loaded.run_id == latest.run_id

    def test_no_runs(self, data_root: Path, checkout: Path) -> None:
        assert manifest.load_run(REPO, checkout=checkout) is None
        assert manifest.load_run(REPO, manifest.new_run_id(), checkout=checkout) is None

    def test_malformed_run_id_is_rejected(self, data_root: Path, checkout: Path) -> None:
        with pytest.raises(ValueError):
            manifest.load_run(REPO, "../../confirmations", checkout=checkout)

    def test_a_store_inside_the_checkout_is_not_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        outside = tmp_path / "data"
        monkeypatch.setattr(manifest, "user_data_root", lambda: outside)
        run = manifest.start_run(REPO, checkout=tmp_path / "elsewhere")

        assert manifest.load_run(REPO, run.run_id, checkout=tmp_path) is None


@pytest.mark.unit
class TestRepositoryIdentity:
    def test_operator_named_owner_and_repo(self, tmp_path: Path) -> None:
        assert manifest.repository_identity(tmp_path, "Example-Org", "Example") == REPO

    def test_local_identity_is_stable_and_canonical(self, tmp_path: Path) -> None:
        first = manifest.repository_identity(tmp_path)

        assert first == manifest.repository_identity(tmp_path)
        assert first != manifest.repository_identity(tmp_path / "other")
        assert first.startswith(f"{manifest.LOCAL_HOST}/checkout/")
        assert manifest.runs_dir(first).name == first.rsplit("/", 1)[1]
