"""A Baseline audit narrowed by a profile is not cached as a full audit (#542)."""

from __future__ import annotations

import subprocess

import pytest


def _repo_with_one_commit(path) -> None:
    """A commit is needed: the cache of a repository with no HEAD is always stale."""
    git = ["git", "-C", str(path), "-c", "user.name=test", "-c", "user.email=test@example.com"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "README.md").write_text("# test\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)


@pytest.mark.parametrize(("profile", "cached"), [("level1_quick", False), (None, True)])
def test_only_an_unfiltered_audit_is_cached(tmp_path, profile, cached) -> None:
    from darnit.tools.audit import read_full_audit_cache
    from darnit_baseline.tools import audit_openssf_baseline

    _repo_with_one_commit(tmp_path)

    audit_openssf_baseline(local_path=str(tmp_path), profile=profile, auto_init_config=False)

    cache = read_full_audit_cache(str(tmp_path), "openssf-baseline", level=3)
    assert (cache is not None) is cached
