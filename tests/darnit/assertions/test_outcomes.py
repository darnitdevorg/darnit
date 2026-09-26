"""Assertion outcomes: honored, pending, contradicted (feature 040, US3, T042).

A not-applicable claim counts only when the repository is trusted, the claim
gives a reason, and no declared evidence contradicts it (FR-014 to FR-018).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from darnit.config.framework_schema import ContradictedBy
from darnit.trust.assertions import Evidence, ProjectAssertion, assess_assertion, evidence_digest
from darnit.trust.confirmations import Confirmation

REPO = "github.com/example/repo"
RELEASES = ContradictedBy(context="has_releases", when_value=True)
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _claim(reason: str | None = "Pre-1.0, no releases yet", origin: str = "explicit_claim") -> ProjectAssertion:
    return ProjectAssertion(
        control_id="OSPS-BR-02.01",
        claim="not_applicable",
        reason=reason,
        asserted_by="@maintainer",
        location=".project/darnit.yaml:controls.OSPS-BR-02.01",
        origin=origin,
    )


def _evidence(value: object) -> Evidence:
    return Evidence(source="context.has_releases", value=value, observed_at="2026-09-01T00:00:00Z")


def _observe(value: object):
    calls: list[int] = []

    def observe() -> Evidence:
        calls.append(1)
        return _evidence(value)

    observe.calls = calls  # type: ignore[attr-defined]
    return observe


def _confirmation(
    claim: ProjectAssertion, evidence: Evidence | None, *, expires: datetime | None = None
) -> Confirmation:
    return Confirmation(
        repository=REPO,
        control_id=claim.control_id,
        claim="not_applicable",
        evidence_digest=evidence_digest(claim, evidence),
        confirmed_by="operator@example",
        confirmed_at="2026-08-01T00:00:00Z",
        expires_at=(expires or NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
    )


@pytest.mark.unit
class TestStateMachine:
    def test_trusted_with_reason_and_no_declared_evidence_is_honored(self) -> None:
        result = assess_assertion(_claim(), trusted=True, contradicted_by=None)

        assert result.outcome == "honored"
        assert result.contradiction is None
        assert result.confirmation is None

    def test_trusted_with_reason_and_uncontradicting_evidence_is_honored(self) -> None:
        result = assess_assertion(_claim(), trusted=True, contradicted_by=RELEASES, observe=_observe(False))

        assert result.outcome == "honored"

    def test_untrusted_is_pending(self) -> None:
        assert assess_assertion(_claim(), trusted=False, contradicted_by=None).outcome == "pending"

    def test_missing_reason_is_pending_even_when_trusted(self) -> None:
        assert assess_assertion(_claim(reason=None), trusted=True, contradicted_by=None).outcome == "pending"

    def test_unobtainable_evidence_is_pending(self) -> None:
        result = assess_assertion(_claim(), trusted=True, contradicted_by=RELEASES, observe=_observe(None))

        assert result.outcome == "pending"
        assert result.contradiction is None

    def test_declared_evidence_without_an_observer_is_pending(self) -> None:
        assert assess_assertion(_claim(), trusted=True, contradicted_by=RELEASES).outcome == "pending"

    def test_contradicting_evidence_is_reported_and_claim_ignored(self) -> None:
        result = assess_assertion(_claim(), trusted=True, contradicted_by=RELEASES, observe=_observe(True))

        assert result.outcome == "contradicted"
        assert result.contradiction == {
            "evidence_source": "context.has_releases",
            "observed_at": "2026-09-01T00:00:00Z",
            "summary": "has_releases detected as True, which contradicts the not-applicable claim",
        }

    def test_untrusted_claim_does_not_observe_evidence_without_a_confirmation(self) -> None:
        observe = _observe(True)
        result = assess_assertion(_claim(), trusted=False, contradicted_by=RELEASES, observe=observe)

        assert result.outcome == "pending"
        assert observe.calls == []

    def test_report_block_carries_outcome_and_details(self) -> None:
        result = assess_assertion(_claim(), trusted=True, contradicted_by=RELEASES, observe=_observe(True))

        assert result.report() == {
            "outcome": "contradicted",
            "origin": "explicit_claim",
            "reason": "Pre-1.0, no releases yet",
            "asserted_by": "@maintainer",
            "location": ".project/darnit.yaml:controls.OSPS-BR-02.01",
            "confirmation": None,
            "contradiction": result.contradiction,
        }


@pytest.mark.unit
class TestConfirmations:
    def test_confirmation_turns_pending_into_honored(self) -> None:
        claim = _claim()
        confirmation = _confirmation(claim, None)

        result = assess_assertion(
            claim, trusted=False, contradicted_by=None, repository=REPO, confirmations=[confirmation], now=NOW
        )

        assert result.outcome == "honored"
        assert result.report()["confirmation"] == {
            "confirmed_by": "operator@example",
            "confirmed_at": "2026-08-01T00:00:00Z",
            "expires_at": confirmation.expires_at,
        }

    def test_confirmation_honors_a_claim_without_reason(self) -> None:
        claim = _claim(reason=None, origin="context_value:has_releases")
        confirmation = _confirmation(claim, _evidence(False))

        result = assess_assertion(
            claim,
            trusted=True,
            contradicted_by=RELEASES,
            observe=_observe(False),
            repository=REPO,
            confirmations=[confirmation],
            now=NOW,
        )

        assert result.outcome == "honored"

    def test_expired_confirmation_lapses(self) -> None:
        claim = _claim()
        confirmation = _confirmation(claim, None, expires=NOW - timedelta(seconds=1))

        result = assess_assertion(
            claim, trusted=False, contradicted_by=None, repository=REPO, confirmations=[confirmation], now=NOW
        )

        assert result.outcome == "pending"

    def test_changed_reason_lapses(self) -> None:
        confirmation = _confirmation(_claim(), None)

        result = assess_assertion(
            _claim(reason="a different reason"),
            trusted=False,
            contradicted_by=None,
            repository=REPO,
            confirmations=[confirmation],
            now=NOW,
        )

        assert result.outcome == "pending"

    def test_changed_evidence_lapses(self) -> None:
        claim = _claim()
        confirmation = _confirmation(claim, _evidence(None))

        result = assess_assertion(
            claim,
            trusted=False,
            contradicted_by=RELEASES,
            observe=_observe(False),
            repository=REPO,
            confirmations=[confirmation],
            now=NOW,
        )

        assert result.outcome == "pending"

    def test_confirmation_for_another_repository_does_not_apply(self) -> None:
        claim = _claim()
        confirmation = _confirmation(claim, None)

        result = assess_assertion(
            claim,
            trusted=False,
            contradicted_by=None,
            repository="github.com/example/other",
            confirmations=[confirmation],
            now=NOW,
        )

        assert result.outcome == "pending"

    def test_contradicting_evidence_overrides_a_confirmation(self) -> None:
        claim = _claim()
        confirmation = _confirmation(claim, _evidence(True))

        result = assess_assertion(
            claim,
            trusted=False,
            contradicted_by=RELEASES,
            observe=_observe(True),
            repository=REPO,
            confirmations=[confirmation],
            now=NOW,
        )

        assert result.outcome == "contradicted"


@pytest.mark.unit
class TestEvidenceDigest:
    def test_digest_depends_on_reason_and_evidence_only(self) -> None:
        a = evidence_digest(_claim(), _evidence(False))
        later = Evidence(source="context.has_releases", value=False, observed_at="2027-01-01T00:00:00Z")

        assert a == evidence_digest(_claim(), later)
        assert a != evidence_digest(_claim(), _evidence(True))
        assert a != evidence_digest(_claim(reason="other"), _evidence(False))
        assert len(a) == 64
