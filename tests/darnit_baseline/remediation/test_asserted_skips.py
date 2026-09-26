"""Remediation follows assertion outcomes, not raw claims (feature 040, US3, T053)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

CONTROL = "OSPS-BR-07.01"


def _claimed_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".project").mkdir()
    (tmp_path / ".project" / "project.yaml").write_text("name: repo\n", encoding="utf-8")
    (tmp_path / ".project" / "darnit.yaml").write_text(
        f"controls:\n  {CONTROL}:\n    status: n/a\n    reason: not relevant\n", encoding="utf-8"
    )
    return tmp_path


def _remediate(repo: Path, cached: list[dict]) -> dict:
    from darnit_baseline.remediation import orchestrator

    applied: list[str] = []

    def fake_apply(control_id: str, **_: object) -> dict:
        applied.append(control_id)
        return {"control_id": control_id, "status": "would_apply"}

    with (
        patch("darnit.core.audit_cache.read_audit_cache", return_value={"results": cached}),
        patch.object(orchestrator, "_preflight_context_check", return_value=(True, {})),
        patch.object(orchestrator, "_apply_control_remediation", side_effect=fake_apply),
        patch.object(orchestrator, "_format_remediation_output", side_effect=lambda results, **_: results),
    ):
        results = orchestrator.remediate_audit_findings(local_path=str(repo), owner="o", repo="r", categories=["all"])
    return {"applied": applied, "results": results}


@pytest.mark.unit
@pytest.mark.parametrize("outcome", ["pending", "contradicted"])
def test_unhonored_claim_does_not_skip_remediation(tmp_path: Path, outcome: str) -> None:
    repo = _claimed_repo(tmp_path)
    cached = [{"id": CONTROL, "status": "FAIL", "assertion": {"outcome": outcome, "reason": "not relevant"}}]

    assert _remediate(repo, cached)["applied"] == [CONTROL]


@pytest.mark.unit
def test_raw_project_claim_no_longer_skips_a_control(tmp_path: Path) -> None:
    from darnit_baseline.remediation.orchestrator import _apply_control_remediation

    result = _apply_control_remediation(CONTROL, str(_claimed_repo(tmp_path)), owner="o", repo="r", dry_run=True)

    assert result["status"] != "skipped"
