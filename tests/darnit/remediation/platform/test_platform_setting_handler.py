"""The ``platform_setting`` remediation handler and schema; ``api_call`` removed (feature 043 T025, T026)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from darnit.config.framework_schema import FrameworkConfig, HandlerInvocation, RemediationConfig
from darnit.config.operator.schema import RemediationSettings
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationExecutor
from darnit.remediation.platform import PlatformRequirement, PlatformSession, ResolvedPolicy
from darnit.sieve.builtin_handlers import register_builtin_handlers
from darnit.sieve.handler_registry import HandlerContext, get_sieve_handler_registry
from tests.conftest_helpers import assert_unchanged, snapshot

OWNER, REPO = "o", "r"
REPOSITORY = "github.com/o/r"


def _framework(*handlers: dict) -> dict:
    return {
        "metadata": {"name": "t", "display_name": "T", "version": "1"},
        "controls": {"T-01": {"name": "T", "description": "t", "remediation": {"handlers": list(handlers)}}},
    }


def _platform_setting(**fields) -> HandlerInvocation:
    return HandlerInvocation(handler="platform_setting", **fields)


AC_03_02 = _platform_setting(target="branch_protection", require={"prevent_deletion": True})
PUBLIC = _platform_setting(target="repository", require={"visibility": "public"})


def _policy(platform: str = "prompt", high_impact: str = "prompt") -> ResolvedPolicy:
    return ResolvedPolicy(
        settings=RemediationSettings(platform=platform, high_impact=high_impact),
        operator_config_digest=None,
        operator="alice",
    )


@pytest.mark.unit
class TestSchema:
    def test_api_call_fails_validation_naming_platform_setting(self) -> None:
        with pytest.raises(ValidationError) as exc:
            FrameworkConfig.model_validate(_framework({"handler": "api_call", "endpoint": "/x"}))

        assert "platform_setting" in str(exc.value)
        assert "T-01" in str(exc.value)

    def test_legacy_api_call_table_fails_validation_naming_platform_setting(self) -> None:
        framework = _framework()
        framework["controls"]["T-01"]["remediation"] = {"api_call": {"method": "PUT", "endpoint": "/x"}}

        with pytest.raises(ValidationError) as exc:
            FrameworkConfig.model_validate(framework)

        assert "platform_setting" in str(exc.value)

    def test_platform_setting_validates(self) -> None:
        config = FrameworkConfig.model_validate(
            _framework(
                {"handler": "platform_setting", "target": "branch_protection", "require": {"require_approvals": 1}}
            )
        )

        assert config.controls["T-01"].remediation.handlers[0].handler == "platform_setting"

    @pytest.mark.parametrize(
        "fields",
        [
            {"target": "branch_protection", "require": {"allow_deletions": False}},
            {"target": "branch_protection", "require": {"require_approvals": 0}},
            {"target": "branches", "require": {"prevent_deletion": True}},
            {"require": {"prevent_deletion": True}},
            {"target": "branch_protection"},
            {"target": "repository", "require": {"visibility": "public"}, "branch": "main"},
            {"target": "branch_protection", "require": {"prevent_deletion": True}, "payload_template": "x"},
        ],
    )
    def test_invalid_platform_setting_fails_validation(self, fields: dict) -> None:
        with pytest.raises(ValidationError):
            FrameworkConfig.model_validate(_framework({"handler": "platform_setting", **fields}))


@pytest.mark.unit
class TestRegistry:
    def test_platform_setting_supports_plan_and_api_call_is_gone(self) -> None:
        register_builtin_handlers()
        registry = get_sieve_handler_registry()

        assert registry.get("platform_setting").supports_plan is True
        assert registry.get("api_call") is None


@pytest.mark.unit
class TestHandler:
    def test_plan_returns_change_sets_and_writes_nothing(self, tmp_path: Path, gh_platform) -> None:
        gh = gh_platform("stricter")
        handler = get_sieve_handler_registry().get("platform_setting").fn
        context = HandlerContext(local_path=str(tmp_path), owner=OWNER, repo=REPO, mode="plan")

        result = handler({"target": "branch_protection", "require": {"prevent_deletion": True}}, context)

        assert result.status.value == "pass"
        [change_set] = result.evidence["change_sets"]
        assert change_set["operations"][0]["method"] == "PUT"
        assert gh.writes == []

    def test_unreadable_state_is_error_with_class(self, tmp_path: Path, gh_platform) -> None:
        gh_platform("read_failure")
        handler = get_sieve_handler_registry().get("platform_setting").fn
        context = HandlerContext(local_path=str(tmp_path), owner=OWNER, repo=REPO, mode="plan")

        result = handler({"target": "branch_protection", "require": {"prevent_deletion": True}}, context)

        assert result.status.value == "error"
        assert result.error_class == "unavailable"


@pytest.mark.unit
class TestExecutor:
    def test_preview_carries_change_sets_and_changes_nothing(self, tmp_path: Path, gh_platform) -> None:
        gh = gh_platform("stricter")
        before = snapshot(tmp_path)

        result = RemediationExecutor(local_path=str(tmp_path), owner=OWNER, repo=REPO).execute(
            "T-01", RemediationConfig(handlers=[AC_03_02]), dry_run=True
        )

        [item] = result.plan
        assert item.previewable is True
        assert item.requires_individual_approval is False
        assert item.change_sets[0]["operations"]
        assert gh.writes == []
        assert_unchanged(tmp_path, before)

    def test_high_impact_under_prompt_requires_individual_approval(self, tmp_path: Path, gh_platform) -> None:
        gh_platform("private_repo")

        result = RemediationExecutor(local_path=str(tmp_path), owner=OWNER, repo=REPO).execute(
            "T-01", RemediationConfig(handlers=[PUBLIC]), dry_run=True
        )

        assert result.plan[0].requires_individual_approval is True

    def test_high_impact_under_auto_needs_no_individual_approval(self, tmp_path: Path, gh_platform) -> None:
        gh_platform("private_repo")
        session = PlatformSession(REPOSITORY, policy=_policy(high_impact="auto"))

        result = RemediationExecutor(local_path=str(tmp_path), owner=OWNER, repo=REPO, platform=session).execute(
            "T-01", RemediationConfig(handlers=[PUBLIC]), dry_run=True
        )

        assert result.plan[0].requires_individual_approval is False

    def test_apply_without_approval_writes_nothing(self, tmp_path: Path, simulated_gh) -> None:
        gh = simulated_gh("stricter")
        session = PlatformSession(REPOSITORY, policy=_policy())

        result = RemediationExecutor(local_path=str(tmp_path), owner=OWNER, repo=REPO, platform=session).execute(
            "T-01", RemediationConfig(handlers=[AC_03_02]), dry_run=False
        )

        assert gh.writes == []
        assert result.changed is False
        assert manifest.load_run(REPOSITORY, checkout=tmp_path) is None

    def test_apply_with_approval_writes_and_records_the_change_set(self, tmp_path: Path, simulated_gh) -> None:
        simulated_gh("stricter")
        preview = RemediationExecutor(local_path=str(tmp_path), owner=OWNER, repo=REPO).execute(
            "T-01", RemediationConfig(handlers=[AC_03_02]), dry_run=True
        )
        digest = preview.plan[0].change_sets[0]["digest"]
        gh = simulated_gh("stricter")
        session = PlatformSession(REPOSITORY, policy=_policy(), approvals=[digest])

        result = RemediationExecutor(local_path=str(tmp_path), owner=OWNER, repo=REPO, platform=session).execute(
            "T-01", RemediationConfig(handlers=[AC_03_02]), dry_run=False
        )

        assert [(w.method, w.endpoint) for w in gh.writes] == [("PUT", "/repos/o/r/branches/main/protection")]
        assert result.changed is True
        run = manifest.load_run(REPOSITORY, result.run_id, checkout=tmp_path)
        assert run.change_sets == [digest]
        assert run.files == []

    def test_requirements_from_several_controls_share_one_change_set(self, tmp_path: Path, simulated_gh) -> None:
        gh = simulated_gh("unprotected")
        requests = [
            PlatformRequirement(target="branch_protection", require={"require_pull_request": True}),
            PlatformRequirement(target="branch_protection", require={"prevent_deletion": True}),
        ]
        session = PlatformSession(REPOSITORY, requests, policy=_policy(platform="auto"))
        executor = RemediationExecutor(local_path=str(tmp_path), owner=OWNER, repo=REPO, platform=session)

        first = executor.execute(
            "C-1",
            RemediationConfig(
                handlers=[_platform_setting(target="branch_protection", require={"require_pull_request": True})]
            ),
            dry_run=False,
        )
        second = executor.execute("C-2", RemediationConfig(handlers=[AC_03_02]), dry_run=False)

        assert len(gh.writes) == 1, "one combined change, not two full replacements"
        assert first.changed and second.changed

    def test_non_github_checkout_is_manual_with_no_platform_call(self, tmp_path: Path, gh_platform) -> None:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "remote", "add", "origin", "https://gitlab.com/o/r.git"], check=True
        )
        gh = gh_platform("stricter")

        result = RemediationExecutor(local_path=str(tmp_path), owner=OWNER, repo=REPO).execute(
            "T-01", RemediationConfig(handlers=[AC_03_02]), dry_run=False
        )

        assert gh.calls == []
        assert result.changed is False
        evidence = result.details["handlers"][0]["evidence"]
        assert evidence["platform_results"][0]["kind"] == "manual"
