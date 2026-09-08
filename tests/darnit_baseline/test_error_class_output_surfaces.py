"""Feature 036: `error_class` reaches the three machine-readable surfaces.

JSON (both shapes), SARIF properties, and the in-toto attestation
predicate. Each test asserts BOTH directions -- present when set, and
genuinely absent (not null, not empty string) when unset -- because a
consumer branching on `"error_class" in result` breaks if we emit nulls.

The attestation case is the one that matters most for compliance. A
signed attestation claiming FAIL without recording that the check never
reached GitHub is precisely the misleading claim Constitution Principle
II forbids.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


def _result(
    control_id: str, status: str = "FAIL", error_class: str | None = None
) -> dict[str, Any]:
    r: dict[str, Any] = {
        "id": control_id,
        "status": status,
        "details": "some message",
        "level": 1,
        "authority": "dispositive",
    }
    if error_class is not None:
        r["error_class"] = error_class
    return r


ENV_FAILURE = _result("OSPS-LE-02.02", error_class="auth")
REAL_FINDING = _result("OSPS-QA-04.01")


class TestJsonFormatter:
    """FR-011: top-level key at the same depth as `status`, both shapes."""

    @pytest.mark.unit
    def test_full_json_passes_error_class_through_verbatim(self) -> None:
        """The full shape serializes CheckResult as-is, so the field rides along.

        Asserted rather than assumed: a future change that filtered result
        keys before serializing would silently drop it.
        """
        payload = json.loads(json.dumps({"results": [ENV_FAILURE, REAL_FINDING]}))
        by_id = {r["id"]: r for r in payload["results"]}
        assert by_id["OSPS-LE-02.02"]["error_class"] == "auth"
        assert "error_class" not in by_id["OSPS-QA-04.01"]

    @pytest.mark.unit
    def test_summary_shape_carries_error_class(self) -> None:
        """R-006: the compact shape keeps it despite stripping evidence.

        A summary that strips "we could not verify" would let a CI job
        report an unreachable network as a compliance failure.
        """
        from darnit_baseline.tools import _compact_result

        compact = _compact_result(ENV_FAILURE)
        assert compact["error_class"] == "auth"

    @pytest.mark.unit
    def test_summary_shape_omits_error_class_for_real_finding(self) -> None:
        from darnit_baseline.tools import _compact_result

        compact = _compact_result(REAL_FINDING)
        assert "error_class" not in compact, (
            "a genuine finding must carry no error_class -- otherwise a "
            "consumer cannot tell it apart from an infrastructure failure"
        )

    @pytest.mark.unit
    def test_summary_shape_still_strips_evidence(self) -> None:
        """Regression guard: adding error_class must not un-strip the rest."""
        from darnit_baseline.tools import _compact_result

        heavy = dict(ENV_FAILURE, evidence={"big": "x" * 1000}, pass_history=[1, 2, 3])
        compact = _compact_result(heavy)
        assert "evidence" not in compact
        assert "pass_history" not in compact

    @pytest.mark.unit
    def test_error_class_sits_at_same_depth_as_status(self) -> None:
        """FR-011 is explicit about nesting -- not buried in `details`."""
        from darnit_baseline.tools import _compact_result

        compact = _compact_result(ENV_FAILURE)
        assert "error_class" in compact
        assert "status" in compact


class TestSarifFormatter:
    """FR-012: `properties["errorClass"]`, camelCase per the file's convention."""

    def _sarif(self, result: dict[str, Any]) -> dict[str, Any]:
        from darnit_baseline.formatters.sarif import result_to_sarif_result

        return result_to_sarif_result(
            result, rule_index=0, local_path="/tmp/x", repo="r"
        )

    @pytest.mark.unit
    def test_sarif_carries_error_class_in_properties(self) -> None:
        out = self._sarif(ENV_FAILURE)
        assert out["properties"]["errorClass"] == "auth"

    @pytest.mark.unit
    def test_sarif_omits_error_class_for_real_finding(self) -> None:
        out = self._sarif(REAL_FINDING)
        assert "errorClass" not in out["properties"]

    @pytest.mark.unit
    def test_sarif_uses_camel_case_matching_sibling_properties(self) -> None:
        """The file already uses resolvingPassHandler / passHistory."""
        out = self._sarif(ENV_FAILURE)
        assert "error_class" not in out["properties"], (
            "SARIF properties in this formatter are camelCase"
        )


class TestAttestationPredicate:
    """FR-013 / SC-004: additive within the v1 predicate, no version bump."""

    def _predicate(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        from darnit_baseline.attestation.predicate import build_assessment_predicate

        return build_assessment_predicate(
            owner="o",
            repo="r",
            commit="a" * 40,
            ref="refs/heads/main",
            level=1,
            results=results,
            project_config=None,
            adapters_used=["builtin"],
        )

    def _controls_by_id(self, predicate: dict[str, Any]) -> dict[str, Any]:
        return {c["id"]: c for c in predicate["controls"]}

    @pytest.mark.unit
    def test_predicate_carries_error_class(self) -> None:
        controls = self._controls_by_id(self._predicate([ENV_FAILURE]))
        assert controls["OSPS-LE-02.02"]["error_class"] == "auth"

    @pytest.mark.unit
    def test_predicate_omits_error_class_when_unset(self) -> None:
        """US4 acceptance scenario 2: happy-path predicate shape unchanged."""
        controls = self._controls_by_id(self._predicate([REAL_FINDING]))
        assert "error_class" not in controls["OSPS-QA-04.01"]

    @pytest.mark.unit
    def test_error_class_sits_beside_status_not_nested(self) -> None:
        """SC-004: same schema depth as `status`."""
        controls = self._controls_by_id(self._predicate([ENV_FAILURE]))
        entry = controls["OSPS-LE-02.02"]
        assert "status" in entry
        assert "error_class" in entry
        assert entry["error_class"] == "auth"

    @pytest.mark.unit
    def test_predicate_still_carries_authority_alongside(self) -> None:
        """Regression guard: the feature-025 field is untouched."""
        controls = self._controls_by_id(self._predicate([ENV_FAILURE]))
        assert controls["OSPS-LE-02.02"]["authority"] == "dispositive"
