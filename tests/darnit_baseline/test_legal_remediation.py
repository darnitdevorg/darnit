"""Legal remediations never replace an existing license (feature 043, T055c).

OSPS-LE-01.01 requires contributor sign-off (DCO or CLA, #508), not a license
file; its former remediation replaced an existing LICENSE with MIT. Per the
spec assumption on remediations that change something unrelated, it is
manual-only. A LICENSE is created only by a control that requires a license
file, never over an existing file, and only for a confirmed ``license_type``
(Principle IV: no default license).
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from darnit.config import load_framework_config
from darnit.core import audit_cache
from darnit.remediation.executor import RemediationExecutor
from darnit_baseline import get_framework_path
from darnit_baseline.remediation import orchestrator

OWNER, REPO = "o", "r"
BASELINE_PATH = get_framework_path()
BASELINE = tomllib.loads(BASELINE_PATH.read_text(encoding="utf-8"))
LEGAL = sorted(cid for cid, c in BASELINE["controls"].items() if cid.startswith("OSPS-LE-") and c.get("remediation"))
LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING")
EXISTING_LICENSE = b"GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\r\n\nCopyright (C) 2026 Someone\n"
LICENSE_TYPES = [None, "mit", "apache-2.0", "bsd-3-clause", "other"]


def _handlers(control_id: str) -> list[dict]:
    return BASELINE["controls"][control_id]["remediation"]["handlers"]


def _license_creates() -> list[tuple[str, dict]]:
    return [
        (cid, h)
        for cid in LEGAL
        for h in _handlers(cid)
        if h["handler"] == "file_create" and h["path"] in LICENSE_FILES
    ]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    (path / "LICENSE").write_bytes(EXISTING_LICENSE)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "--no-gpg-sign", "-m", "fixture"], cwd=path, check=True)
    return path


@pytest.mark.unit
def test_legal_controls_are_found() -> None:
    assert {"OSPS-LE-01.01", "OSPS-LE-02.01", "OSPS-LE-03.01"} <= set(LEGAL)


@pytest.mark.unit
def test_le_01_01_is_manual_with_contributor_sign_off_steps() -> None:
    handlers = _handlers("OSPS-LE-01.01")

    assert [h["handler"] for h in handlers] == ["manual"]
    steps = " ".join(handlers[0]["steps"])
    for term in ("DCO", "CLA", "Signed-off-by", "CONTRIBUTING.md"):
        assert term in steps


@pytest.mark.unit
def test_only_controls_that_require_a_license_file_create_one() -> None:
    assert {cid for cid, _ in _license_creates()} == {"OSPS-LE-02.01", "OSPS-LE-03.01"}


@pytest.mark.unit
def test_no_legal_remediation_overwrites_a_file() -> None:
    for control_id in LEGAL:
        for handler in _handlers(control_id):
            assert handler.get("overwrite", False) is False, f"{control_id}: {handler}"


@pytest.mark.unit
def test_license_choice_comes_only_from_a_license_type() -> None:
    for control_id, handler in _license_creates():
        assert set(handler.get("when", {})) == {"license_type"}, f"{control_id}: {handler['template']} is a default"


@pytest.mark.unit
def test_license_type_is_a_user_judgment_key() -> None:
    definition = BASELINE["context"]["license_type"]

    assert definition["auto_detect"] is False
    assert {h["when"]["license_type"] for _, h in _license_creates()} <= set(definition["values"])


@pytest.mark.unit
@pytest.mark.parametrize("license_type", LICENSE_TYPES)
@pytest.mark.parametrize("control_id", LEGAL)
def test_existing_license_is_byte_identical_after_preview_and_apply(
    repo: Path, control_id: str, license_type: str | None
) -> None:
    framework = load_framework_config(BASELINE_PATH)
    remediation = framework.controls[control_id].remediation
    assert remediation is not None

    def executor(approvals: list[str]) -> RemediationExecutor:
        return RemediationExecutor(
            local_path=str(repo),
            owner=OWNER,
            repo=REPO,
            templates=framework.templates,
            framework_path=str(BASELINE_PATH),
            context_values={"license_type": license_type} if license_type else {},
            unconfirmed_keys=() if license_type else ("license_type",),
            approvals=approvals,
        )

    preview = executor([]).execute(control_id, remediation, dry_run=True)
    assert (repo / "LICENSE").read_bytes() == EXISTING_LICENSE
    assert not [c for c in preview.file_changes if c.path in LICENSE_FILES and c.changes]

    executor([item.digest for item in preview.plan]).execute(control_id, remediation, dry_run=False)
    assert (repo / "LICENSE").read_bytes() == EXISTING_LICENSE


def _remediate_all_legal(repo: Path, monkeypatch: pytest.MonkeyPatch, *, dry_run: bool, approve=None) -> dict:
    monkeypatch.setattr(
        audit_cache,
        "read_audit_cache",
        lambda *_a, **_k: {"results": [{"id": cid, "status": "FAIL"} for cid in LEGAL]},
    )
    monkeypatch.setattr(orchestrator, "_recheck", lambda *_a, **_k: {})
    output = orchestrator.remediate_audit_findings(
        local_path=str(repo), owner=OWNER, repo=REPO, dry_run=dry_run, approve=approve
    )
    return json.loads(re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)[-1])


@pytest.mark.integration
def test_remediating_every_legal_control_leaves_an_existing_license_unchanged(repo: Path, monkeypatch) -> None:
    preview = _remediate_all_legal(repo, monkeypatch, dry_run=True)
    assert (repo / "LICENSE").read_bytes() == EXISTING_LICENSE

    approve = [item["digest"] for item in preview.get("plan", [])]
    _remediate_all_legal(repo, monkeypatch, dry_run=False, approve=approve)
    assert (repo / "LICENSE").read_bytes() == EXISTING_LICENSE


@pytest.mark.integration
def test_no_license_is_created_without_a_confirmed_license_type(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "bare"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)

    run = _remediate_all_legal(path, monkeypatch, dry_run=False)

    assert not any((path / name).exists() for name in LICENSE_FILES)
    kinds = {o["control_id"]: o["kind"] for o in run["outcomes"]}
    assert kinds["OSPS-LE-03.01"] == "needs_confirmation"
    assert kinds["OSPS-LE-01.01"] == "manual"
