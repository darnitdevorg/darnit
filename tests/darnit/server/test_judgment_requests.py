"""The get_judgment_requests MCP tool (#644; framework-design 5.4)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from darnit.config.operator.loader import set_launch_options
from darnit.server.tools import judgments
from darnit.server.tools.judgments import get_judgment_requests, get_judgment_requests_impl, submit_judgment_impl
from tests.darnit.trust.judgment_repo import (
    CI_VARS,
    CONTROL,
    EXCERPT,
    FRAMEWORK,
    OWNER,
    REPO,
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


def _requests(checkout: Path, **overrides: object) -> dict:
    args: dict = {"owner": OWNER, "repo": REPO, "local_path": str(checkout), "framework_name": FRAMEWORK}
    args.update(overrides)
    return json.loads(get_judgment_requests_impl(**args))


def _all_pages(checkout: Path, **overrides: object) -> list[dict]:
    pages = [_requests(checkout, **overrides)]
    while pages[-1]["remaining"]:
        pages.append(_requests(checkout, control_ids=pages[-1]["remaining"], **overrides))
        assert len(pages) < 50
    return pages


def _big_repo(tmp_path: Path, controls: int = 8, size: int = 12_000) -> Path:
    """A repository with ``controls`` judged controls, each reading two files of ``size`` characters and a shared README."""
    path = make_repo(tmp_path)
    passes = []
    for i in range(controls):
        for side in ("a", "b"):
            (path / f"doc{i}{side}.md").write_text((f"Control {i}{side} text. " * 800)[:size], encoding="utf-8")
        passes.append(
            f'[custom_controls."BIG-{i:02d}.01"]\n'
            f'name = "Big{i}"\ndescription = "Big control {i}."\nlevel = 1\ndomain = "BIG"\n'
            "passes = [\n"
            f'  {{ handler = "llm_eval", prompt = "Judge {i}.", '
            f'files_to_include = ["README.md", "doc{i}a.md", "doc{i}b.md"] }},\n'
            '  { handler = "manual", steps = ["Read it"] },\n]\n'
        )
    config = tmp_path / "operator" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("schema_version = 1\n\n" + "\n".join(passes), encoding="utf-8")
    config.chmod(0o600)
    set_launch_options(config)
    return path


@pytest.mark.integration
class TestGetJudgmentRequests:
    def test_request_carries_prompt_hints_and_the_judged_files(self, repo: Path) -> None:
        response = _requests(repo)

        assert response["status"] == "ok"
        assert response["remaining"] == []
        [request] = response["requests"]
        assert request["control_id"] == CONTROL
        assert request["kind"] == "llm_judgment"
        assert request["prompt"] == "Does the README describe what the project is?"
        assert request["analysis_hints"] == ["Look for a purpose statement"]
        assert request["evidence_digest"].startswith("sha256:")
        assert request["files"] == ["README.md"]
        assert response["files"]["README.md"]["path"] == "README.md"
        assert "gathered_evidence" not in json.dumps(response)

    def test_files_hold_exactly_what_submit_judgment_checks(self, repo: Path) -> None:
        from darnit.config.operator.loader import resolve_operator_config
        from darnit.tools.audit import judgment_consultations
        from darnit.trust.judgments import judged_content

        response = _requests(repo)
        consultation = judgment_consultations(
            str(repo), [CONTROL], FRAMEWORK, resolve_operator_config(str(repo)), OWNER, REPO, None
        )[CONTROL]

        assert {k: v["content"] for k, v in response["files"].items()} == judged_content(consultation)

    def test_a_citation_copied_from_the_files_map_is_accepted(self, repo: Path) -> None:
        response = _requests(repo)
        content = response["files"][response["requests"][0]["files"][0]]["content"]
        excerpt = content[content.index(EXCERPT) : content.index(EXCERPT) + len(EXCERPT)]

        submitted = submit_judgment_impl(
            control_id=CONTROL,
            verdict="pass",
            reasoning="The README states what the project is.",
            cited_evidence=[excerpt],
            model="m",
            model_version="v",
            owner=OWNER,
            repo=REPO,
            local_path=str(repo),
            framework_name=FRAMEWORK,
        )

        assert submitted["status"] == "candidate"
        assert submitted["candidate"]["evidence_digest"] == response["requests"][0]["evidence_digest"]

    def test_a_stored_candidate_is_left_out_unless_asked_for(self, repo: Path) -> None:
        submit_judgment_impl(
            control_id=CONTROL,
            verdict="pass",
            reasoning="r",
            cited_evidence=[EXCERPT],
            model="m",
            model_version="v",
            owner=OWNER,
            repo=REPO,
            local_path=str(repo),
            framework_name=FRAMEWORK,
        )

        assert _requests(repo)["requests"] == []
        [request] = _requests(repo, include_judged=True)["requests"]
        assert request["control_id"] == CONTROL
        assert request["kind"] == "confirmation"

    def test_repository_must_be_named(self, repo: Path) -> None:
        response = _requests(repo, owner="", repo="")

        assert response["status"] == "rejected"
        assert "name the audited repository" in response["rejection"]["reason"]

    def test_control_ids_limit_the_requests(self, tmp_path: Path) -> None:
        checkout = _big_repo(tmp_path, controls=3)

        response = _requests(checkout, control_ids=["BIG-01.01"])

        assert [r["control_id"] for r in response["requests"]] == ["BIG-01.01"]

    def test_pages_stay_under_the_limit_and_cover_every_request_once(self, tmp_path: Path) -> None:
        checkout = _big_repo(tmp_path)

        pages = _all_pages(checkout)

        assert len(pages) > 1
        for page in pages:
            assert (
                len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                <= judgments.JUDGMENT_REQUEST_PAGE_BYTES
            )
            assert "oversized" not in page
            referenced = {key for request in page["requests"] for key in request["files"]}
            assert referenced == set(page["files"])
        ids = [request["control_id"] for page in pages for request in page["requests"]]
        assert ids == [f"BIG-{i:02d}.01" for i in range(8)]

    def test_a_file_read_by_several_controls_appears_once_per_page(self, tmp_path: Path) -> None:
        checkout = _big_repo(tmp_path, controls=2, size=2_000)

        [page] = _all_pages(checkout)

        assert [key for key in page["files"] if page["files"][key]["path"] == "README.md"] == ["README.md"]
        assert all("README.md" in request["files"] for request in page["requests"])

    def test_a_request_larger_than_a_page_is_returned_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = _big_repo(tmp_path, controls=3)
        monkeypatch.setattr(judgments, "JUDGMENT_REQUEST_PAGE_BYTES", 5_000)

        pages = _all_pages(checkout)

        assert [len(page["requests"]) for page in pages] == [1, 1, 1]
        assert all(page["oversized"] is True for page in pages)
        assert "alone exceeds" in pages[0]["note"]

    def test_async_tool_requires_a_framework(self, repo: Path) -> None:
        response = json.loads(asyncio.run(get_judgment_requests(owner=OWNER, repo=REPO, local_path=str(repo))))

        assert response["status"] == "error"


@pytest.mark.unit
def test_every_framework_server_registers_get_judgment_requests() -> None:
    from darnit.server.factory import create_server_from_dict

    server = create_server_from_dict({"metadata": {"name": FRAMEWORK}, "mcp": {"name": "t"}})
    tools = {tool.name: tool for tool in asyncio.new_event_loop().run_until_complete(server.list_tools())}

    assert set(tools["get_judgment_requests"].inputSchema["properties"]) == {
        "owner",
        "repo",
        "host",
        "local_path",
        "control_ids",
        "include_judged",
    }


@pytest.mark.unit
def test_get_judgment_requests_returns_its_text_without_a_structured_copy() -> None:
    from darnit.server.factory import create_server_from_dict

    server = create_server_from_dict({"metadata": {"name": FRAMEWORK}, "mcp": {"name": "t"}})
    tools = {tool.name: tool for tool in asyncio.new_event_loop().run_until_complete(server.list_tools())}

    assert tools["get_judgment_requests"].outputSchema is None


@pytest.mark.integration
def test_every_page_carries_the_judgment_procedure(tmp_path: Path) -> None:
    checkout = _big_repo(tmp_path)

    pages = _all_pages(checkout)

    assert len(pages) > 1
    for page in pages:
        text = "\n".join(page["procedure"])
        assert "submit_judgment(" in text
        assert f'owner="{OWNER}", repo="{REPO}", local_path="{checkout}"' in text
        assert "get_judgment_requests(" in text
