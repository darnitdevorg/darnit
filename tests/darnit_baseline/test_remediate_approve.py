"""``remediate_audit_findings`` threads approvals and the operator policy to the platform engine (feature 043 T029)."""

from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path

import pytest

from darnit.core import audit_cache
from darnit.core.utils import set_gh_api_responder
from darnit.remediation import manifest
from darnit_baseline import tools
from darnit_baseline.remediation import remediate_audit_findings
from tests.darnit.remediation.platform.conftest import PLATFORM_FIXTURES, REPO_PATH, SimulatedGitHub

REPOSITORY = "github.com/o/r"
PROTECTION = f"{REPO_PATH}/branches/main/protection"


@pytest.fixture()
def failing(monkeypatch: pytest.MonkeyPatch):
    def set_failing(*control_ids: str) -> None:
        results = [{"id": cid, "status": "FAIL"} for cid in control_ids]
        monkeypatch.setattr(audit_cache, "read_audit_cache", lambda *_a, **_k: {"results": results})

    return set_failing


@pytest.fixture()
def platform():
    previous = set_gh_api_responder(None)

    def install(name: str) -> SimulatedGitHub:
        responder = SimulatedGitHub(PLATFORM_FIXTURES[name]())
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _run_block(output: str) -> dict:
    blocks = re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)
    assert blocks, output
    return json.loads(blocks[-1])


def _remediate(repo: Path, **kwargs) -> tuple[str, dict]:
    output = remediate_audit_findings(local_path=str(repo), owner="o", repo="r", **kwargs)
    return output, _run_block(output)


@pytest.mark.unit
def test_tool_takes_approve() -> None:
    params = inspect.signature(tools.remediate_audit_findings).parameters

    assert params["approve"].default is None
    assert params["dry_run"].default is True


@pytest.mark.unit
def test_preview_returns_run_id_and_change_set_digests(repo: Path, failing, platform) -> None:
    failing("OSPS-AC-03.02", "OSPS-QA-07.01")
    gh = platform("stricter")

    output, run = _remediate(repo)

    assert gh.writes == []
    assert run["mode"] == "preview"
    assert run["run_id"]
    assert run["policy"] == {"platform": "prompt", "high_impact": "prompt"}
    digests = {cs["digest"] for item in run["plan"] for cs in item["change_sets"]}
    assert len(digests) == 1, "both controls' requirements on main merge into one change set"
    assert digests <= set(re.findall(r"sha256:[0-9a-f]{64}", output.split("```json")[0]))
    assert manifest.load_run(REPOSITORY, checkout=repo) is None, "a preview writes no manifest"


@pytest.mark.unit
def test_apply_without_approval_needs_approval(repo: Path, failing, platform) -> None:
    failing("OSPS-AC-03.02")
    gh = platform("stricter")

    _, run = _remediate(repo, dry_run=False)

    assert gh.writes == []
    assert [(o["control_id"], o["kind"]) for o in run["outcomes"]] == [("OSPS-AC-03.02", "needs_approval")]
    assert run["summary"]["needs_approval"] == 1


@pytest.mark.unit
def test_apply_with_approval_writes_and_records(repo: Path, failing, platform) -> None:
    failing("OSPS-AC-03.02")
    platform("stricter")
    _, preview = _remediate(repo)
    [digest] = {cs["digest"] for item in preview["plan"] for cs in item["change_sets"]}
    gh = platform("stricter")

    _, run = _remediate(repo, dry_run=False, approve=[digest])

    assert [(w.method, w.endpoint) for w in gh.writes] == [("PUT", PROTECTION)]
    [outcome] = run["outcomes"]
    assert outcome["kind"] in ("fixed", "changed_not_passing", "changed_not_verified")
    assert outcome["kind"] != "fixed" or outcome["recheck"]["status"] == "PASS"
    assert [a["digest"] for a in run["approvals"]] == [digest]
    recorded = manifest.load_run(REPOSITORY, run["run_id"], checkout=repo)
    assert recorded.change_sets == [digest]


@pytest.mark.unit
def test_high_impact_needs_its_own_digest(repo: Path, failing, platform) -> None:
    failing("OSPS-QA-01.01")
    gh = platform("private_repo")

    _, preview = _remediate(repo)
    [item] = [i for i in preview["plan"] if i["change_sets"]]
    assert item["requires_individual_approval"] is True
    assert item["change_sets"][0]["impact_notes"]

    _, run = _remediate(repo, dry_run=False, approve=[item["digest"]])

    assert gh.writes == [], "a plan-item digest does not approve the change set inside it"
    assert run["outcomes"][0]["kind"] in ("needs_approval", "unchanged")
