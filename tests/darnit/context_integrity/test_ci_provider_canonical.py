"""One name and one vocabulary for the CI provider (feature 042, US5, FR-018)."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import OriginKind, Standing
from darnit.config.discovery import discover_ci_config
from darnit.config.loader import load_project_config
from darnit.context import detectors
from darnit.context.auto_detect import collect_auto_context, detect_ci_provider
from darnit.server.tools.project_data import confirm_project_data_impl
from darnit_baseline.tools import audit_openssf_baseline

from .conftest import write_operator_config

OWNER = "example-org"


def _framework() -> dict:
    return tomllib.loads((files("darnit_baseline") / "openssf-baseline.toml").read_text(encoding="utf-8"))


def _vocabulary() -> list[str]:
    return _framework()["context"]["ci_provider"]["values"]


def _ci_gated_controls() -> set[str]:
    return {
        control_id
        for control_id, control in _framework()["controls"].items()
        if "ci_provider" in (control.get("when") or {})
    }


@pytest.mark.integration
def test_confirming_an_unrelated_key_stores_only_the_canonical_ci_provider(
    scratch_repo: Callable[[str], Path], tmp_path: Path
) -> None:
    repo = scratch_repo("R-ci")
    write_operator_config(tmp_path / "operator.toml", trusted=[f"github.com/{OWNER}/r-ci"])

    message = confirm_project_data_impl(
        local_path=str(repo), framework_name="openssf-baseline", owner=OWNER, repo="r-ci", governance_model="bdfl"
    )

    assert "governance_model: confirmed (in-repository)" in message
    data = yaml.safe_load((repo / ".project" / "darnit.yaml").read_text(encoding="utf-8"))
    assert data["context"].get("ci_provider", "github") == "github"
    assert "provider" not in data["context"]
    assert (data.get("ci") or {}).get("provider", "github") == "github"


@pytest.mark.integration
def test_ci_controls_stay_applicable(scratch_repo: Callable[[str], Path], tmp_path: Path) -> None:
    repo = scratch_repo("R-ci")
    write_operator_config(tmp_path / "operator.toml", trusted=[f"github.com/{OWNER}/r-ci"])
    confirm_project_data_impl(
        local_path=str(repo), framework_name="openssf-baseline", owner=OWNER, repo="r-ci", governance_model="bdfl"
    )
    gated = _ci_gated_controls()
    assert gated

    payload = audit_openssf_baseline(local_path=str(repo), level=3, output_format="json")
    results = {r["id"]: r["status"] for r in json.loads(payload[payload.index("{") :])["results"]}

    assert gated <= results.keys()
    assert {control_id: results[control_id] for control_id in gated if results[control_id] == "N/A"} == {}


@pytest.mark.integration
def test_legacy_spelling_reads_as_canonical(scratch_repo: Callable[[str], Path]) -> None:
    repo = scratch_repo("R-legacy")

    resolved = resolve_context(str(repo), detect=False).get("ci_provider")

    assert resolved.value == "github"
    assert resolved.standing is Standing.CANDIDATE
    assert resolved.origin.kind is OriginKind.STORED_UNCONFIRMED
    assert load_project_config(str(repo)).get_ci_provider() == "github"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"ci": {"provider": "github_actions"}}, "github"),
        ({"ci": {"provider": "gitlab_ci"}}, "gitlab"),
        ({"context": {"ci_provider": "azure_pipelines"}}, "azure"),
        ({"context": {"ci_provider": "unknown"}}, None),
        ({"context": {"ci_provider": "gitlab"}, "ci": {"provider": "github_actions"}}, "gitlab"),
    ],
)
def test_get_ci_provider_reads_the_canonical_vocabulary(tmp_path: Path, stored: dict, expected: str | None) -> None:
    project = tmp_path / ".project"
    project.mkdir()
    (project / "project.yaml").write_text("name: legacy\n", encoding="utf-8")
    (project / "darnit.yaml").write_text(yaml.safe_dump(stored), encoding="utf-8")

    assert load_project_config(str(tmp_path)).get_ci_provider() == expected


CI_LAYOUTS = {
    ".github/workflows/ci.yml": "github",
    ".gitlab-ci.yml": "gitlab",
    "Jenkinsfile": "jenkins",
    ".circleci/config.yml": "circleci",
    "azure-pipelines.yml": "azure",
    ".travis.yml": "travis",
}


@pytest.mark.unit
@pytest.mark.parametrize(("path", "provider"), list(CI_LAYOUTS.items()))
def test_every_detection_route_uses_the_canonical_vocabulary(tmp_path: Path, path: str, provider: str) -> None:
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text("x: 1\n", encoding="utf-8")

    assert provider in _vocabulary()
    assert detect_ci_provider(str(tmp_path)) == provider
    assert collect_auto_context(str(tmp_path), include_stored=False)["ci_provider"] == provider
    discovered = discover_ci_config(str(tmp_path))
    assert discovered is None or discovered.provider in _vocabulary()


@pytest.mark.unit
def test_one_ci_detector() -> None:
    assert not hasattr(detectors, "detect_ci")
