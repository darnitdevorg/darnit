"""The OpenSSF Baseline flow a coding agent drives, end to end over MCP, with no model (#655, Phase 0.1).

An untrusted repository goes through the tools in the order the skills call
them: audit, the project-data questions until none remain, one judgment, and
a remediation preview. Each step is checked for what the next step needs, so
a change that breaks the hand-off between tools fails here even when every
tool passes its own tests.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from importlib.resources import files
from pathlib import Path

import pytest

OWNER, REPO = "acme", "widget"
JUDGED = "OSPS-DO-01.01"
EXCERPT = "Widget converts Markdown documents to HTML from the command line."
README = f"""# Widget

{EXCERPT}

## Installation

Run `pip install widget`, then `widget build docs/` to render a directory. The
command writes one HTML file per Markdown file and keeps the directory layout.
"""
# A person's answers, by key, for whatever get_pending_data asks.
ANSWERS = {
    "maintainers": ["@alice"],
    "security_contact": "security@example.com",
    "governance_model": "bdfl",
    "has_subprojects": False,
    "has_releases": False,
    "is_library": False,
    "has_compiled_assets": False,
    "ci_provider": "github",
    "license_type": "mit",
    "platform": "github",
}
MAX_ROUNDS = 5


def _operator(tmp_path: Path) -> Path:
    """An operator configuration that trusts no repository."""
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir()
    path.write_text("schema_version = 1\n\n[trust]\nrepos = []\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{OWNER}/{REPO}.git"], cwd=path, check=True)
    (path / "README.md").write_text(README, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init"],
        cwd=path,
        check=True,
    )
    return path


def _text(result) -> str:
    assert not result.isError, result.content
    return "".join(block.text for block in result.content if block.type == "text")


def _json(result) -> dict:
    """The JSON object in a tool result, after any instruction text in front of it."""
    text = _text(result)
    return json.loads(text[text.index("{") :])


async def _flow(checkout: Path, operator_config: Path) -> dict:
    from mcp.shared.memory import create_connected_server_and_client_session

    from darnit.server.factory import create_server

    server = create_server(
        Path(str(files("darnit_baseline") / "openssf-baseline.toml")), operator_config_path=operator_config
    )
    named = {"local_path": str(checkout), "owner": OWNER, "repo": REPO}
    seen: dict = {"rounds": []}
    async with create_connected_server_and_client_session(server) as session:
        audit = json.loads(_text(await session.call_tool("audit_openssf_baseline", {**named, "output_format": "json"})))
        seen["audit"] = {r["id"]: r for r in audit["results"]}

        for _ in range(MAX_ROUNDS):
            pending = _json(await session.call_tool("get_pending_data", named))
            seen["rounds"].append(pending)
            if pending["status"] != "pending":
                break
            answers = {q["key"]: ANSWERS[q["key"]] for q in pending["questions"]}
            seen.setdefault("confirmations", []).append(
                _text(await session.call_tool("confirm_project_data", {**named, **answers}))
            )

        seen["judgment"] = json.loads(
            _text(
                await session.call_tool(
                    "submit_judgment",
                    {
                        **named,
                        "control_id": JUDGED,
                        "verdict": "pass",
                        "reasoning": "The README says what the tool does and how to install and run it.",
                        "cited_evidence": [EXCERPT],
                        "model": "test",
                        "model_version": "test",
                    },
                )
            )
        )
        seen["remediation"] = _text(await session.call_tool("remediate_audit_findings", {**named, "dry_run": True}))
    return seen


@pytest.mark.integration
class TestAgentFlowOnAnUntrustedRepository:
    @pytest.fixture
    def flow(self, tmp_path: Path) -> dict:
        return asyncio.run(_flow(_repo(tmp_path), _operator(tmp_path)))

    def test_the_audit_leaves_the_judged_control_waiting_for_a_judgment(self, flow: dict) -> None:
        assert flow["audit"][JUDGED]["status"] == "PENDING"

    def test_the_questions_end_after_every_answer_is_confirmed(self, flow: dict) -> None:
        rounds = flow["rounds"]
        assert rounds[0]["status"] == "pending"
        assert rounds[-1]["status"] == "complete", rounds[-1]
        assert len(rounds) <= MAX_ROUNDS

    def test_answers_for_an_untrusted_repository_stay_out_of_the_checkout(self, flow: dict, tmp_path: Path) -> None:
        assert not (tmp_path / "repo" / ".project").exists()

    def test_the_judgment_is_checked_and_stored_as_a_candidate(self, flow: dict) -> None:
        assert flow["judgment"]["status"] == "candidate", flow["judgment"]

    def test_remediation_sees_the_confirmed_answers(self, flow: dict) -> None:
        assert "Cannot remediate yet" not in flow["remediation"], flow["remediation"]
        assert "## Would Apply" in flow["remediation"]

    def test_every_tool_used_the_operator_configuration(self, flow: dict) -> None:
        assert "built-in defaults" not in flow["remediation"]
