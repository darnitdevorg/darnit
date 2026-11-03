"""Only a plain `darnit audit` leaves a full-audit cache (#542)."""

from __future__ import annotations

import subprocess

import pytest

from darnit.cli import main


def _repo_with_one_commit(path) -> None:
    """A commit is needed: the cache of a repository with no HEAD is always stale."""
    git = ["git", "-C", str(path), "-c", "user.name=test", "-c", "user.email=test@example.com"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "README.md").write_text("# test\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)


@pytest.mark.parametrize(
    ("flags", "cached"),
    [
        ([], True),
        (["-t", "level=1"], False),
        (["--include", "OSPS-QA-05.01"], False),
        (["--exclude", "OSPS-QA-05.01"], False),
        (["--profile", "level1_quick"], False),
    ],
)
def test_only_a_plain_audit_is_cached(tmp_path, flags, cached) -> None:
    from darnit.tools.audit import read_full_audit_cache

    _repo_with_one_commit(tmp_path)

    code = main(["audit", "-f", "openssf-baseline", "--no-fail", *flags, str(tmp_path)])

    assert code == 0
    cache = read_full_audit_cache(str(tmp_path), "openssf-baseline", level=3)
    assert (cache is not None) is cached
