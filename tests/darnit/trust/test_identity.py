"""Canonical repository identity (feature 040, research R3)."""

from __future__ import annotations

import pytest

from darnit.trust.identity import IdentitySource, RepositoryIdentity, canonical_identity


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Example/Project",
        "https://github.com/example/project.git",
        "https://user@github.com:443/example/project.git",
        "http://GitHub.com/example/project/",
        "git@github.com:Example/Project.git",
        "ssh://git@github.com/example/project",
        "ssh://git@github.com:22/example/project.git",
        "github.com/example/project",
    ],
)
def test_github_forms_normalize_to_one_identity(url: str) -> None:
    assert canonical_identity(url) == "github.com/example/project"


@pytest.mark.unit
def test_gitlab_nested_groups_are_kept() -> None:
    assert canonical_identity("git@gitlab.com:Group/Sub/Proj.git") == "gitlab.com/group/sub/proj"


@pytest.mark.unit
def test_unknown_host_path_case_is_preserved() -> None:
    """Only hosts known (or declared) to be case-insensitive are folded."""
    assert canonical_identity("https://git.example.com/Team/Repo.git") == "git.example.com/Team/Repo"


@pytest.mark.unit
def test_operator_declared_case_insensitive_host_is_folded() -> None:
    assert (
        canonical_identity("https://git.example.com/Team/Repo.git", case_insensitive_hosts=["GIT.example.com"])
        == "git.example.com/team/repo"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    ["", "not a url", "https://github.com/onlyowner", "file:///tmp/repo", "https://github.com//repo", "../x/y"],
)
def test_unparseable_inputs_return_none(bad: str) -> None:
    assert canonical_identity(bad) is None


@pytest.mark.unit
def test_trusted_eligibility_depends_on_source() -> None:
    assert RepositoryIdentity("github.com/a/b", IdentitySource.OPERATOR_TARGET).trusted_eligible
    assert RepositoryIdentity("github.com/a/b", IdentitySource.CI_METADATA).trusted_eligible
    assert not RepositoryIdentity("github.com/a/b", IdentitySource.CHECKOUT_HINT).trusted_eligible
