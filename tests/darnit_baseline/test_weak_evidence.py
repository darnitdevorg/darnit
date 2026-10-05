"""Weak evidence cannot produce a PASS (feature 041 US1, spec Independent Test).

Audits scratch repositories with placeholder documents through the OpenSSF
Baseline framework. Before feature 041 every content control below concluded
PASS from a presence or keyword step.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.tools.audit import run_checks

CONTENT_CONTROLS = (
    "OSPS-DO-01.01",
    "OSPS-VM-01.01",
    "OSPS-VM-02.01",
    "OSPS-GV-01.01",
    "OSPS-GV-01.02",
    "OSPS-GV-03.01",
    "OSPS-LE-01.01",
    "OSPS-AC-04.01",
    "OSPS-QA-06.01",
    "STAGE1-REF-SECURITY-01",
)

PLACEHOLDERS = {
    "README.md": "TODO\n",
    "SECURITY.md": (
        "# Security\n\nThis project has no security policy. There is no process to report a "
        "vulnerability and no security contact. Do not report vulnerabilities.\n"
    ),
    "GOVERNANCE.md": "TODO: governance\n",
    "CONTRIBUTING.md": "TODO\n",
    "MAINTAINERS.md": "TODO\n",
    "CODEOWNERS": "# TODO\n",
    "LICENSE": "TODO\n",
    ".github/workflows/ci.yml": (
        "name: ci\non: [push]\npermissions: write-all\njobs:\n  test:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    ),
}


@pytest.fixture()
def offline_gh(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    shim = tmp_path_factory.mktemp("bin")
    gh = shim / "gh"
    gh.write_text("#!/bin/sh\necho 'gh unavailable (test)' >&2\nexit 1\n", encoding="utf-8")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}:{Path('/usr/bin')}:{Path('/bin')}")
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _audit(repo: Path) -> dict[str, dict]:
    results, _skipped = run_checks(
        owner="corpus",
        repo="placeholder",
        local_path=str(repo),
        default_branch="main",
        level=3,
        stop_on_llm=True,
        evaluate_claims=False,
        framework_name="openssf-baseline",
    )
    return {r["id"]: r for r in results}


def test_placeholder_documents_do_not_pass(tmp_path: Path, offline_gh: None) -> None:
    for rel, content in PLACEHOLDERS.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    by_id = _audit(tmp_path)

    passed = {cid: by_id[cid].get("concluded_by") for cid in CONTENT_CONTROLS if by_id[cid]["status"] == "PASS"}
    assert not passed, f"content controls concluded PASS on placeholder documents: {passed}"


def test_missing_documents_still_fail(tmp_path: Path, offline_gh: None) -> None:
    by_id = _audit(tmp_path)

    for cid in ("OSPS-DO-01.01", "OSPS-VM-02.01", "OSPS-GV-01.01", "OSPS-GV-03.01"):
        assert by_id[cid]["status"] == "FAIL", (cid, by_id[cid]["status"], by_id[cid]["details"])
        assert by_id[cid]["concluded_by"] == "file_exists"
