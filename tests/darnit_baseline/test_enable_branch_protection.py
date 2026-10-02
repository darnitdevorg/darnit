"""``enable_branch_protection`` is a thin, preview-by-default wrapper over the platform engine (feature 043 T020; FR-001, FR-009)."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from darnit.core.utils import set_gh_api_responder
from darnit.remediation.executor import RemediationExecutor
from darnit.remediation.github import enable_branch_protection as core_enable
from darnit_baseline.remediation.orchestrator import _get_framework_config
from darnit_baseline.tools import enable_branch_protection
from tests.darnit.remediation.platform.conftest import PLATFORM_FIXTURES, REPO_PATH, SimulatedGitHub

PROTECTION = f"{REPO_PATH}/branches/main/protection"


@pytest.fixture()
def simulated_gh():
    previous = set_gh_api_responder(None)

    def install(name: str) -> SimulatedGitHub:
        responder = SimulatedGitHub(PLATFORM_FIXTURES[name]())
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)


def _run(local_path: Path, **kwargs) -> tuple[str, dict]:
    output = enable_branch_protection(owner="o", repo="r", local_path=str(local_path), **kwargs)
    blocks = re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)
    assert blocks, output
    return output, json.loads(blocks[-1])


def _change_sets(run: dict) -> list[dict]:
    return [cs for item in run["plan"] for cs in item["change_sets"]]


@pytest.mark.unit
def test_signature_defaults_preview_the_default_branch() -> None:
    for fn in (enable_branch_protection, core_enable):
        params = inspect.signature(fn).parameters
        assert params["dry_run"].default is True, "FR-001: platform tools preview unless asked to apply"
        assert params["branch"].default is None, "FR-007: the default branch comes from the platform"
        assert params["approve"].default is None


@pytest.mark.unit
def test_default_call_previews_only(tmp_path: Path, simulated_gh) -> None:
    gh = simulated_gh("stricter")

    output, run = _run(tmp_path)

    assert gh.writes == []
    assert run["mode"] == "preview"
    [change_set] = _change_sets(run)
    assert change_set["digest"].startswith("sha256:")
    assert change_set["digest"] in output
    assert run["policy"] == {"platform": "prompt", "high_impact": "prompt"}


@pytest.mark.unit
def test_branch_none_uses_the_default_branch(tmp_path: Path, simulated_gh) -> None:
    simulated_gh("default_branch_release")

    _, run = _run(tmp_path)

    [change_set] = _change_sets(run)
    assert change_set["target"]["branch"] == "release"


@pytest.mark.unit
def test_required_approvals_never_lowers_an_existing_count(tmp_path: Path, simulated_gh) -> None:
    gh = simulated_gh("stricter")

    _, preview = _run(tmp_path, required_approvals=1)
    [change_set] = _change_sets(preview)
    fields = {c["field"] for op in change_set["operations"] for c in op["changes"]}
    assert not any("required_approving_review_count" in f for f in fields)

    _, applied = _run(tmp_path, required_approvals=1, dry_run=False, approve=change_set["digest"])

    assert applied["outcomes"][0]["kind"] == "fixed"
    assert gh.protection()["required_pull_request_reviews"]["required_approving_review_count"] == 2


@pytest.mark.unit
def test_status_checks_only_add(tmp_path: Path, simulated_gh) -> None:
    gh = simulated_gh("stricter")

    _, preview = _run(tmp_path, require_status_checks=True, status_checks=["ci/lint"])
    [change_set] = _change_sets(preview)
    posts = [op for op in change_set["operations"] if op["endpoint"].endswith("/required_status_checks/contexts")]
    assert [op["body"] for op in posts] == [{"contexts": ["ci/lint"]}]

    _run(tmp_path, require_status_checks=True, status_checks=["ci/lint"], dry_run=False, approve=change_set["digest"])

    contexts = gh.protection()["required_status_checks"]["contexts"]
    assert set(contexts) == {"ci/build", "ci/test", "ci/lint"}


@pytest.mark.unit
def test_apply_without_approval_under_prompt_writes_nothing(tmp_path: Path, simulated_gh) -> None:
    gh = simulated_gh("stricter")

    _, run = _run(tmp_path, dry_run=False)

    assert gh.writes == []
    assert run["outcomes"][0]["kind"] == "needs_approval"


@pytest.mark.unit
def test_tool_and_toml_produce_the_same_change_set(tmp_path: Path, simulated_gh) -> None:
    simulated_gh("unprotected")
    framework = _get_framework_config()
    remediation = framework.controls["OSPS-AC-03.01"].remediation

    result = RemediationExecutor(local_path=str(tmp_path), owner="o", repo="r").execute(
        "OSPS-AC-03.01", remediation, dry_run=True
    )
    toml_sets = [cs for item in result.plan for cs in item.change_sets]
    _, run = _run(
        tmp_path,
        require_pull_request=True,
        required_approvals=0,
        enforce_admins=False,
        prevent_deletion=False,
        prevent_force_push=False,
    )

    assert [cs["digest"] for cs in toml_sets] == [cs["digest"] for cs in _change_sets(run)]
    assert toml_sets[0]["operations"] == _change_sets(run)[0]["operations"]
