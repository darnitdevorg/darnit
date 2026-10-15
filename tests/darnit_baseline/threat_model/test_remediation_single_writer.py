"""OSPS-SA-03.02 remediation goes through the single writer (framework-design 4.2).

The shipped control's ``generate_threat_model`` step returns its files as
``FileChange``s, so the executor writes them: a file with uncommitted user
changes is kept and reported ``user_changes_present``, every written file is
in the run manifest, and the commit step commits them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from darnit.config import context_storage
from darnit.core import audit_cache
from darnit.core.discovery import get_implementation
from darnit.remediation import manifest
from darnit_baseline import tools
from tests.darnit.server.conftest import _init_repo, _write, git

OWNER, REPO = "example-org", "example"
IDENTITY = f"github.com/{OWNER}/{REPO}"
CONTROL = "OSPS-SA-03.02"
DATA_FLOW = "docs/threatmodel/data-flow.md"
USER_EDIT = "# Data Flow Analysis\n\nHand-written notes, not yet committed.\n"


@pytest.fixture(autouse=True)
def baseline_handlers() -> None:
    impl = get_implementation("openssf-baseline")
    assert impl is not None
    impl.register_handlers()


@pytest.fixture(autouse=True)
def only_threat_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_cache, "read_audit_cache", lambda *_a, **_k: {"results": [{"id": CONTROL, "status": "FAIL"}]})
    monkeypatch.setattr(context_storage, "get_pending_context", lambda **_k: [])


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with a committed data-flow.md that has an uncommitted edit."""
    path = _init_repo(tmp_path / "repo")
    _write(path, {DATA_FLOW: "# Data Flow Analysis\n\nCommitted.\n"})
    git(path, "add", "--", DATA_FLOW)
    git(path, "commit", "-q", "-m", "data flow")
    _write(path, {DATA_FLOW: USER_EDIT})
    return path


def _run_block(output: str) -> dict:
    blocks = re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)
    assert blocks, output
    return json.loads(blocks[-1])


def _threat_model_changes(run: dict) -> dict[str, dict]:
    [outcome] = [o for o in run["outcomes"] if o["control_id"] == CONTROL]
    return {c["path"]: c for c in outcome["file_changes"]}


@pytest.mark.integration
def test_preview_lists_the_threat_model_files_and_writes_nothing(repo: Path) -> None:
    status = git(repo, "status", "--porcelain", "--untracked-files=all").stdout

    output = tools.remediate_audit_findings(local_path=str(repo), owner=OWNER, repo=REPO)

    [item] = [i for i in _run_block(output)["plan"] if i["control_id"] == CONTROL and i["step"].startswith("generate")]
    assert item["previewable"] is True
    changes = {c["path"]: c for c in item["file_changes"]}
    assert changes["docs/threatmodel/SUMMARY.md"]["action"] == "create"
    assert changes[DATA_FLOW] == {**changes[DATA_FLOW], "action": "none", "reason": "user_changes_present"}
    assert git(repo, "status", "--porcelain", "--untracked-files=all").stdout == status


@pytest.mark.integration
def test_apply_keeps_user_edits_records_and_commits_what_it_wrote(repo: Path) -> None:
    preview = _run_block(tools.remediate_audit_findings(local_path=str(repo), owner=OWNER, repo=REPO))
    approve = [item["digest"] for item in preview["plan"] if item["requires_individual_approval"]]

    output = tools.remediate_audit_findings(
        local_path=str(repo), owner=OWNER, repo=REPO, dry_run=False, auto_commit=True, approve=approve
    )

    run = _run_block(output)
    changes = _threat_model_changes(run)
    assert (repo / DATA_FLOW).read_text(encoding="utf-8") == USER_EDIT
    assert changes[DATA_FLOW]["action"] == "none" and changes[DATA_FLOW]["reason"] == "user_changes_present"

    written = {p for p, c in changes.items() if c["action"] != "none"}
    assert {"docs/threatmodel/SUMMARY.md", "docs/threatmodel/raw-findings.json"} <= written
    [outcome] = [o for o in run["outcomes"] if o["control_id"] == CONTROL]
    assert outcome["kind"] != "unchanged", outcome

    recorded = {f.path for f in manifest.load_run(IDENTITY, run["run_id"], checkout=repo).files}
    assert written <= recorded
    assert DATA_FLOW not in recorded

    committed = set(git(repo, "diff-tree", "-r", "--no-commit-id", "--name-only", "HEAD").stdout.split())
    assert written <= committed
    assert DATA_FLOW not in committed
    assert git(repo, "status", "--porcelain", "--", DATA_FLOW).stdout.startswith(" M")


@pytest.mark.integration
def test_generate_threat_model_tool_writes_the_multi_file_output(tmp_path: Path) -> None:
    """The MCP tool is a separate entry point that still writes the files the handler returns."""
    output = tools.generate_threat_model(local_path=str(tmp_path), output_path="docs/threatmodel/SUMMARY.md")

    assert output.startswith("Multi-file threat model written"), output
    for name in ("SUMMARY.md", "data-flow.md", "raw-findings.json"):
        assert (tmp_path / "docs" / "threatmodel" / name).is_file()
