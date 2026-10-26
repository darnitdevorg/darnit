"""An apply says what each changed control awaits (#681; framework-design 15.4, 15.5, 15.9).

Four controls each create a document; the re-check is stubbed to the four
states a changed document can be in after remediation.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
    RemediationConfig,
)
from darnit.core import audit_cache
from darnit.remediation.plan import RemediationRun
from darnit_baseline.remediation import orchestrator

OWNER, REPO = "example-org", "example"
RECHECK = {
    "T-JUDGE": {"status": "PENDING", "pending": {"kind": "llm_judgment"}, "details": "awaiting a model judgment"},
    "T-CAND": {"status": "PENDING", "pending": {"kind": "confirmation"}},
    "T-WARN": {"status": "WARN"},
    "T-PASS": {"status": "PASS"},
}


def _control(path: str) -> ControlConfig:
    return ControlConfig(
        name="Test",
        description=f"Test control for {path}",
        level=1,
        passes=[HandlerInvocation(handler="file_exists", files=[path], existence=True)],
        remediation=RemediationConfig(
            handlers=[HandlerInvocation(handler="file_create", path=path, content=f"# {path}\n")]
        ),
    )


FRAMEWORK = FrameworkConfig(
    metadata=FrameworkMetadata(name="openssf-baseline", display_name="Test", version="1.0"),
    controls={cid: _control(f"{cid}.md") for cid in RECHECK},
)


@pytest.fixture(autouse=True)
def synthetic_framework(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [{"id": cid, "status": "FAIL"} for cid in FRAMEWORK.controls]
    monkeypatch.setattr(orchestrator, "_get_framework_config", lambda: FRAMEWORK)
    monkeypatch.setattr(audit_cache, "read_audit_cache", lambda *_a, **_k: {"results": results})

    def recheck(ids: list[str], *_args: Any) -> dict[str, dict[str, Any]]:
        return {cid: {"id": cid, **RECHECK[cid]} for cid in ids}

    monkeypatch.setattr(orchestrator, "_recheck", recheck)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "README.md").write_text("# Example\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _apply(repo: Path) -> tuple[str, RemediationRun]:
    output = orchestrator.remediate_audit_findings(local_path=str(repo), owner=OWNER, repo=REPO, dry_run=False)
    blocks = re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)
    assert blocks, output
    return output, RemediationRun.model_validate(json.loads(blocks[-1]))


def _section(output: str, heading: str) -> str:
    start = output.index(heading)
    end = output.find("\n#", start + len(heading))
    return output[start : end if end != -1 else len(output)]


@pytest.mark.integration
class TestApplyAwaiting:
    def test_outcomes_carry_what_they_await(self, repo: Path) -> None:
        _output, run = _apply(repo)
        by_id = {o.control_id: o for o in run.outcomes}

        assert (by_id["T-JUDGE"].kind, by_id["T-JUDGE"].pending_kind) == ("changed_not_passing", "llm_judgment")
        assert (by_id["T-CAND"].kind, by_id["T-CAND"].pending_kind) == ("changed_not_passing", "confirmation")
        assert (by_id["T-WARN"].kind, by_id["T-WARN"].pending_kind) == ("changed_not_passing", None)
        assert (by_id["T-PASS"].kind, by_id["T-PASS"].pending_kind) == ("fixed", None)
        assert run.awaiting == {"confirmation": ["T-CAND"], "llm_judgment": ["T-JUDGE"]}
        assert run.summary["changed_not_passing"] == 3

    def test_the_report_says_what_each_awaits(self, repo: Path) -> None:
        output, _run = _apply(repo)

        assert "- **Awaiting:** a model judgment" in _section(output, "### T-JUDGE")
        assert "- **Awaiting:** the operator's confirmation of a PASS candidate" in _section(output, "### T-CAND")
        assert "Awaiting" not in _section(output, "### T-WARN")
        assert "Awaiting" not in _section(output, "### T-PASS")

    def test_the_report_names_the_next_steps(self, repo: Path) -> None:
        output, run = _apply(repo)

        steps = _section(output, "## Next steps")
        assert "get_judgment_requests(" in steps
        assert f'get_pass_candidates(owner="{OWNER}", repo="{REPO}"' in steps
        assert f'run_id="{run.run_id}"' in steps
        assert "T-JUDGE" in steps
        assert "T-CAND" in steps
        assert output.index("## Next steps") < output.index("```json")

    def test_awaiting_outcomes_count_as_changed_files_for_the_gates(self, repo: Path) -> None:
        _output, run = _apply(repo)

        for outcome in run.outcomes:
            if outcome.pending_kind:
                assert outcome.changed
                assert any(change.changes for change in outcome.file_changes)

    def test_nothing_awaiting_has_no_next_steps(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            orchestrator, "_recheck", lambda ids, *_a: {cid: {"id": cid, "status": "PASS"} for cid in ids}
        )

        output, run = _apply(repo)

        assert run.awaiting == {}
        assert "## Next steps" not in output


@pytest.mark.integration
def test_a_pending_recheck_without_a_kind_is_not_verified(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestrator, "_recheck", lambda ids, *_a: {cid: {"id": cid, "status": "PENDING"} for cid in ids}
    )

    _output, run = _apply(repo)

    assert {o.kind for o in run.outcomes} == {"changed_not_verified"}
    assert all(o.error is not None and o.error.error_class == "evaluation" for o in run.outcomes)
    assert run.awaiting == {}
