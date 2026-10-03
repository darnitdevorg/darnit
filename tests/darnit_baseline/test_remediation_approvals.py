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


@pytest.mark.integration
def test_an_approved_apply_previews_each_step_no_more_often_than_an_unapproved_one(
    repo: Path, simulated_gh, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Stale classification needs no extra preview pass: exec previews and platform reads run as often as without approvals."""
    import sys

    counter = tmp_path / "exec-runs.log"
    count = f"open({str(counter)!r}, 'a').write('run\\n')"
    framework = FRAMEWORK.model_copy(deep=True)
    framework.controls["OSPS-QA-99.01"] = ControlConfig(
        name="Counted",
        description="An exec step that records each run",
        level=1,
        passes=[HandlerInvocation(handler="file_exists", files=["NEVER"], existence=True)],
        remediation=RemediationConfig(
            handlers=[
                HandlerInvocation(
                    handler="exec", command=[sys.executable, "-c", count], effects="working_tree", offline=True
                )
            ]
        ),
    )
    failing = {"results": [{"id": c, "status": "FAIL"} for c in framework.controls]}
    monkeypatch.setattr(orchestrator, "_get_framework_config", lambda: framework)
    monkeypatch.setattr(audit_cache, "read_audit_cache", lambda *_a, **_k: failing)
    simulated_gh("unprotected")
    preview = _remediate(repo, dry_run=True).run
    assert preview is not None
    [unsafe_item] = [item for item in preview.plan if item.control_id == UNSAFE_CONTROL]

    def apply(approve: list[str]) -> tuple[int, int]:
        (repo / "UNSAFE.md").unlink(missing_ok=True)
        counter.unlink(missing_ok=True)
        gh = simulated_gh("unprotected")
        _remediate(repo, dry_run=False, approve=approve)
        return len(counter.read_text().splitlines()), len([c for c in gh.calls if c.method == "GET"])

    unapproved = apply([])
    approved = apply([unsafe_item.digest])

    assert approved == unapproved, (approved, unapproved)


@pytest.mark.integration
def test_approving_only_an_llm_enhancement_leaves_the_change_set_needing_approval(
    repo: Path, simulated_gh, monkeypatch: pytest.MonkeyPatch
) -> None:
    from darnit_baseline.remediation import enhancer

    monkeypatch.setattr(enhancer, "is_enhanceable", lambda _path: True)
    monkeypatch.setattr(enhancer, "get_enhancement_type", lambda _path: "architecture")
    monkeypatch.setattr(enhancer, "enhance_generated_file", lambda *_a, **_k: "# Enriched\n")
    simulated_gh("unprotected")
    preview = _remediate(repo, dry_run=True, enhance_with_llm=True).run
    assert preview is not None
    [enhancement] = [item for item in preview.plan if item.step.startswith("llm_enhance[")]
    gh = simulated_gh("unprotected")

    applied = _remediate(repo, dry_run=False, enhance_with_llm=True, approve=[enhancement.digest]).run

    assert applied is not None
    outcomes = {o.control_id: o for o in applied.outcomes}
    assert outcomes[PROTECTION_CONTROL].kind == "needs_approval", outcomes[PROTECTION_CONTROL]
    assert gh.writes == []
