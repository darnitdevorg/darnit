"""The URL naming the audited repository keeps its host and namespace (#155).

Attestations and badge URLs used to be built as ``https://github.com/{owner}/{repo}``
whatever the repository's host: an explicit ``host``, or a GitLab remote whose
subgroup the owner/repo parser drops, still produced a github.com URL.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from darnit_baseline import tools
from darnit_baseline.tools import _detect_repository, _repository_url


@pytest.fixture(autouse=True)
def _no_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("darnit.core.utils._gh_enrich", lambda *_args: {})


def _checkout(tmp_path: Path, **remotes: str) -> Path:
    repo = tmp_path / "checkout"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, url in remotes.items():
        subprocess.run(["git", "-C", str(repo), "remote", "add", name, url], check=True)
    return repo


@pytest.mark.unit
class TestRepositoryUrl:
    def test_named_repository_wins(self) -> None:
        detected = ("me", "proj", "github.com/me/proj")
        assert _repository_url("gitlab.com/org/proj", "org", "proj", detected) == "https://gitlab.com/org/proj"

    def test_gitlab_remote_keeps_host_and_subgroup(self, tmp_path: Path) -> None:
        repo = _checkout(tmp_path, origin="git@gitlab.com:group/sub/proj.git")
        detected = _detect_repository(repo)
        owner, name, _identity = detected
        assert _repository_url(None, owner, name, detected) == "https://gitlab.com/group/sub/proj"

    def test_github_remote_is_unchanged(self, tmp_path: Path) -> None:
        repo = _checkout(tmp_path, origin="https://github.com/octo/hello.git")
        detected = _detect_repository(repo)
        assert detected[:2] == ("octo", "hello")
        assert _repository_url(None, "octo", "hello", detected) == "https://github.com/octo/hello"

    def test_identity_of_another_repository_is_not_used(self) -> None:
        """An owner or repo the caller gave without the other is not the remote's repository."""
        detected = ("me", "proj", "gitlab.com/me/proj")
        assert _repository_url(None, "other", "proj", detected) == "https://github.com/other/proj"

    def test_no_remote_falls_back_to_the_directory_name(self, tmp_path: Path) -> None:
        repo = _checkout(tmp_path)
        assert _detect_repository(repo) == ("", "checkout", None)


@pytest.mark.unit
def test_generate_attestation_names_the_given_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """generate_attestation(host=...) puts that host in the subject and the predicate."""
    repo = _checkout(tmp_path, origin="https://github.com/me/proj.git")
    seen: dict = {}

    def fake_generate(audit_result, **_kwargs) -> str:
        seen["url"] = audit_result.repository_url
        return json.dumps({"ok": True})

    monkeypatch.setattr("darnit.tools.audit.run_sieve_audit", lambda **_kwargs: ([], {}))
    monkeypatch.setattr("darnit_baseline.attestation.generate_attestation_from_results", fake_generate)
    monkeypatch.setattr(tools, "_detect_default_branch", lambda _path: "main")

    tools.generate_attestation(owner="org", repo="proj", host="gitlab.example.org", local_path=str(repo), sign=False)

    assert seen["url"] == "https://gitlab.example.org/org/proj"
