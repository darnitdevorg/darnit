"""gittuf controls through the canonical audit pipeline, with real git."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's git configuration out of these repositories."""
    global_config = tmp_path_factory.mktemp("home") / "gitconfig"
    global_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{name}_NAME", "Test")
        monkeypatch.setenv(f"{name}_EMAIL", "test@example.com")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")
    return repo


def _audit(path: Path, control_id: str) -> dict:
    from darnit_gittuf.implementation import GittufImplementation

    from darnit.config import load_controls_from_framework
    from darnit.config.merger import load_framework_config
    from darnit.tools.audit import run_sieve_audit

    config = load_framework_config(GittufImplementation().get_framework_config_path())
    controls = [c for c in load_controls_from_framework(config) if c.control_id == control_id]
    results, _ = run_sieve_audit(
        "testorg",
        "testrepo",
        str(path),
        "main",
        controls=controls,
        evaluate_claims=False,
        stop_on_llm=False,
        framework_name="gittuf",
        write_cache=False,
    )
    (result,) = results
    return result


class TestGittufPolicyValid:
    """GT-01.02: gittuf verify-ref HEAD."""

    def test_missing_gittuf_is_a_missing_tool_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _repo(tmp_path)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        os.symlink(shutil.which("git"), bin_dir / "git")
        monkeypatch.setenv("PATH", str(bin_dir))

        result = _audit(repo, "GT-01.02")

        assert result["status"] == "ERROR"
        assert result["error"]["class"] == "missing_tool"
