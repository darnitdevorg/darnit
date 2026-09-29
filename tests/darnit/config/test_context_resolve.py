"""Context value standing (feature 042, FR-003 to FR-006, FR-009 to FR-012, FR-022; research R2 to R5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from darnit.config import context_resolve
from darnit.config.context_keys import value_digest
from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import (
    ContextDefinition,
    ContextType,
    ContextValue,
    OriginKind,
    Standing,
)
from darnit.config.operator.schema import OperatorConfig
from darnit.trust.confirmations import record_context_confirmation

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
TARGET = "github.com/example-org/project"
MAINTAINERS = ["@alice", "@bob"]


def _definitions(**overrides: dict[str, Any]) -> dict[str, ContextDefinition]:
    base = {
        "maintainers": {"type": ContextType.LIST_OR_PATH, "affects": ["C-1"], "allow_sieve_hints": True},
        "security_contact": {"type": ContextType.STRING, "affects": ["C-2"]},
        "has_releases": {"type": ContextType.BOOLEAN, "affects": ["C-3"], "auto_detect": True},
        "ci_provider": {
            "type": ContextType.ENUM,
            "affects": ["C-4"],
            "auto_detect": True,
            "values": ["github", "gitlab", "azure", "other"],
        },
        "governance_model": {"type": ContextType.ENUM, "affects": [], "values": ["bdfl", "foundation"]},
    }
    for key, fields in overrides.items():
        base[key] = {**base[key], **fields}
    return {key: ContextDefinition(prompt=f"{key}?", **fields) for key, fields in base.items()}


def _operator(**data: Any) -> OperatorConfig:
    return OperatorConfig.model_validate({"schema_version": 1, **data})


def _write_darnit(repo: Path, data: dict[str, Any]) -> None:
    (repo / ".project").mkdir(exist_ok=True)
    (repo / ".project" / "darnit.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def _record(value: Any, key: str = "maintainers", **fields: Any) -> dict[str, Any]:
    return {
        "value_digest": value_digest(key, value),
        "confirmed_by": "alice",
        "confirmed_at": "2026-09-01T00:00:00Z",
        "last_validated": "2026-09-01T00:00:00Z",
        **fields,
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    return path


@pytest.fixture
def detections(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[ContextValue, OriginKind]]:
    """Per-key detection results the resolver sees; keys absent here detect nothing."""
    results: dict[str, tuple[ContextValue, OriginKind]] = {}

    def fake_detect(key: str, definition: ContextDefinition, local_path: str, owner: Any, repo: Any):
        return results.get(key, (None, None))

    monkeypatch.setattr(context_resolve, "_detect", fake_detect)
    return results


def _resolve(repo: Path, **kwargs: Any):
    kwargs.setdefault("operator", _operator())
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("env", {})
    return resolve_context(str(repo), _definitions(), auto_accept_confidence=0.8, **kwargs)


def _detected(value: Any, confidence: float, method: str = "MAINTAINERS.md") -> ContextValue:
    return ContextValue.auto_detected(value=value, method=method, confidence=confidence)


@pytest.mark.unit
class TestDetection:
    def test_nothing_known(self, repo: Path, detections: dict) -> None:
        resolved = _resolve(repo)

        assert resolved.values["maintainers"].standing is Standing.UNKNOWN
        assert resolved.values["maintainers"].value is None
        assert resolved.usable() == {}

    @pytest.mark.parametrize("confidence", [0.5, 0.95, 1.0])
    def test_judgment_key_is_never_concluded(self, repo: Path, detections: dict, confidence: float) -> None:
        detections["maintainers"] = (_detected(MAINTAINERS, confidence), OriginKind.SIEVE_HINT)

        value = _resolve(repo).values["maintainers"]

        assert value.standing is Standing.CANDIDATE
        assert value.value == MAINTAINERS
        assert value.origin.kind is OriginKind.SIEVE_HINT
        assert value.origin.method == "MAINTAINERS.md"
        assert value.origin.confidence == confidence

    def test_candidate_is_not_usable(self, repo: Path, detections: dict) -> None:
        detections["maintainers"] = (_detected(MAINTAINERS, 0.95), OriginKind.SIEVE_HINT)

        assert "maintainers" not in _resolve(repo).usable()

    def test_detectable_key_concluded_above_threshold(self, repo: Path, detections: dict) -> None:
        detections["has_releases"] = (_detected(True, 0.9, "detect_pipeline:file_exists"), OriginKind.DETECTOR)

        resolved = _resolve(repo)

        assert resolved.values["has_releases"].standing is Standing.CONCLUDED
        assert resolved.values["has_releases"].origin.kind is OriginKind.DETECTOR
        assert resolved.usable() == {"has_releases": True}

    def test_detectable_key_below_threshold_is_candidate(self, repo: Path, detections: dict) -> None:
        detections["has_releases"] = (_detected(True, 0.5), OriginKind.DETECTOR)

        resolved = _resolve(repo)

        assert resolved.values["has_releases"].standing is Standing.CANDIDATE
        assert resolved.usable() == {}

    def test_no_detection_when_asked_not_to(self, repo: Path, detections: dict) -> None:
        detections["has_releases"] = (_detected(True, 0.9), OriginKind.DETECTOR)

        assert _resolve(repo, detect=False).values["has_releases"].standing is Standing.UNKNOWN

    def test_confirmed_key_is_not_detected(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_darnit(
            repo, {"context": {"maintainers": MAINTAINERS}, "confirmations": {"maintainers": _record(MAINTAINERS)}}
        )
        seen: list[str] = []
        monkeypatch.setattr(context_resolve, "_detect", lambda key, *a: (seen.append(key), (None, None))[1])

        _resolve(repo)

        assert "maintainers" not in seen


@pytest.mark.unit
class TestStoredValues:
    def test_stored_without_record_is_a_candidate(self, repo: Path, detections: dict) -> None:
        _write_darnit(repo, {"context": {"maintainers": MAINTAINERS}})

        value = _resolve(repo).values["maintainers"]

        assert value.standing is Standing.CANDIDATE
        assert value.origin.kind is OriginKind.STORED_UNCONFIRMED
        assert value.location == ".project/darnit.yaml:context.maintainers"
        assert value.value == MAINTAINERS

    def test_project_file_value_without_record(self, repo: Path, detections: dict) -> None:
        (repo / ".project").mkdir()
        (repo / ".project" / "project.yaml").write_text(
            "name: p\nsecurity:\n  contact: security@p.example.net\n", encoding="utf-8"
        )

        value = _resolve(repo).values["security_contact"]

        assert value.standing is Standing.CANDIDATE
        assert value.origin.kind is OriginKind.STORED_UNCONFIRMED
        assert value.location == ".project/project.yaml:security.contact"

    def test_legacy_ci_provider_reads_canonically(self, repo: Path, detections: dict) -> None:
        _write_darnit(repo, {"context": {"ci_provider": "github_actions"}})

        value = _resolve(repo).values["ci_provider"]

        assert value.value == "github"
        assert value.standing is Standing.CANDIDATE

    def test_stored_candidates_are_listed_for_review(self, repo: Path, detections: dict) -> None:
        _write_darnit(repo, {"context": {"maintainers": MAINTAINERS, "has_releases": False}})

        listed = {v.key: v.location for v in _resolve(repo).stored_unconfirmed()}

        assert listed == {
            "maintainers": ".project/darnit.yaml:context.maintainers",
            "has_releases": ".project/darnit.yaml:context.has_releases",
        }

    def test_detectable_key_stored_without_record_uses_a_concluding_detection(
        self, repo: Path, detections: dict
    ) -> None:
        _write_darnit(repo, {"context": {"has_releases": False}})
        detections["has_releases"] = (_detected(True, 0.9), OriginKind.DETECTOR)

        value = _resolve(repo).values["has_releases"]

        assert value.standing is Standing.CONCLUDED
        assert value.value is True


@pytest.mark.unit
class TestInRepositoryRecords:
    def test_matching_record_confirms(self, repo: Path, detections: dict) -> None:
        _write_darnit(
            repo,
            {
                "context": {"maintainers": ["@bob", "@alice"]},
                "confirmations": {"maintainers": _record(MAINTAINERS)},
            },
        )

        resolved = _resolve(repo)
        value = resolved.values["maintainers"]

        assert value.standing is Standing.CONFIRMED
        assert value.confirmation.confirmed_by == "alice"
        assert value.confirmation.location == "repository"
        assert resolved.usable() == {"maintainers": ["@bob", "@alice"]}

    def test_counts_without_trust(self, repo: Path, detections: dict) -> None:
        _write_darnit(
            repo, {"context": {"maintainers": MAINTAINERS}, "confirmations": {"maintainers": _record(MAINTAINERS)}}
        )

        assert _resolve(repo, target=None).values["maintainers"].standing is Standing.CONFIRMED

    def test_hand_edit_is_not_confirmed_by_the_old_record(self, repo: Path, detections: dict) -> None:
        _write_darnit(
            repo,
            {"context": {"maintainers": ["@mallory"]}, "confirmations": {"maintainers": _record(MAINTAINERS)}},
        )

        value = _resolve(repo).values["maintainers"]

        assert value.standing is Standing.CANDIDATE
        assert value.origin.kind is OriginKind.STORED_UNCONFIRMED
        assert value.lapsed is not None
        assert value.lapsed.value_digest == value_digest("maintainers", MAINTAINERS)

    def test_expires_at(self, repo: Path, detections: dict) -> None:
        _write_darnit(
            repo,
            {
                "context": {"maintainers": MAINTAINERS},
                "confirmations": {"maintainers": _record(MAINTAINERS, expires_at="2026-09-15T00:00:00Z")},
            },
        )

        value = _resolve(repo).values["maintainers"]

        assert value.standing is Standing.CANDIDATE
        assert value.origin.kind is OriginKind.EXPIRED_CONFIRMATION
        assert value.value == MAINTAINERS
        assert value.lapsed is not None
        assert "maintainers" not in _resolve(repo).usable()

    def test_not_yet_expired(self, repo: Path, detections: dict) -> None:
        _write_darnit(
            repo,
            {
                "context": {"maintainers": MAINTAINERS},
                "confirmations": {"maintainers": _record(MAINTAINERS, expires_at="2026-12-31T00:00:00Z")},
            },
        )

        assert _resolve(repo).values["maintainers"].standing is Standing.CONFIRMED

    def test_validity_days_from_last_validated(self, repo: Path, detections: dict) -> None:
        _write_darnit(
            repo, {"context": {"maintainers": MAINTAINERS}, "confirmations": {"maintainers": _record(MAINTAINERS)}}
        )
        definitions = _definitions(maintainers={"validity_days": 10})

        value = resolve_context(str(repo), definitions, operator=_operator(), now=NOW, env={}).values["maintainers"]

        assert value.standing is Standing.CANDIDATE
        assert value.origin.kind is OriginKind.EXPIRED_CONFIRMATION

    def test_earliest_limit_applies(self, repo: Path, detections: dict) -> None:
        record = _record(MAINTAINERS, expires_at="2027-01-01T00:00:00Z", last_validated="2026-09-25T00:00:00Z")
        _write_darnit(repo, {"context": {"maintainers": MAINTAINERS}, "confirmations": {"maintainers": record}})

        def standing(validity_days: int) -> Standing:
            definitions = _definitions(maintainers={"validity_days": validity_days})
            return (
                resolve_context(str(repo), definitions, operator=_operator(), now=NOW, env={})
                .values["maintainers"]
                .standing
            )

        assert standing(3) is Standing.CANDIDATE
        assert standing(30) is Standing.CONFIRMED

    def test_unparseable_timestamp_is_lapsed(self, repo: Path, detections: dict) -> None:
        _write_darnit(
            repo,
            {
                "context": {"maintainers": MAINTAINERS},
                "confirmations": {"maintainers": _record(MAINTAINERS, expires_at="whenever")},
            },
        )

        assert _resolve(repo).values["maintainers"].origin.kind is OriginKind.EXPIRED_CONFIRMATION


@pytest.mark.unit
class TestOperatorSideRecords:
    def _confirm_operator_side(self, repo: Path, value: Any, operator: OperatorConfig | None = None, **kwargs: Any):
        return record_context_confirmation(
            TARGET,
            "maintainers",
            value_digest("maintainers", value),
            value,
            None,
            operator or _operator(),
            checkout=repo,
            now=kwargs.pop("now", NOW - timedelta(days=1)),
            **kwargs,
        )

    def test_confirms_for_the_named_repository(self, repo: Path, detections: dict) -> None:
        _write_darnit(repo, {"context": {"maintainers": MAINTAINERS}})
        self._confirm_operator_side(repo, MAINTAINERS)

        value = _resolve(repo, target=TARGET).values["maintainers"]

        assert value.standing is Standing.CONFIRMED
        assert value.confirmation.location == "operator"

    def test_not_without_an_operator_named_repository(self, repo: Path, detections: dict) -> None:
        _write_darnit(repo, {"context": {"maintainers": MAINTAINERS}})
        self._confirm_operator_side(repo, MAINTAINERS)

        assert _resolve(repo).values["maintainers"].standing is Standing.CANDIDATE

    def test_not_for_another_repository(self, repo: Path, detections: dict) -> None:
        _write_darnit(repo, {"context": {"maintainers": MAINTAINERS}})
        self._confirm_operator_side(repo, MAINTAINERS)

        value = _resolve(repo, target="github.com/example-org/other").values["maintainers"]

        assert value.standing is Standing.CANDIDATE

    def test_value_kept_operator_side(self, repo: Path, detections: dict) -> None:
        self._confirm_operator_side(repo, MAINTAINERS)

        resolved = _resolve(repo, target=TARGET)

        assert resolved.values["maintainers"].standing is Standing.CONFIRMED
        assert resolved.usable() == {"maintainers": MAINTAINERS}

    def test_in_repository_record_wins(self, repo: Path, detections: dict) -> None:
        _write_darnit(
            repo, {"context": {"maintainers": MAINTAINERS}, "confirmations": {"maintainers": _record(MAINTAINERS)}}
        )
        self._confirm_operator_side(repo, MAINTAINERS)

        value = _resolve(repo, target=TARGET).values["maintainers"]

        assert value.confirmation.location == "repository"

    def test_operator_expiry_policy_has_no_effect(self, repo: Path, detections: dict) -> None:
        operator = _operator(policy={"confirmation_expiry_days": 1})
        self._confirm_operator_side(repo, MAINTAINERS, operator=operator, now=NOW - timedelta(days=30))

        value = _resolve(repo, target=TARGET, operator=operator).values["maintainers"]

        assert value.standing is Standing.CONFIRMED
        assert value.confirmation.expires_at is None

    def test_explicit_expiry(self, repo: Path, detections: dict) -> None:
        self._confirm_operator_side(repo, MAINTAINERS, expires_at=NOW - timedelta(days=1))

        value = _resolve(repo, target=TARGET).values["maintainers"]

        assert value.origin.kind is OriginKind.EXPIRED_CONFIRMATION


@pytest.mark.unit
class TestViews:
    def test_pending_lists_candidates_and_unknowns_that_affect_controls(self, repo: Path, detections: dict) -> None:
        _write_darnit(repo, {"context": {"security_contact": "sec@p.example.net"}})
        detections["maintainers"] = (_detected(MAINTAINERS, 0.95), OriginKind.SIEVE_HINT)
        detections["has_releases"] = (_detected(True, 0.9), OriginKind.DETECTOR)

        pending = {v.key: v.standing for v in _resolve(repo).pending()}

        assert pending == {
            "maintainers": Standing.CANDIDATE,
            "security_contact": Standing.CANDIDATE,
            "ci_provider": Standing.UNKNOWN,
        }

    def test_pending_filtered_by_control(self, repo: Path, detections: dict) -> None:
        assert [v.key for v in _resolve(repo).pending(control_ids=["C-4"])] == ["ci_provider"]


@pytest.mark.unit
def test_hand_written_unquoted_timestamps(repo: Path, detections: dict) -> None:
    digest = value_digest("maintainers", MAINTAINERS)
    (repo / ".project").mkdir()
    (repo / ".project" / "darnit.yaml").write_text(
        "context:\n  maintainers: ['@alice', '@bob']\nconfirmations:\n  maintainers:\n"
        f"    value_digest: '{digest}'\n    confirmed_by: alice\n"
        "    confirmed_at: 2026-09-01T00:00:00Z\n    last_validated: 2026-09-01T00:00:00Z\n    expires_at: 2027-01-01\n",
        encoding="utf-8",
    )

    value = _resolve(repo).values["maintainers"]

    assert value.standing is Standing.CONFIRMED
    assert value.confirmation.expires_at == "2027-01-01"
