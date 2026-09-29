"""Consumers read only usable context values (feature 042, US2, FR-004 to FR-006, SC-002)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from darnit.config import context_resolve
from darnit.config.context_keys import value_digest
from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import ContextValue, OriginKind, Standing
from darnit.config.operator.schema import OperatorConfig
from darnit.context.auto_detect import collect_auto_context
from darnit.tools.audit import _applicability_context
from darnit.trust.assertions import context_value_assertions
from darnit.trust.confirmations import record_context_confirmation

TARGET = "github.com/example-org/empty"
RELEASE_CONTROLS = {"OSPS-BR-02.01": {"has_releases": True}}
CANDIDATE_MAINTAINERS = ["@candidate-only-maintainer"]
CANDIDATE_CONTACT = "candidate-only@unconfirmed.example.net"


def _baseline_definitions() -> dict[str, Any]:
    from darnit.config.context_storage import get_context_definitions

    return get_context_definitions(".")


def _operator() -> OperatorConfig:
    return OperatorConfig.model_validate({"schema_version": 1})


def _record(key: str, value: Any) -> dict[str, Any]:
    return {
        "value_digest": value_digest(key, value),
        "confirmed_by": "alice",
        "confirmed_at": "2026-09-01T00:00:00Z",
        "last_validated": "2026-09-01T00:00:00Z",
    }


def _write_darnit(repo: Path, data: dict[str, Any]) -> None:
    (repo / ".project").mkdir(exist_ok=True)
    (repo / ".project" / "darnit.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture
def detected_maintainers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detection proposes maintainers at confidence 0.95; nothing else is detected."""

    def fake_detect(key: str, definition: Any, local_path: str, owner: Any, repo: Any):
        if key == "maintainers":
            detected = ContextValue.auto_detected(value=CANDIDATE_MAINTAINERS, method="MAINTAINERS.md", confidence=0.95)
            return detected, OriginKind.SIEVE_HINT
        return None, None

    monkeypatch.setattr(context_resolve, "_detect", fake_detect)


@pytest.mark.unit
class TestBaselineJudgmentKeys:
    """FR-005: maintainers and security contact require a person's decision."""

    @pytest.mark.parametrize("key", ["maintainers", "security_contact"])
    def test_marked_as_judgment_keys_that_may_propose(self, key: str) -> None:
        definition = _baseline_definitions()[key]

        assert definition.auto_detect is False
        assert definition.allow_sieve_hints is True
        assert definition.hint_sources

    def test_detected_maintainers_at_high_confidence_is_a_candidate(self, tmp_path: Path, detected_maintainers) -> None:
        resolved = resolve_context(str(tmp_path), _baseline_definitions(), operator=_operator(), env={})

        assert resolved.values["maintainers"].standing is Standing.CANDIDATE
        assert resolved.values["maintainers"].origin.confidence == 0.95
        assert "maintainers" not in resolved.usable()


@pytest.mark.integration
class TestAuditApplicability:
    def test_unconfirmed_stored_values_are_not_used(self, scratch_repo: Callable[[str], Path]) -> None:
        repo = scratch_repo("R-legacy")

        context, detected, repository_values = _applicability_context(str(repo), "example-org", operator=_operator())

        assert "has_releases" not in context
        assert "maintainers" not in context
        assert context.get("ci_provider") != "github_actions"
        assert "provider" not in context
        assert not {"has_releases", "maintainers", "ci_provider"} & set(repository_values)

    def test_unconfirmed_stored_value_implies_no_claim(self, scratch_repo: Callable[[str], Path]) -> None:
        repo = scratch_repo("R-legacy")

        context, detected, repository_values = _applicability_context(str(repo), "example-org", operator=_operator())

        assert context_value_assertions(RELEASE_CONTROLS, context, detected, repository_values) == []

    def test_confirmed_repository_value_is_used_and_is_a_claim(self, scratch_repo: Callable[[str], Path]) -> None:
        repo = scratch_repo("R-legacy")
        data = yaml.safe_load((repo / ".project" / "darnit.yaml").read_text(encoding="utf-8"))
        data["confirmations"] = {"has_releases": _record("has_releases", False)}
        _write_darnit(repo, data)

        context, detected, repository_values = _applicability_context(str(repo), "example-org", operator=_operator())
        claims = context_value_assertions(RELEASE_CONTROLS, context, detected, repository_values)

        assert context["has_releases"] is False
        assert repository_values["has_releases"] == ".project/darnit.yaml:context.has_releases"
        assert [(c.control_id, c.origin) for c in claims] == [("OSPS-BR-02.01", "context_value:has_releases")]
        assert "maintainers" not in context

    def test_operator_confirmed_value_is_used_and_is_not_a_repository_claim(
        self, scratch_repo: Callable[[str], Path]
    ) -> None:
        repo = scratch_repo("empty")
        operator = _operator()
        record_context_confirmation(
            TARGET, "has_releases", value_digest("has_releases", False), False, None, operator, checkout=repo
        )

        context, detected, repository_values = _applicability_context(
            str(repo), "example-org", target=TARGET, operator=operator
        )

        assert context["has_releases"] is False
        assert "has_releases" not in repository_values

    def test_detected_maintainers_candidate_is_not_used(
        self, scratch_repo: Callable[[str], Path], detected_maintainers
    ) -> None:
        repo = scratch_repo("R-maint")

        context, detected, _ = _applicability_context(str(repo), "example-org", operator=_operator())

        assert "maintainers" not in context
        assert "maintainers" not in detected


@pytest.mark.integration
class TestCollectAutoContext:
    def test_stored_values_only_when_confirmed_and_canonical(self, scratch_repo: Callable[[str], Path]) -> None:
        repo = scratch_repo("R-legacy")
        data = yaml.safe_load((repo / ".project" / "darnit.yaml").read_text(encoding="utf-8"))
        data["confirmations"] = {"has_releases": _record("has_releases", False)}
        _write_darnit(repo, data)

        context = collect_auto_context(str(repo))

        assert context["has_releases"] is False
        assert "maintainers" not in context
        assert "provider" not in context
        assert context.get("ci_provider") != "github_actions"

    def test_detections_only_without_stored(self, scratch_repo: Callable[[str], Path]) -> None:
        repo = scratch_repo("R-ci")
        _write_darnit(
            repo,
            {"context": {"ci_provider": "gitlab"}, "confirmations": {"ci_provider": _record("ci_provider", "gitlab")}},
        )

        assert collect_auto_context(str(repo), include_stored=False)["ci_provider"] == "github"
        assert collect_auto_context(str(repo))["ci_provider"] == "gitlab"

    def test_detection_of_a_judgment_key_is_dropped(self, scratch_repo: Callable[[str], Path]) -> None:
        from darnit.config.context_schema import ContextDefinition, ContextType

        repo = scratch_repo("R-ci")
        definitions = {"ci_provider": ContextDefinition(type=ContextType.STRING, prompt="CI?", auto_detect=False)}

        assert "ci_provider" not in collect_auto_context(str(repo), include_stored=False, definitions=definitions)


@pytest.mark.integration
def test_attestation_carries_no_unconfirmed_value(
    scratch_repo: Callable[[str], Path], tmp_path: Path, detected_maintainers
) -> None:
    """A regression guard: attestations do not carry context values today (SC-002)."""
    from darnit_baseline.tools import generate_attestation

    repo = scratch_repo("R-legacy")
    _write_darnit(
        repo,
        {"context": {"maintainers": CANDIDATE_MAINTAINERS, "security_contact": CANDIDATE_CONTACT}},
    )
    out_dir = tmp_path / "attestations"
    out_dir.mkdir()

    output = generate_attestation(
        owner="example-org", repo="r-legacy", local_path=str(repo), level=1, sign=False, output_dir=str(out_dir)
    )

    written = "".join(p.read_text(encoding="utf-8") for p in out_dir.iterdir())
    assert "predicate" in output + written
    for text in (output, written):
        assert CANDIDATE_MAINTAINERS[0] not in text
        assert CANDIDATE_CONTACT not in text
