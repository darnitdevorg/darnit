"""Model judgments and PASS candidates (feature 041, FR-010 to FR-015).

A model judgment never concludes a control. A positive judgment whose cited
excerpts all appear in the content the step gathered becomes a PASS
candidate: non-compliant until a person confirms it through the feature 040
confirmation store (claim ``pass_candidate``). A negative judgment is a
suggestive FAIL; a judgment citing text that is not there is invalid.

The evidence digest covers the judged content and the control's rubric, so a
confirmation lapses when either changes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from darnit.sieve.models import SieveResult, VerificationPhase
from darnit.trust.confirmations import (
    Confirmation,
    StoredCandidate,
    find_confirmation,
    load_candidates,
    load_confirmations,
    record_candidate,
)

PASS_CANDIDATE_CLAIM = "pass_candidate"

Verdict = Literal["pass", "fail", "inconclusive"]
CandidateSource = Literal["harness", "mcp_agent"]
CANDIDATE_SOURCES: frozenset[str] = frozenset(("harness", "mcp_agent"))


@dataclass(frozen=True)
class Judgment:
    verdict: Verdict
    reasoning: str
    cited_evidence: tuple[str, ...] = ()
    model: str = ""
    model_version: str = ""
    confidence: float | None = None


@dataclass(frozen=True)
class JudgmentAssessment:
    """What a judgment amounts to under FR-010 to FR-014."""

    kind: Literal["candidate", "finding", "inconclusive", "invalid"]
    reason: str = ""
    candidate: dict[str, Any] | None = None
    missing_excerpts: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredJudgment:
    """What the operator-side store says about one control's current evidence."""

    state: Literal["confirmed", "candidate", "lapsed"]
    candidate: dict[str, Any] | None = None
    confirmation: Confirmation | None = None
    reason: str = ""


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def judged_content(consultation: Mapping[str, Any] | None) -> dict[str, str]:
    """The file contents the model step gathered: what citations are checked against."""
    contents = (consultation or {}).get("file_contents") or {}
    return {str(name): str(text) for name, text in contents.items()}


def evidence_digest(consultation: Mapping[str, Any] | None) -> str:
    consultation = consultation or {}
    payload = {
        "content": judged_content(consultation),
        "prompt": str(consultation.get("prompt") or ""),
        "analysis_hints": [str(h) for h in consultation.get("analysis_hints") or []],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def missing_excerpts(cited: Iterable[str], consultation: Mapping[str, Any] | None) -> list[str]:
    """Cited excerpts that do not appear verbatim (whitespace-normalized) in the judged content."""
    haystacks = [normalize_whitespace(text) for text in judged_content(consultation).values()]
    missing = []
    for excerpt in cited:
        needle = normalize_whitespace(str(excerpt))
        if not needle or not any(needle in haystack for haystack in haystacks):
            missing.append(str(excerpt))
    return missing


def assess_judgment(
    judgment: Judgment, consultation: Mapping[str, Any] | None, *, source: CandidateSource
) -> JudgmentAssessment:
    """Apply the judgment rules (framework-design.md 3.5) to one judgment."""
    if source not in CANDIDATE_SOURCES:
        raise ValueError(f"source={source!r} is not one of {sorted(CANDIDATE_SOURCES)}")
    if judgment.verdict == "inconclusive":
        return JudgmentAssessment(kind="inconclusive", reason="the model could not decide from the evidence")
    if judgment.verdict == "pass" and not judgment.cited_evidence:
        return JudgmentAssessment(
            kind="invalid", reason="a positive judgment must cite verbatim excerpts of the content it was given"
        )
    missing = missing_excerpts(judgment.cited_evidence, consultation)
    if missing:
        return JudgmentAssessment(
            kind="invalid",
            reason="cited excerpts not found in the content the step gathered: " + "; ".join(repr(m) for m in missing),
            missing_excerpts=tuple(missing),
        )
    if judgment.verdict == "fail":
        return JudgmentAssessment(kind="finding", reason=judgment.reasoning)
    candidate: dict[str, Any] = {
        "verdict": "pass",
        "reasoning": judgment.reasoning,
        "cited_evidence": list(judgment.cited_evidence),
        "model": judgment.model,
        "model_version": judgment.model_version,
        "evidence_digest": evidence_digest(consultation),
        "source": source,
    }
    if judgment.confidence is not None:
        candidate["confidence"] = judgment.confidence
    return JudgmentAssessment(kind="candidate", reason=judgment.reasoning, candidate=candidate)


def store_candidate(
    repository: str,
    control_id: str,
    candidate: Mapping[str, Any],
    *,
    checkout: str | Path | None = None,
    now: datetime | None = None,
) -> StoredCandidate:
    return record_candidate(
        repository,
        control_id,
        PASS_CANDIDATE_CLAIM,
        str(candidate["evidence_digest"]),
        dict(candidate),
        checkout=checkout,
        now=now,
    )


def stored_judgment(
    repository: str | None,
    control_id: str,
    digest: str,
    *,
    candidates: Iterable[StoredCandidate],
    confirmations: Iterable[Confirmation],
    now: datetime | None = None,
) -> StoredJudgment | None:
    """The stored candidate or confirmation that applies to this control's current evidence, if any."""
    if repository is None:
        return None
    now = now or datetime.now(UTC)
    key = (repository, control_id, PASS_CANDIDATE_CLAIM)
    confirmations = [c for c in confirmations if (c.repository, c.control_id, c.claim) == key]
    candidate = next(
        (
            c.candidate
            for c in candidates
            if (c.repository, c.control_id, c.claim) == key and c.evidence_digest == digest
        ),
        None,
    )
    confirmed = find_confirmation(confirmations, repository, control_id, PASS_CANDIDATE_CLAIM, digest, now=now)
    if confirmed is not None:
        return StoredJudgment(state="confirmed", candidate=candidate, confirmation=confirmed)
    if any(c.evidence_digest == digest for c in confirmations):
        return StoredJudgment(state="lapsed", reason="the confirmation of its PASS candidate expired")
    if candidate is not None:
        return StoredJudgment(state="candidate", candidate=candidate)
    if confirmations:
        return StoredJudgment(state="lapsed", reason="the evidence changed since its PASS candidate was confirmed")
    return None


def load_judgment_records(
    repository: str | None, *, checkout: str | Path | None = None
) -> tuple[list[StoredCandidate], list[Confirmation]]:
    if repository is None:
        return [], []
    return (
        load_candidates(repository, checkout=checkout),
        [c for c in load_confirmations(repository, checkout=checkout) if c.claim == PASS_CANDIDATE_CLAIM],
    )


def awaiting_judgment(result: SieveResult) -> bool:
    return result.status == "PENDING" and (result.pending or {}).get("kind") == "llm_judgment"


def apply_stored_judgment(
    result: SieveResult,
    repository: str | None,
    *,
    candidates: Iterable[StoredCandidate],
    confirmations: Iterable[Confirmation],
    now: datetime | None = None,
) -> SieveResult:
    """Replace a PENDING (llm_judgment) result with what the store says about its current evidence."""
    if not awaiting_judgment(result):
        return result
    consultation = (result.evidence or {}).get("llm_consultation")
    if not consultation:
        return result
    stored = stored_judgment(
        repository,
        result.control_id,
        evidence_digest(consultation),
        candidates=candidates,
        confirmations=confirmations,
        now=now,
    )
    if stored is None:
        return result
    if stored.state == "lapsed":
        return dataclasses.replace(result, message=f"Model judgment required: {stored.reason}")
    if stored.state == "candidate":
        return candidate_result(result, stored.candidate or {})
    confirmation = stored.confirmation
    assert confirmation is not None
    return dataclasses.replace(
        result,
        status="PASS",
        message=f"PASS candidate confirmed by {confirmation.confirmed_by} at {confirmation.confirmed_at}",
        conclusive_phase=VerificationPhase.LLM,
        authority="asserted",
        concluded_by="confirmation",
        pending=None,
        candidate=stored.candidate,
        confirmation=confirmation.report(),
    )


def candidate_result(result: SieveResult, candidate: Mapping[str, Any]) -> SieveResult:
    """``result`` as a PASS candidate awaiting confirmation."""
    return dataclasses.replace(
        result,
        status="PENDING",
        message=(
            "PASS candidate from a model judgment; not compliant until an operator confirms it: "
            f"{candidate.get('reasoning', '')}"
        ),
        conclusive_phase=VerificationPhase.LLM,
        authority="suggestive",
        concluded_by="none",
        pending={"kind": "confirmation"},
        candidate=dict(candidate),
    )
