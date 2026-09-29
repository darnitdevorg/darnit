"""Confirmations are recorded with who, when, basis, and validity (feature 042, US4, FR-009, FR-011, FR-012, FR-022)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from darnit.config.context_keys import value_digest
from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import OriginKind, Standing
from darnit.server.tools.project_data import confirm_project_data_impl
from darnit.trust.confirmations import CONTEXT_VALUE_CLAIM, load_confirmations

from .conftest import assert_unchanged, snapshot, write_operator_config

OWNER = "example-org"
REPO = "r-maint"
IDENTITY = f"github.com/{OWNER}/{REPO}"
MAINTAINERS = ["@alice", "@bob"]


def _confirm(repo: Path, **kwargs) -> str:
    kwargs.setdefault("owner", OWNER)
    kwargs.setdefault("repo", REPO)
    return confirm_project_data_impl(local_path=str(repo), framework_name="openssf-baseline", **kwargs)


def _extension(repo: Path) -> dict:
    return yaml.safe_load((repo / ".project" / "darnit.yaml").read_text())


@pytest.fixture
def r_maint(scratch_repo) -> Path:
    return scratch_repo("R-maint")


@pytest.mark.integration
class TestLocation:
    def test_trusted_target_records_in_the_repository(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY], identity="alice")

        message = _confirm(r_maint, maintainers=MAINTAINERS)

        assert "maintainers: confirmed (in-repository), recorded in .project/darnit.yaml" in message
        data = _extension(r_maint)
        assert data["context"]["maintainers"] == MAINTAINERS
        record = data["confirmations"]["maintainers"]
        assert record["value_digest"] == value_digest("maintainers", MAINTAINERS)
        assert record["confirmed_by"] == "alice"
        assert record["confirmed_at"] == record["last_validated"]
        assert "basis" not in record
        assert "expires_at" not in record
        assert load_confirmations() == []

    def test_untrusted_target_records_operator_side_only(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", identity="alice")
        before = snapshot(r_maint)

        message = _confirm(r_maint, maintainers=MAINTAINERS)

        assert "maintainers: confirmed (operator-side)" in message
        assert ".project/darnit.yaml" not in message
        assert_unchanged(r_maint, before)
        [confirmation] = load_confirmations(IDENTITY)
        assert confirmation.claim == CONTEXT_VALUE_CLAIM
        assert confirmation.control_id == "maintainers"
        assert confirmation.evidence_digest == value_digest("maintainers", MAINTAINERS)
        assert confirmation.confirmed_by == "alice"

    @pytest.mark.parametrize("names", [{}, {"owner": None}, {"repo": None}])
    @pytest.mark.parametrize("trusted", [True, False])
    def test_missing_owner_or_repo_refuses(self, r_maint: Path, tmp_path: Path, names: dict, trusted: bool) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY] if trusted else [])
        before = snapshot(r_maint)

        message = confirm_project_data_impl(
            local_path=str(r_maint),
            framework_name="openssf-baseline",
            maintainers=MAINTAINERS,
            **({"owner": OWNER, "repo": REPO} | names if names else {}),
        )

        assert "maintainers: refused:" in message
        assert "owner" in message and "repo" in message
        assert "confirmed" not in message
        assert_unchanged(r_maint, before)
        assert load_confirmations() == []


@pytest.mark.integration
class TestExpiry:
    def test_expires_at_is_recorded_in_the_repository(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])

        message = _confirm(r_maint, maintainers=MAINTAINERS, expires_at={"maintainers": "2099-09-29"})

        assert "maintainers: confirmed (in-repository)" in message
        assert "expires 2099-09-29T00:00:00Z" in message
        assert _extension(r_maint)["confirmations"]["maintainers"]["expires_at"] == "2099-09-29T00:00:00Z"

    def test_expires_at_is_recorded_operator_side(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml")

        _confirm(r_maint, maintainers=MAINTAINERS, expires_at={"maintainers": "2099-09-29T12:00:00Z"})

        [confirmation] = load_confirmations(IDENTITY)
        assert confirmation.expires_at == "2099-09-29T12:00:00Z"

    @pytest.mark.parametrize("expiry", ["not-a-date", "2000-01-01"])
    def test_unusable_expiry_refuses_the_key(self, r_maint: Path, tmp_path: Path, expiry: str) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        before = snapshot(r_maint)

        message = _confirm(r_maint, maintainers=MAINTAINERS, expires_at={"maintainers": expiry})

        assert "maintainers: refused:" in message
        assert_unchanged(r_maint, before)

    def test_expiry_for_a_key_not_being_confirmed_is_refused(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])

        message = _confirm(r_maint, maintainers=MAINTAINERS, expires_at={"governance_model": "2099-01-01"})

        assert "maintainers: confirmed (in-repository)" in message
        assert "governance_model: refused:" in message
        assert "governance_model" not in _extension(r_maint)["confirmations"]


@pytest.mark.integration
class TestReconfirmation:
    def _age_record(self, repo: Path, **fields: str) -> None:
        path = repo / ".project" / "darnit.yaml"
        data = yaml.safe_load(path.read_text())
        data["confirmations"]["maintainers"].update(fields)
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def test_updates_last_validated_and_keeps_a_project_set_expiry(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        _confirm(r_maint, maintainers=MAINTAINERS)
        self._age_record(
            r_maint,
            confirmed_at="2026-01-01T00:00:00Z",
            last_validated="2026-01-01T00:00:00Z",
            expires_at="2099-01-01T00:00:00Z",
        )

        _confirm(r_maint, maintainers=list(reversed(MAINTAINERS)))

        record = _extension(r_maint)["confirmations"]["maintainers"]
        assert record["confirmed_at"] == "2026-01-01T00:00:00Z"
        assert record["last_validated"] > "2026-01-01T00:00:00Z"
        assert record["expires_at"] == "2099-01-01T00:00:00Z"

    def test_a_new_expiry_replaces_the_project_set_one(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        _confirm(r_maint, maintainers=MAINTAINERS)
        self._age_record(r_maint, expires_at="2099-01-01T00:00:00Z")

        _confirm(r_maint, maintainers=MAINTAINERS, expires_at={"maintainers": "2098-06-30"})

        assert _extension(r_maint)["confirmations"]["maintainers"]["expires_at"] == "2098-06-30T00:00:00Z"

    def test_an_expired_confirmation_is_revalidated(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        _confirm(r_maint, maintainers=MAINTAINERS)
        self._age_record(r_maint, expires_at="2000-01-01T00:00:00Z")
        resolved = resolve_context(str(r_maint), detect=False).get("maintainers")
        assert resolved.standing is Standing.CANDIDATE
        assert resolved.origin.kind is OriginKind.EXPIRED_CONFIRMATION

        message = _confirm(r_maint, confirm_stored=["maintainers"], expires_at={"maintainers": "2099-01-01"})

        assert "maintainers: confirmed (in-repository)" in message
        assert resolve_context(str(r_maint), detect=False).get("maintainers").standing is Standing.CONFIRMED


@pytest.mark.integration
def test_hand_edit_makes_the_key_a_candidate_with_the_lapsed_record(r_maint: Path, tmp_path: Path) -> None:
    write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
    _confirm(r_maint, maintainers=MAINTAINERS)
    path = r_maint / ".project" / "darnit.yaml"
    path.write_text(path.read_text().replace("'@bob'", "'@mallory'").replace("@bob", "@mallory"))

    resolved = resolve_context(str(r_maint), detect=False).get("maintainers")

    assert resolved.standing is Standing.CANDIDATE
    assert resolved.origin.kind is OriginKind.STORED_UNCONFIRMED
    assert resolved.value == ["@alice", "@mallory"]
    assert resolved.lapsed is not None
    assert resolved.lapsed.value_digest == value_digest("maintainers", MAINTAINERS)


_STANDING_SCRIPT = """
import json, sys
from pathlib import Path
from darnit.config.operator.loader import set_launch_options
from darnit.trust import confirmations
from darnit.config.context_resolve import resolve_context

repo, operator_config, data_root, target = sys.argv[1:5]
confirmations.user_data_root = lambda: Path(data_root)
set_launch_options(operator_config, strict=False)
resolved = resolve_context(repo, target=target, detect=False)
print(json.dumps({key: [v.standing.value, v.value, v.origin.kind.value if v.origin else None,
                        v.confirmation.location if v.confirmation else None]
                  for key, v in sorted(resolved.values.items())}))
"""


def _standing(repo: Path, target: str) -> dict:
    resolved = resolve_context(str(repo), target=target, detect=False)
    return {
        key: [
            v.standing.value,
            v.value,
            v.origin.kind.value if v.origin else None,
            v.confirmation.location if v.confirmation else None,
        ]
        for key, v in sorted(resolved.values.items())
    }


@pytest.mark.integration
def test_a_new_process_reads_identical_standing(scratch_repo, tmp_path: Path) -> None:
    """SC-006: confirmed (in-repository and operator-side) and candidate values read the same in a new process."""
    from darnit.trust import confirmations

    repo = scratch_repo("R-legacy")
    identity = "github.com/example-org/r-legacy"
    write_operator_config(tmp_path / "trusting.toml", trusted=[identity])
    confirm_project_data_impl(
        local_path=str(repo), framework_name="openssf-baseline", owner=OWNER, repo="r-legacy", governance_model="bdfl"
    )
    untrusting = write_operator_config(tmp_path / "untrusting.toml")
    confirm_project_data_impl(
        local_path=str(repo), framework_name="openssf-baseline", owner=OWNER, repo="r-legacy", is_library=True
    )
    target = identity

    here = _standing(repo, target)
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            _STANDING_SCRIPT,
            str(repo),
            str(untrusting),
            str(confirmations.user_data_root()),
            target,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(process.stdout) == here
    assert here["governance_model"] == ["confirmed", "bdfl", None, "repository"]
    assert here["is_library"] == ["confirmed", True, None, "operator"]
    assert here["maintainers"][0] == "candidate"
    assert here["maintainers"][2] == "stored_unconfirmed"
    assert here["has_releases"][:3] == ["candidate", False, "stored_unconfirmed"]
