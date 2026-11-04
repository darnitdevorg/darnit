"""Summary rows carry ``pending`` so a client can tell a judgment request from a PASS candidate (#644)."""

from __future__ import annotations

import pytest

from darnit_baseline.tools import _compact_result

AWAITING_JUDGMENT = {
    "id": "OSPS-DO-01.01",
    "status": "PENDING",
    "level": 1,
    "details": "LLM consultation required",
    "pending": {"kind": "llm_judgment"},
    "evidence": {"llm_consultation": {"prompt": "p", "file_contents": {"README.md": "x" * 10_000}}},
}

CANDIDATE = {
    "id": "OSPS-GV-01.01",
    "status": "PENDING",
    "level": 1,
    "details": "PASS candidate from a model judgment; not compliant until an operator confirms it: r",
    "pending": {"kind": "confirmation"},
    "candidate": {
        "verdict": "pass",
        "reasoning": "GOVERNANCE.md names the maintainers.",
        "cited_evidence": ["Maintainers: @alice", "Decisions by consensus"],
        "model": "claude-opus-5-5",
        "model_version": "claude-opus-5-5",
        "evidence_digest": "sha256:abc",
        "source": "mcp_agent",
    },
}


@pytest.mark.unit
class TestSummaryPending:
    def test_awaiting_judgment_row_carries_its_kind_and_no_evidence(self) -> None:
        compact = _compact_result(AWAITING_JUDGMENT)

        assert compact["pending"] == {"kind": "llm_judgment"}
        assert "evidence" not in compact

    def test_candidate_row_carries_a_candidate_summary_without_excerpts(self) -> None:
        compact = _compact_result(CANDIDATE)

        assert compact["pending"] == {
            "kind": "confirmation",
            "candidate": {
                "model": "claude-opus-5-5",
                "reasoning": "GOVERNANCE.md names the maintainers.",
                "cited_excerpts": 2,
            },
        }
        assert "Maintainers: @alice" not in str(compact)

    def test_concluded_row_has_no_pending(self) -> None:
        compact = _compact_result({"id": "X", "status": "PASS", "level": 1, "details": "ok"})

        assert "pending" not in compact
