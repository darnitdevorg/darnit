"""Attestations label assertion-backed results (feature 040, US3, T046, SC-006, FR-020)."""

from __future__ import annotations

from typing import Any

import pytest

from darnit_baseline.attestation.predicate import build_assessment_predicate


def _assertion(outcome: str, confirmation: dict | None = None) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "origin": "explicit_claim",
        "reason": "no releases yet",
        "asserted_by": "@maintainer",
        "location": ".project/darnit.yaml:controls.OSPS-BR-02.01",
        "confirmation": confirmation,
        "contradiction": None,
    }


def _predicate(results: list[dict[str, Any]], level: int = 1) -> dict[str, Any]:
    return build_assessment_predicate(
        owner="example",
        repo="repo",
        commit="abc123",
        ref="main",
        level=level,
        results=results,
        project_config=None,
        adapters_used=["builtin"],
    )


def _control(predicate: dict[str, Any], control_id: str) -> dict[str, Any]:
    return next(c for c in predicate["controls"] if c["id"] == control_id)


@pytest.mark.unit
class TestAssertedLabelling:
    def test_every_assertion_backed_na_is_labelled_asserted(self) -> None:
        results = [
            {"id": "OSPS-DO-01.01", "status": "PASS", "level": 1, "authority": "dispositive"},
            {
                "id": "OSPS-BR-02.01",
                "status": "N/A",
                "level": 1,
                "authority": "dispositive",
                "assertion": _assertion("honored"),
            },
        ]

        control = _control(_predicate(results), "OSPS-BR-02.01")

        assert control["authority"] == "asserted"
        assert control["asserted_by"] == "@maintainer"
        assert "confirmed_by" not in control

    def test_confirmation_fields_are_carried(self) -> None:
        confirmation = {
            "confirmed_by": "alice@example.com",
            "confirmed_at": "2026-09-01T00:00:00Z",
            "expires_at": "2027-02-28T00:00:00Z",
        }
        results = [
            {
                "id": "OSPS-BR-02.01",
                "status": "N/A",
                "level": 1,
                "assertion": _assertion("honored", confirmation),
            }
        ]

        control = _control(_predicate(results), "OSPS-BR-02.01")

        assert control["authority"] == "asserted"
        assert control["confirmed_by"] == "alice@example.com"
        assert control["confirmed_at"] == "2026-09-01T00:00:00Z"

    @pytest.mark.parametrize("outcome", ["pending", "contradicted"])
    def test_unhonored_claims_are_not_labelled_asserted(self, outcome: str) -> None:
        results = [
            {
                "id": "OSPS-BR-02.01",
                "status": "FAIL",
                "level": 1,
                "authority": "dispositive",
                "assertion": _assertion(outcome),
            }
        ]

        control = _control(_predicate(results), "OSPS-BR-02.01")

        assert control["authority"] == "dispositive"
        assert control["assertion_outcome"] == outcome
        assert "asserted_by" not in control

    def test_excluded_controls_lists_only_honored_claims(self) -> None:
        results = [
            {"id": "A", "status": "N/A", "level": 1, "assertion": _assertion("honored")},
            {"id": "B", "status": "FAIL", "level": 1, "assertion": _assertion("pending")},
            {"id": "C", "status": "PASS", "level": 1},
        ]

        assert _predicate(results)["configuration"]["excluded_controls"] == ["A"]


@pytest.mark.unit
class TestLevelCompliance:
    @pytest.mark.parametrize("status", ["WARN", "ERROR", "PENDING_LLM"])
    def test_unverified_status_is_not_compliant(self, status: str) -> None:
        results = [
            {"id": "A", "status": "PASS", "level": 1},
            {"id": "B", "status": status, "level": 1},
        ]

        predicate = _predicate(results)

        assert predicate["levels"]["1"]["compliant"] is False
        assert predicate["summary"]["level_achieved"] == 0

    def test_pending_assertion_is_not_compliant(self) -> None:
        results = [
            {"id": "A", "status": "PASS", "level": 1},
            {"id": "B", "status": "PASS", "level": 1, "assertion": _assertion("pending")},
        ]

        assert _predicate(results)["levels"]["1"]["compliant"] is False

    def test_honored_assertion_does_not_block_compliance(self) -> None:
        results = [
            {"id": "A", "status": "PASS", "level": 1},
            {"id": "B", "status": "N/A", "level": 1, "assertion": _assertion("honored")},
        ]

        predicate = _predicate(results)

        assert predicate["levels"]["1"]["compliant"] is True
        assert predicate["summary"]["level_achieved"] == 1
