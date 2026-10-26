"""The get_pass_candidates MCP tool (#681; framework-design 5.4, 15.9)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from darnit.config.operator.loader import set_launch_options
from darnit.server.tools import judgments
from darnit.server.tools.judgments import get_pass_candidates, get_pass_candidates_impl, submit_judgment_impl
from tests.darnit.trust.judgment_repo import (
    CI_VARS,
    CONTROL,
    EXCERPT,
    FRAMEWORK,
    OWNER,
    README,
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


def _candidates(checkout: Path, **overrides: object) -> dict:
    args: dict = {"owner": OWNER, "repo": REPO, "local_path": str(checkout), "framework_name": FRAMEWORK}
    args.update(overrides)
    return json.loads(get_pass_candidates_impl(**args))


def _judge(checkout: Path, control_id: str = CONTROL, verdict: str = "pass", excerpt: str = EXCERPT) -> dict:
    return submit_judgment_impl(
        control_id=control_id,
        verdict=verdict,
        reasoning=f"{control_id} reasoning.",
        cited_evidence=[excerpt],
        model="m",
        model_version="v",
        owner=OWNER,
        repo=REPO,
        local_path=str(checkout),
        framework_name=FRAMEWORK,
    )


def _many_repo(tmp_path: Path, controls: int = 4, size: int = 3_000) -> Path:
    """A repository with ``controls`` judged controls, each reading its own document."""
    path = make_repo(tmp_path)
    passes = []
    for i in range(controls):
        (path / f"doc{i}.md").write_text((f"Control {i} text. " * 400)[:size], encoding="utf-8")
        passes.append(
            f'[custom_controls."MANY-{i:02d}.01"]\n'
            f'name = "Many{i}"\ndescription = "Many control {i}."\nlevel = 1\ndomain = "MANY"\n'
            "passes = [\n"
            f'  {{ handler = "llm_eval", prompt = "Judge {i}.", files_to_include = ["doc{i}.md"] }},\n'
            '  { handler = "manual", steps = ["Read it"] },\n]\n'
        )
    config = tmp_path / "operator" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("schema_version = 1\n\n" + "\n".join(passes), encoding="utf-8")
    config.chmod(0o600)
    set_launch_options(config)
    for i in range(controls):
        assert _judge(path, f"MANY-{i:02d}.01", excerpt=f"Control {i} text.")["status"] == "candidate"
    return path


def _snapshot(*roots: Path) -> dict[str, bytes]:
    return {
        str(p): p.read_bytes()
        for root in roots
        if root.exists()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


def _record_run(checkout: Path, path: str = "README.md") -> str:
    from darnit.remediation import manifest
    from darnit.remediation.plan import content_digest

    repository = manifest.repository_identity(checkout, OWNER, REPO)
    run = manifest.start_run(repository, checkout=checkout)
    manifest.record_file(
        repository, run.run_id, path, content_digest((checkout / path).read_bytes()), checkout=checkout
    )
    return run.run_id


@pytest.mark.integration
class TestGetPassCandidates:
    def test_a_stored_candidate_is_returned_with_its_passages(self, repo: Path) -> None:
        submitted = _judge(repo)

        response = _candidates(repo)

        assert response["status"] == "ok"
        assert response["awaiting_judgment"] == []
        assert response["remaining"] == []
        [entry] = response["candidates"]
        assert entry["control_id"] == CONTROL
        assert entry["title"] == "ReadmeDescribesProject"
        assert entry["description"] == "The README describes what the project is."
        assert entry["files"] == ["README.md"]
        assert entry["reasoning"] == f"{CONTROL} reasoning."
        assert entry["cited_evidence"] == [EXCERPT]
        assert (entry["model"], entry["model_version"], entry["source"]) == ("m", "v", "mcp_agent")
        assert entry["evidence_digest"] == submitted["candidate"]["evidence_digest"]
        assert "remediation" not in entry

    def test_one_question_per_candidate_with_three_answers(self, repo: Path) -> None:
        _judge(repo)

        [question] = _candidates(repo)["ask_user_batch"]

        assert question["question"] == f"Confirm the PASS candidate for {CONTROL} (README.md)?"
        assert len(question["header"]) <= 12
        assert question["multiSelect"] is False
        assert [o["label"] for o in question["options"]] == ["Confirm", "Do not confirm", "Skip for now"]
        assert EXCERPT not in json.dumps(question)

    def test_the_procedure_names_the_repository_and_holds_no_passage(self, repo: Path) -> None:
        _judge(repo)

        text = "\n".join(_candidates(repo)["procedure"])

        assert f'owner="{OWNER}", repo="{REPO}", local_path="{repo}"' in text
        assert "confirm_pass_candidate(" in text
        assert EXCERPT not in text

    def test_an_unjudged_control_awaits_a_judgment(self, repo: Path) -> None:
        response = _candidates(repo)

        assert response["candidates"] == []
        assert response["ask_user_batch"] == []
        assert response["awaiting_judgment"] == [CONTROL]

    def test_repository_must_be_named(self, repo: Path) -> None:
        response = _candidates(repo, owner="", repo="")

        assert response["status"] == "rejected"
        assert "name the audited repository" in response["rejection"]["reason"]

    def test_an_invalid_path_is_an_error(self, tmp_path: Path) -> None:
        response = _candidates(tmp_path / "missing")

        assert response["status"] == "error"

    def test_control_ids_limit_the_candidates(self, tmp_path: Path) -> None:
        checkout = _many_repo(tmp_path, controls=3)

        response = _candidates(checkout, control_ids=["MANY-01.01"])

        assert [c["control_id"] for c in response["candidates"]] == ["MANY-01.01"]

    def test_pages_stay_under_the_limit_and_cover_every_candidate_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = _many_repo(tmp_path, controls=4)
        monkeypatch.setattr(judgments, "JUDGMENT_REQUEST_PAGE_BYTES", 4_500)

        pages = [_candidates(checkout)]
        while pages[-1]["remaining"]:
            pages.append(_candidates(checkout, control_ids=pages[-1]["remaining"]))
            assert len(pages) < 10

        assert len(pages) > 1
        for page in pages:
            size = len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            assert size <= judgments.JUDGMENT_REQUEST_PAGE_BYTES
            assert len(page["ask_user_batch"]) == len(page["candidates"])
        ids = [c["control_id"] for page in pages for c in page["candidates"]]
        assert ids == [f"MANY-{i:02d}.01" for i in range(4)]

    def test_records_nothing(self, repo: Path) -> None:
        from darnit.trust import confirmations

        _judge(repo)
        before = _snapshot(confirmations.user_data_root(), repo)

        _candidates(repo)

        assert _snapshot(confirmations.user_data_root(), repo) == before

    def test_async_tool_requires_a_framework(self, repo: Path) -> None:
        response = json.loads(asyncio.run(get_pass_candidates(owner=OWNER, repo=REPO, local_path=str(repo))))

        assert response["status"] == "error"


@pytest.mark.integration
class TestDocumentsRemediationWrote:
    def test_a_file_the_run_wrote_is_marked(self, repo: Path) -> None:
        run_id = _record_run(repo)
        _judge(repo)

        [entry] = _candidates(repo, run_id=run_id)["candidates"]

        assert entry["remediation"] == {
            "run_id": run_id,
            "path": "README.md",
            "written": True,
            "edited_after_write": False,
        }

    def test_an_edit_after_the_write_is_marked(self, repo: Path) -> None:
        run_id = _record_run(repo)
        (repo / "README.md").write_text(README + "\nEdited after remediation.\n", encoding="utf-8")
        _judge(repo)

        [entry] = _candidates(repo, run_id=run_id)["candidates"]

        assert entry["remediation"]["edited_after_write"] is True

    def test_an_unknown_run_adds_a_note(self, repo: Path) -> None:
        _judge(repo)

        response = _candidates(repo, run_id="01JAAAAAAAAAAAAAAAAAAAAAAA")

        assert response["status"] == "ok"
        assert "remediation" not in response["candidates"][0]
        assert "01JAAAAAAAAAAAAAAAAAAAAAAA" in response["note"]


@pytest.mark.integration
class TestFirstRoundCandidates:
    def test_a_stale_candidate_is_not_offered(self, repo: Path) -> None:
        _judge(repo)
        (repo / "README.md").write_text(README + "\nChanged after the judgment.\n", encoding="utf-8")

        response = _candidates(repo)

        assert response["candidates"] == []
        assert response["awaiting_judgment"] == [CONTROL]

    def test_a_finding_is_not_a_candidate_and_stores_nothing(self, repo: Path) -> None:
        from darnit.trust import confirmations

        before = _snapshot(confirmations.user_data_root())
        assert _judge(repo, verdict="fail")["status"] == "finding"

        response = _candidates(repo)

        assert response["candidates"] == []
        assert response["awaiting_judgment"] == [CONTROL]
        assert _snapshot(confirmations.user_data_root()) == before

    def test_a_confirmed_candidate_passes(self, repo: Path) -> None:
        from darnit.server.tools.project_data import confirm_pass_candidates_impl

        _judge(repo)
        [entry] = _candidates(repo)["candidates"]

        message = confirm_pass_candidates_impl(
            str(repo), [entry["control_id"]], owner=OWNER, repo=REPO, framework_name=FRAMEWORK
        )

        assert f"{CONTROL}: confirmed by" in message
        result = audit(repo)
        assert result["status"] == "PASS"
        assert result["concluded_by"] == "confirmation"
        assert _candidates(repo)["candidates"] == []


def _framework_server(tmp_path: Path):
    """A server for ``FRAMEWORK`` whose own TOML declares no MCP tools."""
    from darnit.server.factory import create_server

    config = tmp_path / "framework.toml"
    config.write_text(f'[metadata]\nname = "{FRAMEWORK}"\n\n[mcp]\nname = "t"\n', encoding="utf-8")
    return create_server(config)


@pytest.mark.unit
def test_every_framework_server_registers_get_pass_candidates(tmp_path: Path) -> None:
    server = _framework_server(tmp_path)
    tools = {tool.name: tool for tool in asyncio.new_event_loop().run_until_complete(server.list_tools())}

    tool = tools["get_pass_candidates"]
    assert set(tool.inputSchema["properties"]) == {"owner", "repo", "host", "local_path", "control_ids", "run_id"}
    assert tool.outputSchema is None
