"""ERROR at a level makes it non-compliant (feature 041 US2, FR-009)."""

from __future__ import annotations

import pytest

from darnit.tools.audit import calculate_compliance


def _r(control_id: str, status: str, level: int = 1, **extra) -> dict:
    return {"id": control_id, "status": status, "level": level, "details": "", **extra}


def test_all_pass_is_compliant() -> None:
    assert calculate_compliance([_r("A", "PASS"), _r("B", "PASS")], level=1) == {1: True}


def test_one_error_makes_level_non_compliant() -> None:
    results = [_r("A", "PASS"), _r("B", "ERROR", error={"class": "auth", "cause": "HTTP 403"})]
    assert calculate_compliance(results, level=1) == {1: False}


def test_error_only_affects_its_own_level() -> None:
    results = [
        _r("A", "PASS", 1),
        _r("B", "PASS", 2),
        _r("C", "ERROR", 2, error={"class": "rate_limit", "cause": "429"}),
    ]
    assert calculate_compliance(results, level=2) == {1: True, 2: False}


def test_error_with_na_controls_is_still_non_compliant() -> None:
    results = [_r("A", "N/A"), _r("B", "ERROR", error={"class": "missing_tool", "cause": "gh"})]
    assert calculate_compliance(results, level=1) == {1: False}


@pytest.mark.parametrize("status", ["FAIL", "WARN", "ERROR", "PENDING"])
def test_every_non_pass_status_is_non_compliant(status: str) -> None:
    assert calculate_compliance([_r("A", "PASS"), _r("B", status)], level=1) == {1: False}
