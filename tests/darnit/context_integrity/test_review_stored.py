"""One-step review of values stored without a confirmation (feature 042, US4, FR-010, research R5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import OriginKind, Standing
from darnit.server.tools.project_data import confirm_project_data_impl
from darnit.trust.confirmations import load_confirmations

from .conftest import assert_unchanged, snapshot, write_operator_config

OWNER = "example-org"
REPO = "r-legacy"
IDENTITY = f"github.com/{OWNER}/{REPO}"
CONTACT = "security@legacy.example.net"


@pytest.fixture
def r_legacy(scratch_repo) -> Path:
    repo = scratch_repo("R-legacy")
    project = repo / ".project" / "project.yaml"
    project.write_text(project.read_text() + f"security:\n  contact: {CONTACT}\n")
    return repo


def _pending(repo: Path) -> dict:
    from darnit_baseline.tools import get_pending_data

    result = get_pending_data(local_path=str(repo), owner=OWNER, repo=REPO, limit=0)
    return json.loads(result.split("\n---\n", 1)[-1])


def _review(repo: Path, **kwargs) -> str:
    return confirm_project_data_impl(
        local_path=str(repo), framework_name="openssf-baseline", owner=OWNER, repo=REPO, **kwargs
    )


@pytest.mark.integration
def test_get_pending_data_lists_stored_values_with_locations(r_legacy: Path, tmp_path: Path) -> None:
    write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
    before = snapshot(r_legacy)

    stored = {entry["key"]: entry for entry in _pending(r_legacy)["stored_unconfirmed"]}

    assert stored == {
        "maintainers": {
            "key": "maintainers",
            "value": ["@alice", "@realcorp"],
            "location": ".project/darnit.yaml:context.maintainers",
        },
        "has_releases": {
            "key": "has_releases",
            "value": False,
            "location": ".project/darnit.yaml:context.has_releases",
        },
        "ci_provider": {
            "key": "ci_provider",
            "value": "github",
            "location": ".project/darnit.yaml:context.ci_provider",
        },
        "security_contact": {
            "key": "security_contact",
            "value": CONTACT,
            "location": ".project/project.yaml:security.contact",
        },
    }
    assert_unchanged(r_legacy, before)


@pytest.mark.integration
class TestOneCall:
    def test_confirms_some_and_rejects_others(self, r_legacy: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        project_before = (r_legacy / ".project" / "project.yaml").read_bytes()

        message = _review(
            r_legacy,
            confirm_stored=["maintainers", "ci_provider"],
            reject_stored=["has_releases", "security_contact"],
        )

        assert "maintainers: confirmed (in-repository), recorded in .project/darnit.yaml" in message
        assert "ci_provider: confirmed (in-repository), recorded in .project/darnit.yaml" in message
        assert "has_releases: rejected, deleted from .project/darnit.yaml" in message
        assert "security_contact: edit required: .project/project.yaml:security.contact" in message

        data = yaml.safe_load((r_legacy / ".project" / "darnit.yaml").read_text())
        assert "has_releases" not in data["context"]
        assert data["context"]["ci_provider"] == "github"
        assert data["controls"]["OSPS-BR-02.01"]["status"] == "n/a"
        for key, location in (
            ("maintainers", ".project/darnit.yaml:context.maintainers"),
            ("ci_provider", ".project/darnit.yaml:context.ci_provider"),
        ):
            assert data["confirmations"][key]["basis"]["origin"] == {"kind": "stored_unconfirmed", "method": location}
        assert (r_legacy / ".project" / "project.yaml").read_bytes() == project_before

        resolved = resolve_context(str(r_legacy), detect=False)
        assert resolved.get("maintainers").standing is Standing.CONFIRMED
        assert resolved.get("ci_provider").standing is Standing.CONFIRMED
        assert resolved.get("has_releases").standing is Standing.UNKNOWN
        contact = resolved.get("security_contact")
        assert contact.standing is Standing.CANDIDATE
        assert contact.origin.kind is OriginKind.STORED_UNCONFIRMED
        assert [entry["key"] for entry in _pending(r_legacy)["stored_unconfirmed"]] == ["security_contact"]

    def test_untrusted_target_confirms_operator_side_and_rejects_nothing(self, r_legacy: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml")
        before = snapshot(r_legacy)

        message = _review(r_legacy, confirm_stored=["maintainers"], reject_stored=["has_releases"])

        assert "maintainers: confirmed (operator-side)" in message
        assert "has_releases: refused:" in message
        assert ".project/darnit.yaml:context.has_releases" in message
        assert_unchanged(r_legacy, before)
        assert [c.control_id for c in load_confirmations(IDENTITY)] == ["maintainers"]

    def test_a_key_without_a_stored_value_is_refused(self, r_legacy: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        before = snapshot(r_legacy)

        message = _review(r_legacy, confirm_stored=["governance_model"], reject_stored=["is_library"])

        assert "governance_model: refused: no stored value" in message
        assert "is_library: refused: no stored value" in message
        assert_unchanged(r_legacy, before)

    def test_a_key_both_confirmed_and_rejected_is_refused(self, r_legacy: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        before = snapshot(r_legacy)

        message = _review(r_legacy, confirm_stored=["maintainers"], reject_stored=["maintainers"])

        assert "maintainers: refused:" in message
        assert_unchanged(r_legacy, before)
