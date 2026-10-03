"""An approval of one control's plan item never makes another control's change set a stale preview (feature 043, 15.2).

framework-design 15.2: ``stale_preview`` means an approval was given for a
change that no longer matches. A change set with no approval while every
approval matches some other item of the run's preview is ``needs_approval``,
whichever control the approved item belongs to and in whatever order the
controls are applied.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.config import context_storage
from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
    RemediationConfig,
)
from darnit.core import audit_cache
from darnit_baseline.remediation import orchestrator
from tests.darnit.remediation.platform import conftest as platform_fixtures

simulated_gh = platform_fixtures.simulated_gh

PROTECTION_CONTROL = "OSPS-AC-03.01"
UNSAFE_CONTROL = "OSPS-AC-04.01"
FRAMEWORK = FrameworkConfig(
    metadata=FrameworkMetadata(name="openssf-baseline", display_name="Test", version="1.0"),
    controls={
        PROTECTION_CONTROL: ControlConfig(
            name="RequirePullRequest",
            description="Require a pull request",
            level=1,
            passes=[HandlerInvocation(handler="file_exists", files=["NEVER"], existence=True)],
            remediation=RemediationConfig(
                handlers=[
                    HandlerInvocation(
                        handler="platform_setting", target="branch_protection", require={"require_pull_request": True}
                    )
                ]
            ),
        ),
        UNSAFE_CONTROL: ControlConfig(
            name="Unsafe",
            description="A remediation that needs individual approval",
            level=1,
            passes=[HandlerInvocation(handler="file_exists", files=["UNSAFE.md"], existence=True)],
            remediation=RemediationConfig(
                safe=False,
                handlers=[HandlerInvocation(handler="file_create", path="UNSAFE.md", content="# Unsafe\n")],
            ),
        ),
    },
)


@pytest.fixture(autouse=True)
def synthetic_framework(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = {"results": [{"id": c, "status": "FAIL"} for c in FRAMEWORK.controls]}
    monkeypatch.setattr(orchestrator, "_get_framework_config", lambda: FRAMEWORK)
    monkeypatch.setattr(audit_cache, "read_audit_cache", lambda *_a, **_k: failing)
    monkeypatch.setattr(context_storage, "get_pending_context", lambda **_k: [])


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def _remediate(repo: Path, **kwargs) -> orchestrator.RemediationReport:
    return orchestrator.run_remediation(local_path=str(repo), owner="o", repo="r", **kwargs)


@pytest.mark.integration
def test_approving_a_later_controls_item_leaves_an_earlier_change_set_needing_approval(
    repo: Path, simulated_gh
) -> None:
    simulated_gh("unprotected")
    preview = _remediate(repo, dry_run=True).run
    assert preview is not None
    [unsafe_item] = [item for item in preview.plan if item.control_id == UNSAFE_CONTROL]
    gh = simulated_gh("unprotected")

    applied = _remediate(repo, dry_run=False, approve=[unsafe_item.digest]).run

    assert applied is not None
    outcomes = {o.control_id: o for o in applied.outcomes}
    assert outcomes[PROTECTION_CONTROL].kind == "needs_approval", outcomes[PROTECTION_CONTROL]
    assert outcomes[UNSAFE_CONTROL].kind == "fixed", outcomes[UNSAFE_CONTROL]
    assert gh.writes == []


@pytest.mark.integration
def test_an_approval_matching_nothing_in_the_run_is_a_stale_preview(repo: Path, simulated_gh) -> None:
    gh = simulated_gh("unprotected")

    applied = _remediate(repo, dry_run=False, approve=["sha256:" + "0" * 64]).run

    assert applied is not None
    [protection] = [o for o in applied.outcomes if o.control_id == PROTECTION_CONTROL]
    assert protection.kind == "unchanged" and "stale_preview" in (protection.reason or ""), protection
    assert gh.writes == []
