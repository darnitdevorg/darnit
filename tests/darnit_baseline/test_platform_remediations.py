"""Baseline platform remediations declare requirements, not payloads (feature 043 T027; R1, R2)."""

from __future__ import annotations

from importlib import resources

import pytest

from darnit_baseline.remediation.orchestrator import _get_framework_config

PLATFORM_FIXES = {
    "OSPS-AC-03.01": ("branch_protection", {"require_pull_request": True}),
    "OSPS-AC-03.02": ("branch_protection", {"prevent_deletion": True}),
    "OSPS-QA-07.01": ("branch_protection", {"require_approvals": 1}),
    "OSPS-QA-01.01": ("repository", {"visibility": "public"}),
    "OSPS-VM-03.01": ("vulnerability_reporting", {"enabled": True}),
}
PAYLOAD_TEMPLATES = (
    "allow_forking_payload",
    "branch_deletion_protection_payload",
    "branch_protection_payload",
    "mfa_enforcement_payload",
    "pr_review_payload",
    "repo_visibility_payload",
    "vulnerability_reporting_payload",
)


@pytest.fixture(scope="module")
def framework():
    return _get_framework_config()


@pytest.mark.unit
@pytest.mark.parametrize("control_id", sorted(PLATFORM_FIXES))
def test_platform_fix_is_a_platform_setting_requirement(framework, control_id: str) -> None:
    target, require = PLATFORM_FIXES[control_id]
    handlers = framework.controls[control_id].remediation.handlers

    settings = [h for h in handlers if h.handler == "platform_setting"]

    assert len(settings) == 1
    extra = settings[0].model_extra
    assert extra["target"] == target
    assert extra["require"] == require
    assert "branch" not in extra, "FR-007: the default branch comes from the platform"


@pytest.mark.unit
def test_no_remediation_uses_api_call_or_payloads(framework) -> None:
    for control_id, control in framework.controls.items():
        for handler in control.remediation.handlers if control.remediation else []:
            assert handler.handler != "api_call", control_id
            assert "payload_template" not in (handler.model_extra or {}), control_id


@pytest.mark.unit
def test_payload_templates_are_gone(framework) -> None:
    files = resources.files("darnit_baseline") / "templates"
    for name in PAYLOAD_TEMPLATES:
        assert name not in framework.templates
        assert not (files / f"{name}.tmpl").is_file()


@pytest.mark.unit
def test_org_two_factor_is_manual_only_and_states_its_impact(framework) -> None:
    handlers = framework.controls["OSPS-AC-01.01"].remediation.handlers

    assert [h.handler for h in handlers] == ["manual"]
    steps = " ".join(handlers[0].model_extra["steps"]).lower()
    assert "removed" in steps and "collaborators" in steps and "bot" in steps


@pytest.mark.unit
def test_allow_forking_remediation_is_removed(framework) -> None:
    assert framework.controls["OSPS-AC-02.01"].remediation is None
