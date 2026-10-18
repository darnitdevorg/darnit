"""Threat model files are written only through the remediation executor (framework-design 4.2, 15.8).

The ``generate_threat_model`` MCP tool writes only to a validated repository
path, never over a file with uncommitted changes, and records what it writes
in a run manifest the git tools commit. The OSPS-SA-03.02 remediation does the
same through the executor.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from darnit.config import load_framework_config
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationExecutor
from darnit_baseline.tools import commit_remediation_changes, generate_threat_model
from tests.conftest_helpers import snapshot

BASELINE_TOML = (
    Path(__file__).resolve().parents[2] / "packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml"
)
APP = "import subprocess\n\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n"


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "t@example.com")


@pytest.fixture(autouse=True, scope="module")
def _plugin_handlers() -> None:
    from darnit_baseline.implementation import OSPSBaselineImplementation

    OSPSBaselineImplementation().register_handlers()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / "src").mkdir(parents=True)
    (path / "src" / "app.py").write_text(APP, encoding="utf-8")
    (path / "README.md").write_text("# Project\n", encoding="utf-8")
    _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "--no-gpg-sign", "-m", "init")
    return path


def _outside(tmp_path: Path) -> dict[str, str | None]:
    return {p: d for p, d in snapshot(tmp_path).items() if not p.startswith("repo/") and p != "repo"}


@pytest.mark.parametrize(
    "output_path", ["../escaped.md", "docs/../../escaped.md", ".git/escaped.md", "{tmp}/escaped.md"]
)
def test_output_path_leaving_the_repository_is_refused(tmp_path: Path, repo: Path, output_path: str) -> None:
    output_path = output_path.format(tmp=tmp_path)
    before_repo, before_outside = snapshot(repo), _outside(tmp_path)

    output = generate_threat_model(owner="o", repo="r", local_path=str(repo), output_path=output_path)

    assert output.startswith("Error: threat model not written")
    assert snapshot(repo) == before_repo
    assert _outside(tmp_path) == before_outside
    assert not (tmp_path / "escaped.md").exists()
    assert not (repo / ".git" / "escaped.md").exists()
    assert manifest.load_run(manifest.repository_identity(str(repo), "o", "r"), checkout=repo) is None


@pytest.mark.parametrize("output_path", ["docs/threatmodel/SUMMARY.md", "docs/THREAT_MODEL.md"])
def test_symlinked_directory_leading_outside_is_refused(tmp_path: Path, repo: Path, output_path: str) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / "docs").symlink_to(elsewhere)

    output = generate_threat_model(owner="o", repo="r", local_path=str(repo), output_path=output_path)

    assert "outside the repository" in output
    assert list(elsewhere.iterdir()) == []


def test_file_with_uncommitted_changes_is_not_overwritten(repo: Path) -> None:
    target = repo / "THREAT_MODEL.md"
    target.write_text("# Our threat model\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-gpg-sign", "-m", "ours")
    target.write_text("# Our threat model\n\nUnsaved review notes.\n", encoding="utf-8")

    output = generate_threat_model(owner="o", repo="r", local_path=str(repo), output_path="THREAT_MODEL.md")

    assert target.read_text(encoding="utf-8") == "# Our threat model\n\nUnsaved review notes.\n"
    assert "Not written: THREAT_MODEL.md (user_changes_present" in output
    assert "Nothing was written." in output


def test_untracked_hand_written_file_is_not_overwritten(repo: Path) -> None:
    target = repo / "THREAT_MODEL.md"
    target.write_text("# Draft\n", encoding="utf-8")

    output = generate_threat_model(owner="o", repo="r", local_path=str(repo), output_path="THREAT_MODEL.md")

    assert target.read_text(encoding="utf-8") == "# Draft\n"
    assert "Not written: THREAT_MODEL.md" in output


def test_multi_file_output_skips_a_companion_file_with_uncommitted_changes(repo: Path) -> None:
    companion = repo / "docs" / "threatmodel" / "data-flow.md"
    companion.parent.mkdir(parents=True)
    companion.write_text("# Data flow\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-gpg-sign", "-m", "data flow")
    companion.write_text("# Data flow\n\nEdited by hand.\n", encoding="utf-8")

    output = generate_threat_model(owner="o", repo="r", local_path=str(repo), output_path="docs/threatmodel/SUMMARY.md")

    assert companion.read_text(encoding="utf-8") == "# Data flow\n\nEdited by hand.\n"
    assert "Not written: docs/threatmodel/data-flow.md (user_changes_present" in output
    assert (repo / "docs" / "threatmodel" / "SUMMARY.md").is_file()


def test_written_files_are_recorded_and_committed(repo: Path) -> None:
    output = generate_threat_model(local_path=str(repo), output_path="docs/threatmodel/SUMMARY.md")

    run = manifest.load_run(manifest.repository_identity(str(repo)), checkout=repo)
    assert run is not None, output
    recorded = {f.path for f in run.files}
    assert {
        "docs/threatmodel/SUMMARY.md",
        "docs/threatmodel/data-flow.md",
        "docs/threatmodel/raw-findings.json",
    } <= recorded
    assert run.run_id in output

    (repo / "unrelated.txt").write_text("not remediation\n", encoding="utf-8")
    committed = commit_remediation_changes(local_path=str(repo), run_id=run.run_id)

    assert "Error" not in committed, committed
    in_commit = set(_git(repo, "show", "--name-only", "--format=", "HEAD").split())
    assert in_commit == recorded
    assert f"Darnit-Remediation-Run: {run.run_id}" in _git(repo, "log", "-1", "--format=%B")
    assert "?? unrelated.txt" in _git(repo, "status", "--porcelain")


def test_without_output_path_nothing_is_written(repo: Path) -> None:
    before = snapshot(repo)

    output = generate_threat_model(owner="o", repo="r", local_path=str(repo))

    assert "Threat Model" in output
    assert snapshot(repo) == before


class TestRemediationThroughTheExecutor:
    """OSPS-SA-03.02's remediation writes through the executor's single writer."""

    def _apply(self, repo: Path) -> object:
        framework = load_framework_config(BASELINE_TOML)
        remediation = framework.controls["OSPS-SA-03.02"].remediation
        assert remediation is not None

        def executor(approvals: tuple[str, ...] = ()) -> RemediationExecutor:
            return RemediationExecutor(
                local_path=str(repo),
                owner="o",
                repo="r",
                templates=framework.templates,
                framework_path=str(BASELINE_TOML),
                approvals=approvals,
            )

        preview = executor().execute("OSPS-SA-03.02", remediation, dry_run=True)
        approvals = tuple(item.digest for item in preview.plan if item.requires_individual_approval)
        return executor(approvals).execute("OSPS-SA-03.02", remediation, dry_run=False)

    def test_files_are_recorded_in_the_run_manifest(self, repo: Path) -> None:
        result = self._apply(repo)

        assert result.changed is True, result.details
        run = manifest.load_run(manifest.repository_identity(str(repo), "o", "r"), result.run_id, checkout=repo)
        assert run is not None
        assert {"docs/threatmodel/SUMMARY.md", "docs/threatmodel/data-flow.md"} <= {f.path for f in run.files}

    def test_symlinked_docs_directory_writes_nothing_outside(self, tmp_path: Path, repo: Path) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (repo / "docs").symlink_to(elsewhere)

        result = self._apply(repo)

        assert list(elsewhere.iterdir()) == []
        assert result.changed is False
