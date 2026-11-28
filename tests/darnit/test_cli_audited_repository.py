"""`darnit audit` says which repository it audited and where that came from (#344).

On a fork checkout the platform checks ask about whichever remote names the
repository. The text report and the JSON output both name it, with the
source: ``--repo``, the git remote, or none.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from darnit.cli import audited_repository, format_audited_repository, format_results_text
from darnit.cli import main as cli_main


@pytest.fixture(autouse=True)
def _no_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("darnit.core.utils._gh_enrich", lambda *_args: {})


def _repo(tmp_path: Path, **remotes: str) -> Path:
    repo = tmp_path / "checkout"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, url in remotes.items():
        subprocess.run(["git", "-C", str(repo), "remote", "add", name, url], check=True)
    return repo


def test_fork_checkout_names_origin(tmp_path: Path) -> None:
    repo = _repo(tmp_path, origin="https://github.com/me/darnit.git", upstream="https://github.com/org/darnit.git")
    repository = audited_repository(repo, None)
    assert repository == {"owner": "me", "repo": "darnit", "source": "origin", "path": str(repo)}
    assert format_audited_repository(repository) == f"Repository: me/darnit (from git remote 'origin'), checkout {repo}"


def test_upstream_only_names_upstream(tmp_path: Path) -> None:
    repo = _repo(tmp_path, upstream="https://github.com/org/darnit.git")
    assert audited_repository(repo, None)["source"] == "upstream"


def test_repo_flag_wins_and_is_named(tmp_path: Path) -> None:
    repo = _repo(tmp_path, origin="https://github.com/me/darnit.git")
    repository = audited_repository(repo, "github.com/org/darnit")
    assert repository == {"owner": "org", "repo": "darnit", "source": "--repo", "path": str(repo)}
    assert "org/darnit (from --repo)" in format_audited_repository(repository)


def test_no_remote_says_no_owner_is_known(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repository = audited_repository(repo, None)
    assert repository == {"owner": "", "repo": "checkout", "source": "none", "path": str(repo)}
    line = format_audited_repository(repository)
    assert line.startswith(f"Repository: {repo} (no owner known")
    assert "platform checks that need it cannot run" in line


def test_text_report_names_repository_under_the_title() -> None:
    repository = {"owner": "me", "repo": "darnit", "source": "origin", "path": "/src/darnit"}
    lines = format_results_text([], "openssf-baseline", repository=repository).splitlines()
    assert lines[1] == "=== openssf-baseline Audit Results ==="
    assert lines[3] == "Repository: me/darnit (from git remote 'origin'), checkout /src/darnit"


def test_text_report_without_repository_is_unchanged() -> None:
    assert "Repository:" not in format_results_text([], "openssf-baseline")


@pytest.mark.parametrize("output", ["json", "text"])
def test_cli_audit_reports_the_repository(tmp_path: Path, capsys: pytest.CaptureFixture[str], output: str) -> None:
    repo = _repo(tmp_path, origin="https://github.com/me/darnit.git", upstream="https://github.com/org/darnit.git")
    cli_main(["audit", str(repo), "-f", "openssf-baseline", "--include", "OSPS-DO-01.01", "-o", output, "--no-fail"])
    out = capsys.readouterr().out
    if output == "json":
        assert json.loads(out)["repository"] == {"owner": "me", "repo": "darnit", "source": "origin", "path": str(repo)}
    else:
        assert f"Repository: me/darnit (from git remote 'origin'), checkout {repo}" in out
