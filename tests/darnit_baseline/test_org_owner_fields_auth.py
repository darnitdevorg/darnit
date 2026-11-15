"""Tests for AC-01.01 and AC-02.01 owner-only org fields reporting ERROR [auth] (issue #753)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from darnit.config import load_framework_config
from darnit.config.control_loader import control_from_framework, validate_step_authority
from darnit.config.framework_schema import HandlerInvocation
from darnit.core.errors import AuthorityViolation
from darnit.core.utils import RecordedGhApi, set_gh_api_responder
from darnit.sieve.builtin_handlers import gh_api_handler
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_TOML = REPO_ROOT / "packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml"
OWNER = "pallets"
REPO = "flask"


@pytest.fixture
def recorded_platform():
    previous = set_gh_api_responder(None)

    def install(responses: dict[str, Any]) -> RecordedGhApi:
        responder = RecordedGhApi(responses)
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)


def _control(control_id: str):
    framework = load_framework_config(BASELINE_TOML)
    return control_from_framework(
        control_id, framework.controls[control_id].model_copy(deep=True), framework="openssf-baseline"
    )


def _audit(control_id: str, repo_path: Path) -> list[dict[str, Any]]:
    from darnit.config.operator.loader import LoadedOperatorConfig
    from darnit.config.operator.schema import OperatorConfig
    from darnit.tools.audit import run_sieve_audit

    operator = LoadedOperatorConfig(
        config=OperatorConfig.model_validate({"schema_version": 1}),
        source="test",
        digest=None,
        permission_check="ok",
        strict=False,
    )
    results, _ = run_sieve_audit(
        owner=OWNER,
        repo=REPO,
        local_path=str(repo_path),
        default_branch="main",
        level=1,
        controls=[_control(control_id)],
        framework_name="openssf-baseline",
        operator_config=operator,
    )
    return results


@pytest.mark.unit
class TestAc0101OrgOwnerFields:
    def test_shipped_step_declares_auth_fields(self) -> None:
        step = load_framework_config(BASELINE_TOML).controls["OSPS-AC-01.01"].passes[0]
        assert step.model_extra["endpoint"] == "/orgs/$OWNER"
        assert step.model_extra["auth_fields"] == {
            "two_factor_requirement_enabled": "visible only to organization owners"
        }

    def test_ac_01_01_reports_auth_error_when_org_omits_2fa_field(self, recorded_platform, tmp_path: Path) -> None:
        recorded_platform(
            {
                f"/orgs/{OWNER}": {"status": 200, "body": {"login": OWNER, "type": "Organization"}},
                "/user": {"status": 200, "body": {"login": "auditor", "two_factor_authentication": False}},
            }
        )
        (result,) = _audit("OSPS-AC-01.01", tmp_path)
        assert result["status"] == "ERROR"
        assert result["error_class"] == "auth"
        assert result["error"]["class"] == "auth"
        assert "two_factor_requirement_enabled" in result["error"]["cause"]
        assert "visible only to organization owners" in result["error"]["cause"]

    def test_ac_01_01_passes_when_org_owner_token_sees_2fa_enabled(self, recorded_platform, tmp_path: Path) -> None:
        recorded_platform(
            {
                f"/orgs/{OWNER}": {
                    "status": 200,
                    "body": {"login": OWNER, "type": "Organization", "two_factor_requirement_enabled": True},
                },
                "/user": {"status": 200, "body": {"login": "auditor", "two_factor_authentication": True}},
            }
        )
        (result,) = _audit("OSPS-AC-01.01", tmp_path)
        assert result["status"] == "PASS"
        assert result.get("error_class") is None


@pytest.mark.unit
class TestAc0201OrgOwnerFields:
    def test_shipped_step_declares_auth_fields(self) -> None:
        step = load_framework_config(BASELINE_TOML).controls["OSPS-AC-02.01"].passes[0]
        assert step.model_extra["endpoint"] == "/orgs/$OWNER"
        assert step.model_extra["auth_fields"] == {
            "default_repository_permission": "visible only to organization owners"
        }

    def test_ac_02_01_reports_auth_error_when_org_omits_default_permission(
        self, recorded_platform, tmp_path: Path
    ) -> None:
        recorded_platform(
            {
                f"/orgs/{OWNER}": {"status": 200, "body": {"login": OWNER, "type": "Organization"}},
            }
        )
        (result,) = _audit("OSPS-AC-02.01", tmp_path)
        assert result["status"] == "ERROR"
        assert result["error_class"] == "auth"
        assert result["error"]["class"] == "auth"
        assert "default_repository_permission" in result["error"]["cause"]
        assert "visible only to organization owners" in result["error"]["cause"]

    def test_ac_02_01_passes_when_default_permission_is_none(self, recorded_platform, tmp_path: Path) -> None:
        recorded_platform(
            {
                f"/orgs/{OWNER}": {
                    "status": 200,
                    "body": {"login": OWNER, "type": "Organization", "default_repository_permission": "none"},
                },
            }
        )
        step = load_framework_config(BASELINE_TOML).controls["OSPS-AC-02.01"].passes[0]
        ctx = HandlerContext(local_path=str(tmp_path), owner=OWNER, repo=REPO, control_id="OSPS-AC-02.01")
        result = gh_api_handler(step.model_dump() | step.model_extra, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert result.error_class is None


@pytest.mark.unit
class TestAuthFieldsValidation:
    def test_gh_api_accepts_auth_fields_dict(self) -> None:
        inv = HandlerInvocation(
            handler="gh_api",
            endpoint="/orgs/$OWNER",
            auth_fields={"two_factor_requirement_enabled": "visible only to organization owners"},
        )
        validate_step_authority("test-fw", "T-01", [inv])

    def test_gh_api_rejects_auth_fields_list(self) -> None:
        inv = HandlerInvocation(
            handler="gh_api",
            endpoint="/orgs/$OWNER",
            auth_fields=["two_factor_requirement_enabled"],
        )
        with pytest.raises(AuthorityViolation, match="auth_fields must be a mapping"):
            validate_step_authority("test-fw", "T-01", [inv])

    def test_gh_api_rejects_empty_auth_fields_dict(self) -> None:
        inv = HandlerInvocation(
            handler="gh_api",
            endpoint="/orgs/$OWNER",
            auth_fields={},
        )
        with pytest.raises(AuthorityViolation, match="auth_fields mapping must map response body keys to non-empty strings"):
            validate_step_authority("test-fw", "T-01", [inv])

    def test_gh_api_rejects_non_string_auth_fields(self) -> None:
        inv = HandlerInvocation(
            handler="gh_api",
            endpoint="/orgs/$OWNER",
            auth_fields=123,
        )
        with pytest.raises(AuthorityViolation, match="auth_fields must be a mapping"):
            validate_step_authority("test-fw", "T-01", [inv])

    def test_non_gh_api_rejects_auth_fields(self) -> None:
        inv = HandlerInvocation(
            handler="exec",
            command=["echo", "hi"],
            auth_fields={"something": "some reason"},
        )
        with pytest.raises(AuthorityViolation, match="unknown step key 'auth_fields'"):
            validate_step_authority("test-fw", "T-01", [inv])

