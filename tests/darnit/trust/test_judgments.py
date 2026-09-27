"""Model judgments become PASS candidates, never PASS (feature 041, US3, T025, FR-010 to FR-014)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from darnit.config.operator.schema import OperatorConfig
from darnit.sieve.models import ControlSpec, LLMConsultationResponse, PassOutcome, SieveResult
from darnit.sieve.orchestrator import SieveOrchestrator
from darnit.trust import confirmations
from darnit.trust.confirmations import load_candidates, load_confirmations, record_confirmation
from darnit.trust.judgments import (
    PASS_CANDIDATE_CLAIM,
    Judgment,
    apply_stored_judgment,
    assess_judgment,
    evidence_digest,
    load_judgment_records,
    store_candidate,
)
from tests.darnit.trust.judgment_repo import (
    CI_VARS,
    CONTROL,
    EXCERPT,
    IDENTITY,
    README,
    audit,
    make_repo,
    write_operator_config,
)

CONSULTATION = {
    "prompt": "Does the README describe what the project is?",
    "control_id": CONTROL,
    "analysis_hints": ["Look for a purpose statement"],
    "gathered_evidence": {"dependency.OTHER.status": "WARN"},
    "file_contents": {"README.md": README},
}
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def data_root() -> Path:
    return confirmations.user_data_root()


def _spec() -> ControlSpec:
    return ControlSpec(control_id=CONTROL, level=1, domain="JUDGE", name="ReadmeDescribesProject", description="")


def _verify(status: PassOutcome, cited: list[str], consultation: dict | None = CONSULTATION, **kw) -> SieveResult:
    from darnit.sieve.models import CheckContext

    response = LLMConsultationResponse(
        status=status,
        confidence=kw.pop("confidence", 0.9),
        reasoning=kw.pop("reasoning", "The README states what the project is."),
        evidence_cited=cited,
        model="anthropic:claude-sonnet-5",
        model_version="claude-sonnet-5-20260801",
        **kw,
    )
    context = CheckContext(owner="example", repo="project", local_path=".", default_branch="main", control_id=CONTROL)
    return SieveOrchestrator().verify_with_llm_response(_spec(), context, response, consultation=consultation)


def _operator(**data: object) -> OperatorConfig:
    return OperatorConfig.model_validate({"schema_version": 1, **data})


def _pending() -> SieveResult:
    return SieveResult(
        control_id=CONTROL,
        status="PENDING",
        message="LLM consultation required",
        level=1,
        evidence={"llm_consultation": CONSULTATION},
        authority="suggestive",
        concluded_by="none",
        pending={"kind": "llm_judgment"},
    )


def _candidate() -> dict:
    judgment = Judgment(verdict="pass", reasoning="purpose stated", cited_evidence=(EXCERPT,), model="m")
    candidate = assess_judgment(judgment, CONSULTATION, source="harness").candidate
    assert candidate is not None
    return candidate


def _apply(now: datetime = NOW) -> SieveResult:
    candidates, confirmed = load_judgment_records(IDENTITY)
    return apply_stored_judgment(_pending(), IDENTITY, candidates=candidates, confirmations=confirmed, now=now)


@pytest.mark.unit
class TestJudgmentOutcomes:
    def test_positive_with_verified_citation_is_a_pass_candidate(self) -> None:
        result = _verify(PassOutcome.PASS, [EXCERPT])

        assert result.status == "PENDING"
        assert result.pending == {"kind": "confirmation"}
        assert result.authority == "suggestive"
        assert result.concluded_by == "none"
        candidate = result.candidate
        assert candidate is not None
        assert candidate["verdict"] == "pass"
        assert candidate["cited_evidence"] == [EXCERPT]
        assert candidate["model"] == "anthropic:claude-sonnet-5"
        assert candidate["model_version"] == "claude-sonnet-5-20260801"
        assert candidate["evidence_digest"] == evidence_digest(CONSULTATION)
        assert candidate["evidence_digest"].startswith("sha256:")
        assert candidate["source"] == "harness"
        assert candidate["reasoning"] == "The README states what the project is."

    def test_citations_match_after_whitespace_normalization(self) -> None:
        cited = "Project is a   command-line tool\n  that converts Markdown documents to HTML."

        assert _verify(PassOutcome.PASS, [cited]).pending == {"kind": "confirmation"}

    def test_confidence_does_not_decide(self) -> None:
        assert _verify(PassOutcome.PASS, [EXCERPT], confidence=0.05).pending == {"kind": "confirmation"}

    def test_unverifiable_citation_is_an_invalid_judgment(self) -> None:
        result = _verify(PassOutcome.PASS, [EXCERPT, "It has a documented disclosure process."])

        assert result.status == "WARN"
        assert result.candidate is None
        assert "It has a documented disclosure process." in result.message
        invalid = (result.evidence or {})["invalid_judgment"]
        assert invalid["missing_excerpts"] == ["It has a documented disclosure process."]

    def test_positive_without_citations_is_invalid(self) -> None:
        result = _verify(PassOutcome.PASS, [])

        assert result.status == "WARN"
        assert result.candidate is None

    def test_positive_without_gathered_content_is_invalid(self) -> None:
        result = _verify(PassOutcome.PASS, [EXCERPT], consultation=None)

        assert result.status == "WARN"
        assert result.candidate is None

    def test_negative_judgment_is_a_suggestive_fail(self) -> None:
        result = _verify(PassOutcome.FAIL, [], reasoning="The README is a placeholder.")

        assert result.status == "FAIL"
        assert result.authority == "suggestive"
        assert result.concluded_by == "llm_judgment"
        assert result.candidate is None

    def test_negative_judgment_citing_absent_text_is_invalid(self) -> None:
        assert _verify(PassOutcome.FAIL, ["TODO: write docs"]).status == "WARN"

    def test_inconclusive_judgment_is_warn(self) -> None:
        result = _verify(PassOutcome.INCONCLUSIVE, [])

        assert result.status == "WARN"
        assert result.authority == "suggestive"

    @pytest.mark.parametrize("error_class", ["unavailable", "evaluation"])
    def test_model_service_failure_is_error(self, error_class: str) -> None:
        result = _verify(PassOutcome.ERROR, [], reasoning="LLM call failed: timeout", error_class=error_class)

        assert result.status == "ERROR"
        assert result.error == {"class": error_class, "cause": "LLM call failed: timeout"}
        assert result.candidate is None


@pytest.mark.unit
class TestEvidenceDigest:
    def test_changes_with_content_prompt_and_hints(self) -> None:
        base = evidence_digest(CONSULTATION)

        assert evidence_digest({**CONSULTATION, "file_contents": {"README.md": README + "\nMore."}}) != base
        assert evidence_digest({**CONSULTATION, "prompt": "Is there a README?"}) != base
        assert evidence_digest({**CONSULTATION, "analysis_hints": []}) != base

    def test_ignores_other_gathered_evidence(self) -> None:
        changed = {**CONSULTATION, "gathered_evidence": {"dependency.OTHER.status": "PASS"}}

        assert evidence_digest(changed) == evidence_digest(CONSULTATION)


@pytest.mark.unit
class TestStoredCandidates:
    def test_stored_candidate_reads_as_a_candidate(self, data_root: Path) -> None:
        store_candidate(IDENTITY, CONTROL, _candidate())

        stored = json.loads((data_root / "trust" / "confirmations.json").read_text(encoding="utf-8"))
        assert stored["confirmations"] == []
        assert [c["claim"] for c in stored["candidates"]] == [PASS_CANDIDATE_CLAIM]
        assert load_confirmations(IDENTITY) == []

        result = _apply()
        assert result.status == "PENDING"
        assert result.pending == {"kind": "confirmation"}
        assert result.candidate == _candidate()

    def test_confirmation_gives_an_asserted_pass(self) -> None:
        store_candidate(IDENTITY, CONTROL, _candidate())
        record_confirmation(
            IDENTITY,
            CONTROL,
            PASS_CANDIDATE_CLAIM,
            evidence_digest(CONSULTATION),
            _operator(operator={"identity": "alice@example.com"}),
            now=NOW,
        )

        result = _apply()

        assert result.status == "PASS"
        assert result.authority == "asserted"
        assert result.concluded_by == "confirmation"
        assert result.pending is None
        assert result.confirmation == {
            "confirmed_by": "alice@example.com",
            "confirmed_at": "2026-09-01T12:00:00Z",
            "expires_at": "2027-02-28T12:00:00Z",
        }

    def test_recording_a_confirmation_keeps_candidates(self) -> None:
        store_candidate(IDENTITY, CONTROL, _candidate())
        record_confirmation(IDENTITY, "OTHER-01", "not_applicable", "d", _operator(), now=NOW)

        assert len(load_candidates(IDENTITY)) == 1

    def test_expired_confirmation_lapses_to_awaiting_judgment(self) -> None:
        store_candidate(IDENTITY, CONTROL, _candidate())
        record_confirmation(
            IDENTITY, CONTROL, PASS_CANDIDATE_CLAIM, evidence_digest(CONSULTATION), _operator(), now=NOW
        )

        result = _apply(now=NOW + timedelta(days=181))

        assert result.status == "PENDING"
        assert result.pending == {"kind": "llm_judgment"}
        assert "expired" in result.message

    def test_new_candidate_after_expiry_awaits_confirmation_again(self) -> None:
        record_confirmation(
            IDENTITY, CONTROL, PASS_CANDIDATE_CLAIM, evidence_digest(CONSULTATION), _operator(), now=NOW
        )
        store_candidate(IDENTITY, CONTROL, _candidate(), now=NOW + timedelta(days=181))

        assert load_confirmations(IDENTITY) == []
        assert _apply(now=NOW + timedelta(days=181)).pending == {"kind": "confirmation"}

    def test_confirmation_for_other_evidence_lapses(self) -> None:
        record_confirmation(IDENTITY, CONTROL, PASS_CANDIDATE_CLAIM, "sha256:old", _operator(), now=NOW)

        result = _apply()

        assert result.pending == {"kind": "llm_judgment"}
        assert "evidence changed" in result.message

    def test_other_repository_sees_nothing(self) -> None:
        store_candidate(IDENTITY, CONTROL, _candidate())

        candidates, confirmed = load_judgment_records("github.com/other/repo")
        result = apply_stored_judgment(
            _pending(), "github.com/other/repo", candidates=candidates, confirmations=confirmed
        )
        assert result.pending == {"kind": "llm_judgment"}

    def test_refuses_to_store_inside_the_checkout(self, data_root: Path) -> None:
        with pytest.raises(ValueError, match="inside the audited repository"):
            store_candidate(IDENTITY, CONTROL, _candidate(), checkout=data_root.parent)


@pytest.mark.integration
class TestAuditAppliesStoredJudgments:
    """The canonical audit pipeline turns stored records into results (T032)."""

    @pytest.fixture(autouse=True)
    def _outside_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in CI_VARS:
            monkeypatch.delenv(var, raising=False)

    def _store_candidate_for(self, repo: Path) -> dict:
        consultation = audit(repo)["evidence"]["llm_consultation"]
        judgment = Judgment(verdict="pass", reasoning="purpose stated", cited_evidence=(EXCERPT,), model="m")
        candidate = assess_judgment(judgment, consultation, source="harness").candidate
        assert candidate is not None
        store_candidate(IDENTITY, CONTROL, candidate, checkout=repo)
        return candidate

    def test_candidate_confirmation_and_lapse(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        write_operator_config(tmp_path)
        assert audit(repo)["pending"] == {"kind": "llm_judgment"}

        candidate = self._store_candidate_for(repo)
        result = audit(repo)
        assert result["status"] == "PENDING"
        assert result["pending"] == {"kind": "confirmation"}
        assert result["candidate"] == candidate

        record_confirmation(IDENTITY, CONTROL, PASS_CANDIDATE_CLAIM, candidate["evidence_digest"], _operator())
        result = audit(repo)
        assert result["status"] == "PASS"
        assert result["authority"] == "asserted"
        assert result["concluded_by"] == "confirmation"
        assert set(result["confirmation"]) == {"confirmed_by", "confirmed_at", "expires_at"}

        make_repo(tmp_path, readme=README + "\nNow with a changelog.\n")
        result = audit(repo)
        assert result["status"] == "PENDING"
        assert result["pending"] == {"kind": "llm_judgment"}

    def test_rubric_change_lapses_the_confirmation(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        write_operator_config(tmp_path)
        candidate = self._store_candidate_for(repo)
        record_confirmation(IDENTITY, CONTROL, PASS_CANDIDATE_CLAIM, candidate["evidence_digest"], _operator())
        assert audit(repo)["status"] == "PASS"

        write_operator_config(tmp_path, prompt="Does the README explain how to install the project?")

        assert audit(repo)["pending"] == {"kind": "llm_judgment"}

    def test_unnamed_repository_does_not_read_the_store(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        write_operator_config(tmp_path)
        self._store_candidate_for(repo)

        assert audit(repo, target=None)["pending"] == {"kind": "llm_judgment"}

    def test_a_candidate_is_non_compliant(self, tmp_path: Path) -> None:
        from darnit.tools.audit import calculate_compliance

        repo = make_repo(tmp_path)
        write_operator_config(tmp_path)
        self._store_candidate_for(repo)
        result = audit(repo)

        assert calculate_compliance([result], level=1) == {1: False}
