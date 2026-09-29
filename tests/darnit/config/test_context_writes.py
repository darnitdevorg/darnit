"""Project file states and the single context writer (feature 042, FR-011, FR-019 to FR-021; research R3, R10)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from darnit.config.context_keys import value_digest
from darnit.config.context_schema import ContextDefinition, ContextType
from darnit.config.context_writes import delete_stored_value, record_value_confirmation
from darnit.config.loader import load_project_config, load_project_config_checked
from darnit.config.operator.schema import OperatorConfig
from darnit.trust.confirmations import load_confirmations, load_context_bases

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
TARGET = "github.com/example-org/project"

HAND_WRITTEN_INVALID = """\
# Maintained by hand.
name: hand
social:
  - https://social.example.net/@hand
"""

DARNIT_WITH_CLAIMS = """\
# Our darnit extension. Keep this comment.
version: '1.0'
controls:
  OSPS-BR-02.01:
    status: n/a
    reason: No releases yet  # why
context:
  has_subprojects: false
"""


def _definitions() -> dict[str, ContextDefinition]:
    return {
        "maintainers": ContextDefinition(type=ContextType.LIST_OR_PATH, prompt="?", allow_sieve_hints=True),
        "security_contact": ContextDefinition(type=ContextType.STRING, prompt="?"),
        "has_subprojects": ContextDefinition(type=ContextType.BOOLEAN, prompt="?"),
        "ci_provider": ContextDefinition(
            type=ContextType.ENUM, prompt="?", auto_detect=True, values=["github", "gitlab", "other"]
        ),
    }


def _operator(trusted: bool = True, **data: Any) -> OperatorConfig:
    return OperatorConfig.model_validate({"schema_version": 1, "trust": {"repos": [TARGET] if trusted else []}, **data})


def _confirm(repo: Path, key: str, value: Any, **kwargs: Any):
    kwargs.setdefault("target", TARGET)
    kwargs.setdefault("operator", _operator())
    kwargs.setdefault("definitions", _definitions())
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("env", {})
    return record_value_confirmation(str(repo), key, value, **kwargs)


def _darnit(repo: Path) -> dict[str, Any]:
    return yaml.safe_load((repo / ".project" / "darnit.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    return path


def _write(repo: Path, name: str, text: str) -> Path:
    (repo / ".project").mkdir(exist_ok=True)
    path = repo / ".project" / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.unit
class TestLoadChecked:
    def test_absent(self, repo: Path) -> None:
        files = load_project_config_checked(str(repo))

        assert files.project.state == "absent"
        assert files.extension.state == "absent"
        assert not files.invalid

    def test_valid_project_without_extension(self, repo: Path) -> None:
        _write(repo, "project.yaml", "name: p\n")

        files = load_project_config_checked(str(repo))

        assert files.project.state == "valid"
        assert files.extension.state == "absent"

    def test_invalid_project_reported_with_errors(self, repo: Path) -> None:
        _write(repo, "project.yaml", HAND_WRITTEN_INVALID)
        _write(repo, "darnit.yaml", "context:\n  has_subprojects: true\n")

        files = load_project_config_checked(str(repo))

        assert files.project.state == "invalid"
        assert files.project.errors
        assert any("social" in e for e in files.project.errors)
        assert files.extension.state == "valid"
        assert files.invalid

    def test_unparseable_extension(self, repo: Path) -> None:
        _write(repo, "project.yaml", "name: p\n")
        _write(repo, "darnit.yaml", "controls: [unclosed\n")

        files = load_project_config_checked(str(repo))

        assert files.project.state == "valid"
        assert files.extension.state == "invalid"
        assert files.extension.errors

    def test_empty_extension_is_valid(self, repo: Path) -> None:
        _write(repo, "darnit.yaml", "# nothing yet\n")

        assert load_project_config_checked(str(repo)).extension.state == "valid"

    def test_extension_that_is_not_a_mapping(self, repo: Path) -> None:
        _write(repo, "darnit.yaml", "- a\n- b\n")

        assert load_project_config_checked(str(repo)).extension.state == "invalid"

    def test_load_project_config_stays_a_reader(self, repo: Path) -> None:
        _write(repo, "project.yaml", HAND_WRITTEN_INVALID)

        assert load_project_config(str(repo)) is None
        assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == HAND_WRITTEN_INVALID


@pytest.mark.unit
class TestRecordInRepository:
    def test_writes_value_and_record_to_the_extension_file_only(self, repo: Path) -> None:
        result = _confirm(repo, "maintainers", ["@alice", "@bob"])

        assert result.outcome == "confirmed"
        assert result.location == "repository"
        assert result.file == ".project/darnit.yaml"
        assert not (repo / ".project" / "project.yaml").exists()
        data = _darnit(repo)
        assert data["context"]["maintainers"] == ["@alice", "@bob"]
        record = data["confirmations"]["maintainers"]
        assert record["value_digest"] == value_digest("maintainers", ["@alice", "@bob"])
        assert record["confirmed_at"] == "2026-09-29T12:00:00Z"
        assert record["last_validated"] == "2026-09-29T12:00:00Z"
        assert record["confirmed_by"]
        assert "expires_at" not in record
        assert "basis" not in record

    def test_records_basis_and_expiry(self, repo: Path) -> None:
        basis = {"value": ["@alice"], "origin": {"kind": "sieve_hint", "method": "MAINTAINERS.md"}}

        _confirm(repo, "maintainers", ["@alice"], basis=basis, expires_at=datetime(2027, 9, 29, tzinfo=UTC))

        record = _darnit(repo)["confirmations"]["maintainers"]
        assert record["basis"] == basis
        assert record["expires_at"] == "2027-09-29T00:00:00Z"

    def test_confirmed_by_is_the_operator_identity(self, repo: Path) -> None:
        _confirm(repo, "has_subprojects", False, operator=_operator(operator={"identity": "alice@example.net"}))

        assert _darnit(repo)["confirmations"]["has_subprojects"]["confirmed_by"] == "alice@example.net"

    def test_preserves_claims_and_comments(self, repo: Path) -> None:
        path = _write(repo, "darnit.yaml", DARNIT_WITH_CLAIMS)

        _confirm(repo, "maintainers", ["@alice"])

        text = path.read_text(encoding="utf-8")
        assert "# Our darnit extension. Keep this comment." in text
        assert "# why" in text
        data = yaml.safe_load(text)
        assert data["controls"] == {"OSPS-BR-02.01": {"status": "n/a", "reason": "No releases yet"}}
        assert data["context"] == {"has_subprojects": False, "maintainers": ["@alice"]}

    def test_reconfirmation_updates_last_validated_and_keeps_expiry(self, repo: Path) -> None:
        _confirm(repo, "maintainers", ["@alice"], expires_at=datetime(2027, 1, 1, tzinfo=UTC))

        later = datetime(2026, 10, 29, tzinfo=UTC)
        _confirm(repo, "maintainers", ["@alice"], now=later)

        record = _darnit(repo)["confirmations"]["maintainers"]
        assert record["confirmed_at"] == "2026-09-29T12:00:00Z"
        assert record["last_validated"] == "2026-10-29T00:00:00Z"
        assert record["expires_at"] == "2027-01-01T00:00:00Z"

    def test_writes_only_canonical_ci_provider(self, repo: Path) -> None:
        _write(repo, "darnit.yaml", "context:\n  provider: github_actions\n  ci.provider: gitlab_ci\n")

        _confirm(repo, "ci.provider", "github")

        assert _darnit(repo)["context"] == {"ci_provider": "github"}
        assert "ci_provider" in _darnit(repo)["confirmations"]

    def test_never_writes_the_project_file(self, repo: Path) -> None:
        project = _write(repo, "project.yaml", "# mine\nname: p\nsecurity:\n  contact: old@p.example.net\n")
        before = project.read_bytes()

        result = _confirm(repo, "security_contact", "new@p.example.net")

        assert result.outcome == "confirmed"
        assert project.read_bytes() == before
        assert _darnit(repo)["context"]["security_contact"] == "new@p.example.net"


@pytest.mark.unit
class TestRefusals:
    def test_invalid_project_file(self, repo: Path) -> None:
        project = _write(repo, "project.yaml", HAND_WRITTEN_INVALID)

        result = _confirm(repo, "maintainers", ["@alice"])

        assert result.outcome == "refused"
        assert result.errors
        assert project.read_text(encoding="utf-8") == HAND_WRITTEN_INVALID
        assert not (repo / ".project" / "darnit.yaml").exists()

    def test_unparseable_extension_file(self, repo: Path) -> None:
        text = DARNIT_WITH_CLAIMS + "  broken: [\n"
        path = _write(repo, "darnit.yaml", text)

        result = _confirm(repo, "maintainers", ["@alice"])

        assert result.outcome == "refused"
        assert result.errors
        assert path.read_text(encoding="utf-8") == text

    def test_invalid_file_refuses_operator_side_too(self, repo: Path) -> None:
        _write(repo, "project.yaml", HAND_WRITTEN_INVALID)

        result = _confirm(repo, "maintainers", ["@alice"], operator=_operator(trusted=False))

        assert result.outcome == "refused"
        assert load_confirmations() == []

    def test_unknown_key(self, repo: Path) -> None:
        result = _confirm(repo, "favourite_colour", "blue")

        assert result.outcome == "refused"
        assert not (repo / ".project").exists()

    def test_value_outside_the_vocabulary(self, repo: Path) -> None:
        result = _confirm(repo, "ci_provider", "github_actions_but_wrong")

        assert result.outcome == "refused"
        assert "github" in result.reason

    def test_untrusted_without_a_named_repository(self, repo: Path) -> None:
        result = _confirm(repo, "maintainers", ["@alice"], target=None, operator=_operator(trusted=False))

        assert result.outcome == "refused"
        assert not (repo / ".project").exists()
        assert load_confirmations() == []


@pytest.mark.unit
class TestRecordOperatorSide:
    def test_untrusted_target_writes_nothing_to_the_repository(self, repo: Path) -> None:
        basis = {"value": ["@alice"], "origin": {"kind": "sieve_hint", "method": "MAINTAINERS.md"}}

        result = _confirm(repo, "maintainers", ["@alice"], operator=_operator(trusted=False), basis=basis)

        assert result.outcome == "confirmed"
        assert result.location == "operator"
        assert not (repo / ".project").exists()
        (confirmation,) = load_confirmations(TARGET)
        assert confirmation.claim == "context_value"
        assert confirmation.control_id == "maintainers"
        assert confirmation.evidence_digest == value_digest("maintainers", ["@alice"])
        assert confirmation.expires_at is None
        (stored,) = load_context_bases(TARGET)
        assert stored.value == ["@alice"]
        assert stored.origin == basis["origin"]

    def test_explicit_expiry_not_operator_policy(self, repo: Path) -> None:
        operator = _operator(trusted=False, policy={"confirmation_expiry_days": 1})

        _confirm(repo, "has_subprojects", True, operator=operator, expires_at=datetime(2027, 1, 1, tzinfo=UTC))

        (confirmation,) = load_confirmations(TARGET)
        assert confirmation.expires_at == "2027-01-01T00:00:00Z"


@pytest.mark.unit
class TestDeleteStoredValue:
    def test_deletes_from_the_extension_file(self, repo: Path) -> None:
        _write(repo, "darnit.yaml", DARNIT_WITH_CLAIMS)

        result = delete_stored_value(str(repo), "has_subprojects")

        assert result.outcome == "deleted"
        data = _darnit(repo)
        assert "has_subprojects" not in (data.get("context") or {})
        assert "OSPS-BR-02.01" in data["controls"]

    def test_project_file_value_is_reported_not_edited(self, repo: Path) -> None:
        project = _write(repo, "project.yaml", "name: p\nsecurity:\n  contact: old@p.example.net\n")
        before = project.read_bytes()

        result = delete_stored_value(str(repo), "security_contact")

        assert result.outcome == "edit_required"
        assert result.file == ".project/project.yaml"
        assert result.reason == "security.contact"
        assert project.read_bytes() == before
