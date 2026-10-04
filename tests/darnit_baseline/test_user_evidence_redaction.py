"""The auditor's profile stays out of audit output (feature 044, US4, FR-012, SC-005).

OSPS-AC-01.01 reads the auditing user's own account (``/user``) for its
two-factor value. Only the fields the check needs are kept in evidence, so
the JSON report and the attestation predicate never carry the auditor's
email, location, company, or biography (framework-design 3.8).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
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
OWNER = "auditor"
REPO = "project"

PROFILE = {
    "login": "auditor",
    "two_factor_authentication": True,
    "email": "auditor@private.example.net",
    "location": "Secret City",
    "company": "Hidden Employer Inc",
    "bio": "A biography that must never be published",
    "name": "Ada Auditor",
}
PERSONAL_VALUES = [PROFILE[k] for k in ("email", "location", "company", "bio", "name")]


@pytest.fixture
def recorded_platform() -> Iterator[None]:
    previous = set_gh_api_responder(
        RecordedGhApi(
            {
                f"/orgs/{OWNER}": {"status": 404, "body": {"message": "Not Found"}, "error": "Not Found (HTTP 404)"},
                "/user": {"status": 200, "body": PROFILE},
            }
        )
    )
    try:
        yield
    finally:
        set_gh_api_responder(previous)


def _ac_01_01():
    framework = load_framework_config(BASELINE_TOML)
    return control_from_framework(
        "OSPS-AC-01.01", framework.controls["OSPS-AC-01.01"].model_copy(deep=True), framework="openssf-baseline"
    )


def _audit(repo: Path) -> list[dict[str, Any]]:
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
        local_path=str(repo),
        default_branch="main",
        level=1,
        controls=[_ac_01_01()],
        framework_name="openssf-baseline",
        operator_config=operator,
    )
    return results


def _assert_no_profile(text: str) -> None:
    for value in PERSONAL_VALUES:
        assert value not in text, value


@pytest.mark.unit
@pytest.mark.usefixtures("recorded_platform")
class TestAc0101:
    def test_shipped_step_declares_evidence_fields(self) -> None:
        step = load_framework_config(BASELINE_TOML).controls["OSPS-AC-01.01"].passes[1]

        assert step.model_extra["endpoint"] == "/user"
        assert step.model_extra["evidence_fields"] == ["login", "two_factor_authentication"]

    def test_evidence_keeps_only_the_declared_fields(self, tmp_path: Path) -> None:
        (result,) = _audit(tmp_path)

        assert result["evidence"]["endpoint"] == "/user"
        assert result["evidence"]["response"]["body"] == {"login": "auditor", "two_factor_authentication": True}

    def test_json_report_and_attestation_carry_no_profile(self, tmp_path: Path) -> None:
        from darnit_baseline.attestation.predicate import build_assessment_predicate

        results = _audit(tmp_path)
        predicate = build_assessment_predicate(
            owner=OWNER,
            repo=REPO,
            commit="0" * 40,
            ref="refs/heads/main",
            level=1,
            results=results,
            project_config=None,
            adapters_used=["builtin"],
        )

        _assert_no_profile(json.dumps({"results": results}, default=str))
        _assert_no_profile(json.dumps(predicate, default=str))
        assert "two_factor_authentication" in json.dumps(predicate)


@pytest.mark.unit
class TestGhApiEvidenceFields:
    def _run(self, config: dict[str, Any]):
        previous = set_gh_api_responder(RecordedGhApi({"/user": {"status": 200, "body": PROFILE}}))
        try:
            return gh_api_handler(config, HandlerContext(local_path=".", owner=OWNER, repo=REPO))
        finally:
            set_gh_api_responder(previous)

    def test_expression_sees_the_full_response(self) -> None:
        result = self._run(
            {"endpoint": "/user", "evidence_fields": ["login"], "expr": 'response.body.email.endsWith(".net")'}
        )

        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["response"]["body"] == {"login": "auditor"}

    def test_without_evidence_fields_the_body_is_kept(self) -> None:
        result = self._run({"endpoint": "/user"})

        assert result.evidence["response"]["body"] == PROFILE


@pytest.mark.unit
class TestPersonalRecordLoadRule:
    @pytest.mark.parametrize("endpoint", ["/user", "user", "/user/emails", "/user/", "/users/someone", "/user?x=1"])
    def test_personal_record_without_evidence_fields_fails_loading(self, endpoint: str) -> None:
        step = HandlerInvocation(handler="gh_api", endpoint=endpoint, expr="response.body.x == true")

        with pytest.raises(AuthorityViolation) as excinfo:
            validate_step_authority("fw", "PRIV-01", [step])

        text = str(excinfo.value)
        for fragment in ("PRIV-01", "pass[0]:gh_api", "evidence_fields"):
            assert fragment in text, (fragment, text)

    def test_personal_record_with_evidence_fields_loads(self) -> None:
        step = HandlerInvocation(handler="gh_api", endpoint="/users/someone", evidence_fields=["login"])

        validate_step_authority("fw", "PRIV-01", [step])

    @pytest.mark.parametrize("endpoint", ["/repos/o/r", "/users", "/userinfo", "/orgs/o/users"])
    def test_other_endpoints_need_no_evidence_fields(self, endpoint: str) -> None:
        validate_step_authority("fw", "PRIV-01", [HandlerInvocation(handler="gh_api", endpoint=endpoint)])

    @pytest.mark.parametrize(
        "endpoint",
        [
            "/orgs/$OWNER/members",
            "/orgs/{org}/members",
            "orgs/kusari-oss/members?per_page=100",
            "/orgs/$OWNER/outside_collaborators",
            "/orgs/$OWNER/teams/maintainers/members",
            "/repos/$OWNER/$REPO/collaborators",
            "/repos/o/r/collaborators/someone/permission",
        ],
    )
    def test_people_listings_are_personal_records(self, endpoint: str) -> None:
        """People records beyond /user and /users/ (044 review, FR-012)."""
        step = HandlerInvocation(handler="gh_api", endpoint=endpoint)

        with pytest.raises(AuthorityViolation, match="evidence_fields"):
            validate_step_authority("fw", "PRIV-01", [step])

    @pytest.mark.parametrize(
        "endpoint", ["/orgs/o", "/orgs/o/teams", "/orgs/o/teams/t/repos", "/repos/o/r/branches", "/members"]
    )
    def test_endpoints_near_people_listings_need_no_evidence_fields(self, endpoint: str) -> None:
        validate_step_authority("fw", "PRIV-01", [HandlerInvocation(handler="gh_api", endpoint=endpoint)])

    @pytest.mark.parametrize(
        "command",
        [
            ["gh", "api", "/user"],
            ["gh", "api", "user"],
            ["gh", "api", "/orgs/$OWNER/members", "--paginate"],
            ["gh", "api", "-H", "Accept: application/vnd.github+json", "/repos/$OWNER/$REPO/collaborators"],
        ],
    )
    def test_exec_reading_a_personal_record_fails_loading(self, command: list[str]) -> None:
        """An exec step would store the whole record in its output; gh_api with evidence_fields is the way (044 review)."""
        step = HandlerInvocation(handler="exec", command=command)

        with pytest.raises(AuthorityViolation) as excinfo:
            validate_step_authority("fw", "PRIV-01", [step])

        text = str(excinfo.value)
        for fragment in ("PRIV-01", "pass[0]:exec", "gh_api", "evidence_fields"):
            assert fragment in text, (fragment, text)

    @pytest.mark.parametrize(
        "command",
        [["gh", "api", "/repos/$OWNER/$REPO"], ["echo", "/user"], ["gh", "pr", "list"], ["gh", "api", "--jq", ".login"]],
    )
    def test_exec_not_reading_a_personal_record_loads(self, command: list[str]) -> None:
        validate_step_authority("fw", "PRIV-01", [HandlerInvocation(handler="exec", command=command)])

    def test_evidence_fields_must_be_a_list_of_names(self) -> None:
        step = HandlerInvocation(handler="gh_api", endpoint="/user", evidence_fields="login")

        with pytest.raises(AuthorityViolation, match="evidence_fields"):
            validate_step_authority("fw", "PRIV-01", [step])
