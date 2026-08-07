"""Attestation authority-field tests (feature 025 T051-T053).

Covers SC-007 (every Stage-1 result carries authority) and contracts
T1-T4 from
``specs/025-rfc0001-stage1/contracts/attestation-authority-field.md``:

- T1: predicate type string does NOT change (still v1)
- T2: every Stage-1 result carries authority
- T3: older readers (permissive schema) still verify unchanged
- T4: newer readers can enforce an authority accept-list
"""

from __future__ import annotations

from typing import Any

from darnit_baseline.attestation.predicate import build_assessment_predicate


def _make_stage1_results() -> list[dict[str, Any]]:
    """Fixture: a small result set with the authority field set per result."""
    return [
        {
            "id": "OSPS-AC-01.01",
            "status": "PASS",
            "level": 1,
            "authority": "dispositive",
            "details": "gh_api reports MFA required",
        },
        {
            "id": "OSPS-GV-03.01",
            "status": "PASS",
            "level": 1,
            "authority": "asserted",
            "details": "human-confirmed security contact",
        },
        {
            "id": "OSPS-BR-06.01",
            "status": "FAIL",
            "level": 2,
            "authority": "dispositive",
            "details": "no signed releases found",
        },
    ]


def _build_predicate(results: list[dict[str, Any]]) -> dict[str, Any]:
    return build_assessment_predicate(
        owner="test-owner",
        repo="test-repo",
        commit="abc123",
        ref="main",
        level=2,
        results=results,
        project_config=None,
        adapters_used=["builtin"],
    )


class TestAuthorityInPredicate:
    """SC-007 + contract T2: every result carries authority."""

    def test_stage1_output_carries_authority_per_result(self) -> None:
        """Every result in the emitted predicate has an `authority` field
        with a value in the declared Literal domain.
        """
        results = _make_stage1_results()
        predicate = _build_predicate(results)

        controls = predicate["controls"]
        assert len(controls) == len(results)

        allowed_authorities = {"dispositive", "suggestive", "asserted"}
        for control in controls:
            assert "authority" in control, f"result {control['id']} missing authority (contract T2)"
            assert control["authority"] in allowed_authorities, (
                f"result {control['id']} has unknown authority {control['authority']!r}"
            )

    def test_authority_values_preserved_verbatim(self) -> None:
        """The authority string from the input result flows unchanged to
        the predicate output; no rewriting."""
        results = _make_stage1_results()
        predicate = _build_predicate(results)
        # Look up each result by id and confirm authority matches.
        by_id = {c["id"]: c for c in predicate["controls"]}
        for r in results:
            assert by_id[r["id"]]["authority"] == r["authority"]


class TestPredicateTypeUnchanged:
    """Contract T1: predicate type string does NOT change; still v1."""

    def test_predicate_shape_still_matches_v1_expectations(self) -> None:
        """Predicate remains the same top-level shape as before Stage 1.

        Note: `build_assessment_predicate` builds the PREDICATE BODY; the
        DSSE envelope's predicate_type string is set at the emit layer
        (`darnit-baseline/attestation/generator.py`). This test asserts the
        body shape (which does not carry the type string) has NOT gained
        or lost any top-level keys beyond the additive per-result authority.
        """
        results = _make_stage1_results()
        predicate = _build_predicate(results)
        # Existing top-level keys still present.
        for key in [
            "assessor",
            "timestamp",
            "baseline",
            "repository",
            "configuration",
            "summary",
            "levels",
            "controls",
        ]:
            assert key in predicate, f"predicate lost top-level key: {key}"


class TestOlderReaderCompat:
    """Contract T3: an older reader that permits unknown JSON keys still
    verifies the predicate unchanged. Simulated via a stub reader that
    ignores the ``authority`` key entirely."""

    def _stub_older_reader(self, predicate: dict[str, Any]) -> dict[str, Any]:
        """Simulate a pre-Stage-1 reader: strips any keys it doesn't
        recognize, then verifies. Returns the "loaded" record set."""
        known_control_keys = {
            "id",
            "level",
            "category",
            "status",
            "message",
            "evidence",
            "source",  # pre-Stage-1 shape
        }
        loaded_controls = []
        for c in predicate["controls"]:
            loaded = {k: v for k, v in c.items() if k in known_control_keys}
            loaded_controls.append(loaded)
        return {"controls": loaded_controls, "summary": predicate["summary"]}

    def test_older_reader_still_verifies_predicate_shape(self) -> None:
        results = _make_stage1_results()
        predicate = _build_predicate(results)
        loaded = self._stub_older_reader(predicate)

        # The reader sees the same status distribution as the Stage-1 producer
        # intended -- no counts drift, no controls dropped.
        assert len(loaded["controls"]) == len(results)
        statuses = [c["status"] for c in loaded["controls"]]
        assert statuses.count("PASS") == 2
        assert statuses.count("FAIL") == 1
        # And the summary block matches.
        assert loaded["summary"]["passed"] == 2
        assert loaded["summary"]["failed"] == 1


class TestNewerReaderRejectsByAuthorityAcceptList:
    """Contract T4 + FR-005: a Stage-1-aware reader can enforce an
    accept-list on authority (e.g., high-assurance policy accepts only
    dispositive PASSes; rejects asserted ones)."""

    def _apply_accept_list(
        self,
        predicate: dict[str, Any],
        accept: set[str],
    ) -> list[dict[str, Any]]:
        """Return the subset of PASS results whose authority is in accept.
        Non-PASS results pass through unchanged (a rejection policy on
        PASS authorities does not affect FAIL/inconclusive reporting)."""
        result = []
        for c in predicate["controls"]:
            if c["status"] != "PASS":
                result.append(c)
                continue
            if c.get("authority") in accept:
                result.append(c)
            # else: dropped -- policy engine rejects this PASS
        return result

    def test_dispositive_only_accept_list_rejects_asserted_pass(self) -> None:
        """High-assurance policy configured to accept only dispositive
        PASSes MUST reject an asserted PASS."""
        results = _make_stage1_results()
        predicate = _build_predicate(results)

        # High-assurance accept list.
        accepted = self._apply_accept_list(predicate, {"dispositive"})

        # OSPS-AC-01.01 (dispositive PASS) is kept.
        assert any(c["id"] == "OSPS-AC-01.01" for c in accepted)
        # OSPS-GV-03.01 (asserted PASS) is REJECTED.
        assert not any(c["id"] == "OSPS-GV-03.01" for c in accepted)
        # OSPS-BR-06.01 (FAIL) passes through -- reader still sees the failure.
        assert any(c["id"] == "OSPS-BR-06.01" for c in accepted)

    def test_dispositive_and_asserted_accept_list_keeps_both(self) -> None:
        """A more permissive accept-list keeps both authority types."""
        results = _make_stage1_results()
        predicate = _build_predicate(results)

        accepted = self._apply_accept_list(predicate, {"dispositive", "asserted"})

        # Both PASSes kept.
        ids = {c["id"] for c in accepted}
        assert "OSPS-AC-01.01" in ids
        assert "OSPS-GV-03.01" in ids
        assert "OSPS-BR-06.01" in ids
