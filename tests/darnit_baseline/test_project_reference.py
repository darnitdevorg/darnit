"""Remediation never rewrites unrelated project references (feature 043, US3, SC-006, quickstart V4).

framework-design.md 4.3: a reference is recorded only from a
``project_reference`` declared on the ``file_create`` step that creates the
file, only for a file created in this run, and only into an empty field.
The remediations below are the Baseline TOML's own steps, with inline
content in place of templates that read context values.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
    RemediationConfig,
)
from darnit.core import audit_cache
from darnit.core.utils import set_gh_api_responder
from darnit.remediation import manifest
from darnit_baseline import config as baseline_config
from darnit_baseline import get_framework_path
from darnit_baseline.config.mappings import DEFAULT_FILE_LOCATIONS
from darnit_baseline.remediation import orchestrator
from tests.darnit.remediation.platform.conftest import PLATFORM_FIXTURES, SimulatedGitHub

OWNER, REPO = "o", "r"
IDENTITY = f"github.com/{OWNER}/{REPO}"
BASELINE = tomllib.loads(get_framework_path().read_text(encoding="utf-8"))
EXPECTED_REFERENCES = {
    "OSPS-VM-02.01": "security.policy",
    "OSPS-GV-03.01": "governance.contributing",
    "OSPS-GV-03.02": "governance.contributing",
    "OSPS-GV-04.01": "governance.codeowners",
    "OSPS-DO-03.01": "documentation.support",
    "OSPS-DO-01.01": "documentation.readme",
    "OSPS-GV-01.01": "governance.governance_doc",
    "OSPS-GV-01.02": "governance.maintainers",
    "OSPS-LE-01.01": "legal.license",
}


def _file_creates() -> list[tuple[str, dict]]:
    return [
        (cid, handler)
        for cid, control in BASELINE["controls"].items()
        for handler in (control.get("remediation") or {}).get("handlers", [])
        if handler["handler"] == "file_create"
    ]


def _baseline_step(control_id: str) -> HandlerInvocation:
    [step] = [h for cid, h in _file_creates() if cid == control_id and "when" not in h]
    fields = {k: v for k, v in step.items() if k not in ("template", "llm_enhance")}
    return HandlerInvocation(**fields, content=f"# {step['path']}\n")


def _framework(*control_ids: str) -> FrameworkConfig:
    return FrameworkConfig(
        metadata=FrameworkMetadata(name="openssf-baseline", display_name="Test", version="1.0"),
        controls={
            cid: ControlConfig(
                name=cid,
                description=cid,
                level=1,
                passes=[],
                remediation=RemediationConfig(handlers=[_baseline_step(cid)]),
            )
            for cid in control_ids
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    return path


def _commit(repo: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)


def _apply(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    control_id: str,
    framework: FrameworkConfig | None,
    approve: list[str] | None = None,
) -> dict:
    if framework is not None:
        monkeypatch.setattr(orchestrator, "_get_framework_config", lambda: framework)
    monkeypatch.setattr(
        audit_cache, "read_audit_cache", lambda *_a, **_k: {"results": [{"id": control_id, "status": "FAIL"}]}
    )
    monkeypatch.setattr(orchestrator, "_recheck", lambda *_a, **_k: {})
    output = orchestrator.remediate_audit_findings(
        local_path=str(repo), owner=OWNER, repo=REPO, dry_run=False, approve=approve
    )
    [outcome] = json.loads(re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)[-1])["outcomes"]
    return outcome


POLICY_SET = "name: repo\nsecurity:\n  policy:\n    path: SECURITY.md\n"


@pytest.mark.integration
def test_bug_report_template_leaves_the_security_policy_unchanged(repo: Path, monkeypatch) -> None:
    """The reproduction for #482: DO-02.01 once recorded its bug template as the security policy."""
    _commit(repo, {"SECURITY.md": "# Security\n", ".project/project.yaml": POLICY_SET})

    outcome = _apply(repo, monkeypatch, "OSPS-DO-02.01", _framework("OSPS-DO-02.01"))

    assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == POLICY_SET
    assert not (repo / ".project" / "darnit.yaml").exists()
    assert [c["path"] for c in outcome["file_changes"]] == [".github/ISSUE_TEMPLATE/bug_report.md"]
    assert all(c["project_reference"] is None for c in outcome["file_changes"])


@pytest.mark.integration
def test_a_different_existing_reference_is_kept_and_the_outcome_says_why(repo: Path, monkeypatch) -> None:
    project = "name: repo\nsecurity:\n  policy:\n    path: docs/SECURITY.md\n"
    _commit(repo, {".project/project.yaml": project})

    outcome = _apply(repo, monkeypatch, "OSPS-VM-02.01", _framework("OSPS-VM-02.01"))

    assert (repo / "SECURITY.md").exists()
    assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == project
    assert [c["path"] for c in outcome["file_changes"]] == ["SECURITY.md"]
    assert "SECURITY.md is not recorded as security.policy" in outcome["reason"]
    assert "already names docs/SECURITY.md" in outcome["reason"]


@pytest.mark.integration
def test_a_created_file_is_recorded_into_an_empty_field(repo: Path, monkeypatch) -> None:
    _commit(repo, {".project/project.yaml": "name: repo\n"})

    outcome = _apply(repo, monkeypatch, "OSPS-VM-02.01", _framework("OSPS-VM-02.01"))

    assert (repo / ".project" / "project.yaml").read_text(encoding="utf-8") == POLICY_SET
    assert [c["path"] for c in outcome["file_changes"]] == ["SECURITY.md", ".project/project.yaml"]
    run = manifest.load_run(IDENTITY, checkout=repo)
    assert run is not None
    assert sorted(f.path for f in run.files) == [".project/project.yaml", "SECURITY.md"]


@pytest.mark.integration
def test_a_skipped_existing_file_records_nothing(repo: Path, monkeypatch) -> None:
    _commit(repo, {"SECURITY.md": "# Security\n"})

    outcome = _apply(repo, monkeypatch, "OSPS-VM-02.01", _framework("OSPS-VM-02.01"))

    assert outcome["kind"] == "unchanged"
    assert not (repo / ".project").exists()


@pytest.mark.integration
def test_a_platform_only_remediation_records_nothing(repo: Path, monkeypatch) -> None:
    _commit(repo, {})
    previous = set_gh_api_responder(SimulatedGitHub(PLATFORM_FIXTURES["stricter"]()))
    try:
        monkeypatch.setattr(
            audit_cache, "read_audit_cache", lambda *_a, **_k: {"results": [{"id": "OSPS-AC-03.02", "status": "FAIL"}]}
        )
        preview = orchestrator.remediate_audit_findings(local_path=str(repo), owner=OWNER, repo=REPO)
        run = json.loads(re.findall(r"```json\n(.*?)\n```", preview, re.DOTALL)[-1])
        [digest] = {cs["digest"] for item in run["plan"] for cs in item["change_sets"]}
        set_gh_api_responder(SimulatedGitHub(PLATFORM_FIXTURES["stricter"]()))

        outcome = _apply(repo, monkeypatch, "OSPS-AC-03.02", None, approve=[digest])
    finally:
        set_gh_api_responder(previous)

    assert [cs["digest"] for cs in outcome["change_sets"]] == [digest], "the platform change was applied"
    assert outcome["file_changes"] == []
    assert not (repo / ".project").exists()


@pytest.mark.unit
def test_every_declared_reference_matches_the_fields_file_locations() -> None:
    declared = [(cid, h["path"], h["project_reference"]) for cid, h in _file_creates() if "project_reference" in h]

    assert declared
    for control_id, path, reference in declared:
        patterns = DEFAULT_FILE_LOCATIONS.get(reference)
        assert patterns, f"{control_id}: {reference} has no known file locations"
        assert any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns), (
            f"{control_id}: {path} is not a {reference} file ({patterns})"
        )


@pytest.mark.unit
def test_the_documented_steps_declare_their_reference() -> None:
    declared = {cid: h.get("project_reference") for cid, h in _file_creates() if "when" not in h}

    assert {cid: declared[cid] for cid in EXPECTED_REFERENCES} == EXPECTED_REFERENCES
    assert declared["OSPS-DO-02.01"] is None, "a bug report template is no project reference"


@pytest.mark.unit
def test_no_control_to_field_table_remains() -> None:
    assert not hasattr(baseline_config, "CONTROL_REFERENCE_MAPPING")
    assert not hasattr(orchestrator, "CONTROL_REFERENCE_MAPPING")
    for control_id in ("OSPS-DO-01.01", "OSPS-LE-01.01"):
        assert "project_update" not in BASELINE["controls"][control_id]["remediation"], (
            f"{control_id} records its reference through project_reference, not an unconditional project_update"
        )
