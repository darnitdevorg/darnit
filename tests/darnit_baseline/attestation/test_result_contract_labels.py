"""Attestations label feature 041 result-contract statuses (T050, FR-006, FR-009)."""

from __future__ import annotations

from typing import Any

import pytest

from darnit_baseline.attestation.predicate import build_assessment_predicate

CANDIDATE = {
    "verdict": "pass",
    "reasoning": "The README explains installation and usage.",
    "cited_evidence": ["## Installation", "pip install example"],
    "model": "claude-sonnet-5",
    "model_version": "2026-08-01",
    "evidence_digest": "sha256:abc",
    "source": "harness",
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


def _pass(control_id: str = "OSPS-LE-03.01", level: int = 1) -> dict[str, Any]:
    return {
        "id": control_id,
        "status": "PASS",
        "level": level,
        "authority": "dispositive",
        "concluded_by": "file_exists",
    }


def _awaiting_judgment() -> dict[str, Any]:
    return {
        "id": "OSPS-GV-01.01",
        "status": "PENDING",
        "level": 1,
        "details": "LLM consultation required",
        "authority": "suggestive",
        "concluded_by": "none",
        "pending": {"kind": "llm_judgment"},
    }


def _candidate() -> dict[str, Any]:
    return {
        "id": "OSPS-DO-01.01",
        "status": "PENDING",
        "level": 1,
        "details": "PASS candidate from a model judgment; not compliant until an operator confirms it",
        "authority": "suggestive",
        "concluded_by": "none",
        "pending": {"kind": "confirmation"},
        "candidate": dict(CANDIDATE),
    }


def _confirmed() -> dict[str, Any]:
    return {
        "id": "OSPS-DO-01.01",
        "status": "PASS",
        "level": 1,
        "details": "PASS candidate confirmed by @operator",
        "authority": "asserted",
        "concluded_by": "confirmation",
        "candidate": dict(CANDIDATE),
        "confirmation": {
            "confirmed_by": "@operator",
            "confirmed_at": "2026-09-27T00:00:00+00:00",
            "expires_at": "2027-09-27T00:00:00+00:00",
        },
    }


def _model_finding() -> dict[str, Any]:
    return {
        "id": "OSPS-VM-02.01",
        "status": "FAIL",
        "level": 1,
        "details": "Model finding: the policy states there is no disclosure process",
        "authority": "suggestive",
        "concluded_by": "llm_judgment",
    }


def _error() -> dict[str, Any]:
    return {
        "id": "OSPS-AC-03.01",
        "status": "ERROR",
        "level": 1,
        "details": "HTTP 403 from the platform API",
        "authority": "dispositive",
        "concluded_by": "gh_api",
        "error_class": "auth",
        "error": {"class": "auth", "cause": "HTTP 403 from the platform API"},
    }


@pytest.mark.unit
class TestResultContractLabels:
    def test_pending_carries_its_kind(self) -> None:
        control = _control(_predicate([_awaiting_judgment()]), "OSPS-GV-01.01")

        assert control["status"] == "PENDING"
        assert control["pending"] == {"kind": "llm_judgment"}
        assert control["concluded_by"] == "none"
        assert "candidate" not in control

    def test_candidate_never_reads_as_pass(self) -> None:
        predicate = _predicate([_candidate()])
        control = _control(predicate, "OSPS-DO-01.01")

        assert control["status"] == "PENDING"
        assert control["pending"] == {"kind": "confirmation"}
        assert control["authority"] == "suggestive"
        assert control["candidate"]["confirmed"] is False
        assert "verdict" not in control["candidate"]
        assert control["candidate"]["model"] == "claude-sonnet-5"
        assert control["candidate"]["model_version"] == "2026-08-01"
        assert control["candidate"]["source"] == "harness"
        assert control["candidate"]["evidence_digest"] == "sha256:abc"
        assert control["candidate"]["cited_evidence"] == CANDIDATE["cited_evidence"]
        assert "PASS" not in {c["status"] for c in predicate["controls"]}
        assert predicate["summary"]["passed"] == 0
        assert predicate["summary"]["pending"] == 1
        assert predicate["summary"]["pass_candidates"] == 1
        assert predicate["levels"]["1"]["compliant"] is False
        assert predicate["summary"]["level_achieved"] == 0

    def test_model_finding_is_labelled(self) -> None:
        control = _control(_predicate([_model_finding()]), "OSPS-VM-02.01")

        assert control["status"] == "FAIL"
        assert control["authority"] == "suggestive"
        assert control["concluded_by"] == "llm_judgment"

    def test_confirmed_candidate_is_asserted_pass_with_confirmation(self) -> None:
        predicate = _predicate([_confirmed()])
        control = _control(predicate, "OSPS-DO-01.01")

        assert control["status"] == "PASS"
        assert control["authority"] == "asserted"
        assert control["concluded_by"] == "confirmation"
        assert control["confirmation"] == {
            "confirmed_by": "@operator",
            "confirmed_at": "2026-09-27T00:00:00+00:00",
            "expires_at": "2027-09-27T00:00:00+00:00",
        }
        assert control["candidate"]["confirmed"] is True
        assert predicate["summary"]["pass_candidates"] == 0
        assert predicate["levels"]["1"]["compliant"] is True

    def test_error_carries_class_and_cause(self) -> None:
        control = _control(_predicate([_error()]), "OSPS-AC-03.01")

        assert control["status"] == "ERROR"
        assert control["error"] == {"class": "auth", "cause": "HTTP 403 from the platform API"}
        assert control["error_class"] == "auth"

    def test_error_without_error_block_falls_back_to_class_and_details(self) -> None:
        result = _error()
        del result["error"]

        control = _control(_predicate([result]), "OSPS-AC-03.01")

        assert control["error"] == {"class": "auth", "cause": "HTTP 403 from the platform API"}

    def test_deterministic_pass_has_no_judgment_labels(self) -> None:
        control = _control(_predicate([_pass()]), "OSPS-LE-03.01")

        assert control["concluded_by"] == "file_exists"
        for key in ("pending", "candidate", "confirmation", "error"):
            assert key not in control


@pytest.mark.unit
class TestComplianceCounting:
    """Only PASS and N/A are compliant; WARN, ERROR, PENDING, and candidates are not."""

    @pytest.mark.parametrize(
        "blocker",
        [
            {"id": "OSPS-X-01.01", "status": "WARN", "level": 1},
            _error(),
            _awaiting_judgment(),
            _candidate(),
        ],
        ids=["warn", "error", "pending", "candidate"],
    )
    def test_non_pass_status_blocks_the_level(self, blocker: dict[str, Any]) -> None:
        predicate = _predicate([_pass(), blocker])

        assert predicate["levels"]["1"]["failed"] == 0
        assert predicate["levels"]["1"]["compliant"] is False
        assert predicate["summary"]["level_achieved"] == 0

    def test_level_counts_every_bucket(self) -> None:
        predicate = _predicate(
            [
                _pass(),
                _model_finding(),
                {"id": "OSPS-X-01.01", "status": "WARN", "level": 1},
                _error(),
                _awaiting_judgment(),
                _candidate(),
            ]
        )

        assert predicate["levels"]["1"] == {
            "total": 6,
            "passed": 1,
            "failed": 1,
            "warnings": 1,
            "errors": 1,
            "pending": 2,
            "pass_candidates": 1,
            "compliant": False,
        }

    def test_all_pass_or_na_is_compliant(self) -> None:
        predicate = _predicate([_pass(), {"id": "OSPS-X-01.01", "status": "N/A", "level": 1}])

        assert predicate["levels"]["1"]["compliant"] is True
        assert predicate["summary"]["level_achieved"] == 1
