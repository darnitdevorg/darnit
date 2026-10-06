"""An audit evaluates only its own framework's controls (#442).

Controls are registered in a process-wide registry. A long-lived process (the
MCP server) audits several frameworks in turn, and each audit must see the
same control set it would see in a fresh process.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.core.utils import RecordedGhApi, set_gh_api_responder
from darnit.tools.audit import run_sieve_audit

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@pytest.fixture(autouse=True)
def offline_platform():
    previous = set_gh_api_responder(RecordedGhApi({}))
    yield
    set_gh_api_responder(previous)


def _ids(repo: Path, framework: str) -> list[str]:
    results, _ = run_sieve_audit(
        owner="o",
        repo="r",
        local_path=str(repo),
        default_branch="main",
        level=3,
        stop_on_llm=True,
        framework_name=framework,
    )
    return sorted(r["id"] for r in results)


def test_each_audit_sees_only_its_framework(repo: Path) -> None:
    reproducibility_cold = _ids(repo, "reproducibility")
    baseline = _ids(repo, "openssf-baseline")
    reproducibility_warm = _ids(repo, "reproducibility")

    assert reproducibility_cold and all(i.startswith("RE-") for i in reproducibility_cold)
    assert reproducibility_warm == reproducibility_cold
    assert not [i for i in baseline if i.startswith("RE-")]
    assert any(i.startswith("OSPS-") for i in baseline)
