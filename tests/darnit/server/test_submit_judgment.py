"""The submit_judgment MCP tool (feature 041, US3, T026, FR-015)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from darnit.server.tools.judgments import confirm_pass_candidate, submit_judgment, submit_judgment_impl
from darnit.trust.confirmations import load_candidates, load_confirmations
from tests.darnit.trust.judgment_repo import (
    CI_VARS,
    CONTROL,
    EXCERPT,
    FRAMEWORK,
    IDENTITY,
    OWNER,
    REPO,
    audit,
    make_repo,
    write_operator_config,
)


@pytest.fixture(autouse=True)
def _outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in CI_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = make_repo(tmp_path)
    write_operator_config(tmp_path)
    return path


def _submit(checkout: Path, **overrides: object) -> dict:
    args: dict = {
        "control_id": CONTROL,
        "verdict": "pass",
        "reasoning": "The README states what the project is.",
        "cited_evidence": [EXCERPT],
        "model": "claude-opus-5-5",
        "model_version": "claude-opus-5-5",
        "owner": OWNER,
        "repo": REPO,
        "local_path": str(checkout),
        "framework_name": FRAMEWORK,
    }
    args.update(overrides)
    return submit_judgment_impl(**args)


@pytest.mark.integration
class TestSubmitJudgment:
    def test_pass_is_stored_as_a_candidate_and_the_next_audit_shows_it(self, repo: Path) -> None:
        response = _submit(repo)

        assert response["status"] == "candidate"
        assert response["stored"] is True
        candidate = response["candidate"]
        assert candidate["source"] == "mcp_agent"
        assert candidate["cited_evidence"] == [EXCERPT]
        assert candidate["model"] == "claude-opus-5-5"

        [stored] = load_candidates(IDENTITY)
        assert stored.control_id == CONTROL
        assert stored.claim == "pass_candidate"
        assert stored.evidence_digest == candidate["evidence_digest"]
        assert load_confirmations(IDENTITY) == []
        assert not any(p.name == "confirmations.json" for p in repo.rglob("*"))

        result = audit(repo)
        assert result["status"] == "PENDING"
        assert result["pending"] == {"kind": "confirmation"}
        assert result["candidate"]["source"] == "mcp_agent"

    def test_fail_is_a_suggestive_finding_and_nothing_is_stored(self, repo: Path) -> None:
        response = _submit(repo, verdict="fail", cited_evidence=[], reasoning="Too thin.")

        assert response["status"] == "finding"
        assert response["stored"] is False
        assert response["finding"]["status"] == "FAIL"
        assert response["finding"]["authority"] == "suggestive"
        assert response["finding"]["concluded_by"] == "llm_judgment"
        assert load_candidates() == []
        assert audit(repo)["pending"] == {"kind": "llm_judgment"}

    def test_unverifiable_citation_is_rejected_and_nothing_is_stored(self, repo: Path) -> None:
        response = _submit(repo, cited_evidence=[EXCERPT, "Security reports go to security@example.com."])

        assert response["status"] == "rejected"
        assert response["rejection"]["missing_excerpts"] == ["Security reports go to security@example.com."]
        assert load_candidates() == []
        assert audit(repo)["pending"] == {"kind": "llm_judgment"}

    def test_pass_without_citations_is_rejected(self, repo: Path) -> None:
        response = _submit(repo, cited_evidence=[])

        assert response["status"] == "rejected"
        assert load_candidates() == []

    def test_citations_are_checked_against_the_repository_not_the_client(self, repo: Path) -> None:
        (repo / "README.md").write_text("# Project\n\nTODO\n", encoding="utf-8")

        response = _submit(repo)

        assert response["status"] == "rejected"
        assert response["rejection"]["missing_excerpts"] == [EXCERPT]

    def test_repository_must_be_named(self, repo: Path) -> None:
        response = _submit(repo, owner="", repo="")

        assert response["status"] == "rejected"
        assert "name the audited repository" in response["rejection"]["reason"]
        assert load_candidates() == []

    def test_control_without_a_model_step_is_rejected(self, repo: Path) -> None:
        response = _submit(repo, control_id="HELLO-01.01")

        assert response["status"] == "rejected"
        assert "does not reach a model judgment step" in response["rejection"]["reason"]

    def test_unknown_verdict_is_rejected(self, repo: Path) -> None:
        assert _submit(repo, verdict="PASS")["status"] == "rejected"

    def test_async_tool_requires_a_framework(self, repo: Path) -> None:
        response = asyncio.new_event_loop().run_until_complete(
            submit_judgment(
                control_id=CONTROL,
                verdict="pass",
                reasoning="r",
                cited_evidence=[EXCERPT],
                model="m",
                model_version="v",
                owner=OWNER,
                repo=REPO,
                local_path=str(repo),
            )
        )
        assert response["status"] == "error"


@pytest.mark.integration
class TestConfirmingACandidate:
    def _confirm(self, checkout: Path, **names: str) -> str:
        from darnit.server.tools.project_data import confirm_project_data_impl

        return confirm_project_data_impl(
            local_path=str(checkout), confirm_pass_candidate=[CONTROL], framework_name=FRAMEWORK, **names
        )

    def test_operator_confirmation_gives_an_asserted_pass(self, repo: Path) -> None:
        _submit(repo)

        message = self._confirm(repo, owner=OWNER, repo=REPO)

        assert f"{CONTROL}: confirmed by" in message
        [confirmation] = load_confirmations(IDENTITY)
        assert confirmation.claim == "pass_candidate"
        result = audit(repo)
        assert result["status"] == "PASS"
        assert result["authority"] == "asserted"
        assert result["concluded_by"] == "confirmation"

    def test_nothing_to_confirm_without_a_candidate(self, repo: Path) -> None:
        message = self._confirm(repo, owner=OWNER, repo=REPO)

        assert "no PASS candidate for the current evidence" in message
        assert load_confirmations() == []

    def test_candidate_for_older_evidence_is_not_confirmed(self, repo: Path) -> None:
        _submit(repo)
        (repo / "README.md").write_text((repo / "README.md").read_text() + "\nMore.\n", encoding="utf-8")

        message = self._confirm(repo, owner=OWNER, repo=REPO)

        assert "no PASS candidate for the current evidence" in message
        assert load_confirmations() == []

    def test_repository_must_be_named(self, repo: Path) -> None:
        _submit(repo)

        assert self._confirm(repo).startswith("Error: name the repository")
        assert load_confirmations() == []


@pytest.mark.integration
class TestConfirmPassCandidateTool:
    """The framework-neutral confirmation tool, here on a non-Baseline framework."""

    def test_confirms_a_candidate_for_the_current_evidence(self, repo: Path) -> None:
        _submit(repo)

        message = asyncio.run(
            confirm_pass_candidate(
                control_ids=[CONTROL], owner=OWNER, repo=REPO, local_path=str(repo), _framework_name=FRAMEWORK
            )
        )

        assert f"{CONTROL}: confirmed by" in message
        result = audit(repo)
        assert result["status"] == "PASS"
        assert result["authority"] == "asserted"

    def test_requires_a_framework(self, repo: Path) -> None:
        _submit(repo)

        message = asyncio.run(
            confirm_pass_candidate(control_ids=[CONTROL], owner=OWNER, repo=REPO, local_path=str(repo))
        )

        assert message.startswith("Error:")
        assert load_confirmations() == []


@pytest.mark.unit
def test_every_framework_server_registers_confirm_pass_candidate() -> None:
    from darnit.server.factory import create_server_from_dict

    server = create_server_from_dict({"metadata": {"name": FRAMEWORK}, "mcp": {"name": "t"}})
    tools = {tool.name: tool for tool in asyncio.new_event_loop().run_until_complete(server.list_tools())}

    assert set(tools["confirm_pass_candidate"].inputSchema["properties"]) == {
        "control_ids",
        "owner",
        "repo",
        "host",
        "local_path",
    }


@pytest.mark.unit
def test_every_framework_server_registers_submit_judgment() -> None:
    from darnit.server.factory import create_server_from_dict

    server = create_server_from_dict({"metadata": {"name": FRAMEWORK}, "mcp": {"name": "t"}})
    tools = {tool.name: tool for tool in asyncio.new_event_loop().run_until_complete(server.list_tools())}

    assert "submit_judgment" in tools
    params = set(tools["submit_judgment"].inputSchema["properties"])
    assert params == {
        "control_id",
        "verdict",
        "reasoning",
        "cited_evidence",
        "model",
        "model_version",
        "owner",
        "repo",
        "host",
        "local_path",
    }
