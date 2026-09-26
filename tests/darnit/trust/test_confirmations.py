"""Operator-side confirmation store (feature 040, US3, T044, FR-019, FR-019a)."""

from __future__ import annotations

import getpass
import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from darnit.config.operator.schema import OperatorConfig
from darnit.trust import confirmations
from darnit.trust.confirmations import find_confirmation, load_confirmations, record_confirmation

REPO = "github.com/example/repo"
CONTROL = "OSPS-BR-02.01"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data" / "darnit"
    monkeypatch.setattr(confirmations, "user_data_root", lambda: root)
    return root


def _operator(**data: object) -> OperatorConfig:
    return OperatorConfig.model_validate({"schema_version": 1, **data})


def _record(**kwargs: object):
    args: dict = {
        "repository": REPO,
        "control_id": CONTROL,
        "claim": "not_applicable",
        "evidence_digest": "d1",
        "operator": _operator(),
        "now": NOW,
    }
    args.update(kwargs)
    return record_confirmation(**args)


@pytest.mark.unit
class TestConfirmationStore:
    def test_stored_under_the_data_root(self, data_root: Path) -> None:
        _record()

        path = data_root / "trust" / "confirmations.json"
        stored = json.loads(path.read_text(encoding="utf-8"))["confirmations"]
        assert stored == [
            {
                "repository": REPO,
                "control_id": CONTROL,
                "claim": "not_applicable",
                "evidence_digest": "d1",
                "confirmed_by": getpass.getuser(),
                "confirmed_at": "2026-09-01T12:00:00Z",
                "expires_at": "2027-02-28T12:00:00Z",
            }
        ]

    @pytest.mark.skipif(not hasattr(stat, "S_IMODE"), reason="POSIX permissions")
    def test_store_is_private(self, data_root: Path) -> None:
        _record()

        assert stat.S_IMODE((data_root / "trust").stat().st_mode) == 0o700
        assert stat.S_IMODE((data_root / "trust" / "confirmations.json").stat().st_mode) == 0o600

    def test_confirmed_by_uses_operator_identity_and_expiry_policy(self, data_root: Path) -> None:
        operator = _operator(operator={"identity": "alice@example.com"}, policy={"confirmation_expiry_days": 10})

        confirmation = _record(operator=operator)

        assert confirmation.confirmed_by == "alice@example.com"
        assert confirmation.expires_at == "2026-09-11T12:00:00Z"

    def test_applies_only_on_exact_match(self, data_root: Path) -> None:
        _record()
        stored = load_confirmations()

        assert find_confirmation(stored, REPO, CONTROL, "not_applicable", "d1", now=NOW) is not None
        assert find_confirmation(stored, "github.com/example/other", CONTROL, "not_applicable", "d1", now=NOW) is None
        assert find_confirmation(stored, REPO, "OSPS-DO-01.01", "not_applicable", "d1", now=NOW) is None
        assert find_confirmation(stored, REPO, CONTROL, "not_applicable", "d2", now=NOW) is None

    def test_lapses_on_expiry(self, data_root: Path) -> None:
        _record(operator=_operator(policy={"confirmation_expiry_days": 1}))
        stored = load_confirmations()

        assert find_confirmation(stored, REPO, CONTROL, "not_applicable", "d1", now=NOW + timedelta(hours=23))
        assert find_confirmation(stored, REPO, CONTROL, "not_applicable", "d1", now=NOW + timedelta(days=1)) is None

    def test_lapses_on_evidence_change(self, data_root: Path) -> None:
        _record(evidence_digest="d1")
        _record(evidence_digest="d2")
        stored = load_confirmations()

        assert find_confirmation(stored, REPO, CONTROL, "not_applicable", "d1", now=NOW) is None
        assert find_confirmation(stored, REPO, CONTROL, "not_applicable", "d2", now=NOW) is not None
        assert len(stored) == 1

    def test_keyed_by_repository_identity(self, data_root: Path) -> None:
        _record()
        _record(repository="github.com/example/other")

        assert {c.repository for c in load_confirmations()} == {REPO, "github.com/example/other"}
        assert [c.repository for c in load_confirmations(REPO)] == [REPO]

    def test_never_written_to_the_audited_repository(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        monkeypatch.setattr(confirmations, "user_data_root", lambda: checkout / ".darnit")

        with pytest.raises(ValueError, match="inside the audited repository"):
            _record(checkout=checkout)
        assert not (checkout / ".darnit").exists()
        assert load_confirmations(checkout=checkout) == []

    def test_unreadable_store_yields_no_confirmations(self, data_root: Path) -> None:
        (data_root / "trust").mkdir(parents=True)
        (data_root / "trust" / "confirmations.json").write_text("{not json", encoding="utf-8")

        assert load_confirmations() == []


_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")


def _claimed_repo(tmp_path: Path, reason: str) -> Path:
    import subprocess

    path = tmp_path / "repo"
    (path / ".project").mkdir(parents=True, exist_ok=True)
    (path / ".project" / "darnit.yaml").write_text(
        f"controls:\n  OSPS-DO-01.01:\n    status: n/a\n    reason: {reason}\n", encoding="utf-8"
    )
    if not (path / ".git").exists():
        subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    return path


def _outcome(repo: Path) -> str:
    from darnit.config import load_controls_from_framework, load_framework_config
    from darnit.tools.audit import _get_framework_config_path, run_sieve_audit

    framework = load_framework_config(_get_framework_config_path("openssf-baseline"))
    controls = [c for c in load_controls_from_framework(framework) if c.control_id == "OSPS-DO-01.01"]
    results, _ = run_sieve_audit(
        owner="example",
        repo="repo",
        local_path=str(repo),
        default_branch="main",
        level=1,
        controls=controls,
        framework_name="openssf-baseline",
        target=REPO,
    )
    return results[0]["assertion"]["outcome"]


@pytest.mark.integration
class TestConfirmationTool:
    @pytest.fixture(autouse=True)
    def _outside_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in _CI_VARS:
            monkeypatch.delenv(var, raising=False)

    def _confirm(self, path: Path, **names: str) -> str:
        from darnit.server.tools.project_data import confirm_project_data_impl

        return confirm_project_data_impl(
            local_path=str(path),
            confirm_not_applicable=["OSPS-DO-01.01"],
            framework_name="openssf-baseline",
            **names,
        )

    def test_confirmed_claim_is_honored_until_its_reason_changes(self, tmp_path: Path, data_root: Path) -> None:
        repo = _claimed_repo(tmp_path, "docs live elsewhere")
        assert _outcome(repo) == "pending"

        message = self._confirm(repo, owner="example", repo="repo")

        assert "OSPS-DO-01.01: confirmed by" in message
        assert (data_root / "trust" / "confirmations.json").is_file()
        assert not any(p.name == "confirmations.json" for p in repo.rglob("*"))
        assert _outcome(repo) == "honored"

        _claimed_repo(tmp_path, "a new reason")
        assert _outcome(repo) == "pending"

    def test_repository_must_be_named(self, tmp_path: Path, data_root: Path) -> None:
        repo = _claimed_repo(tmp_path, "docs live elsewhere")

        message = self._confirm(repo)

        assert message.startswith("Error: name the repository")
        assert not (data_root / "trust" / "confirmations.json").exists()
