"""The gh_api step: only declared platform responses prove FAIL (feature 041 US2, FR-007, FR-008).

Every test serves recorded responses through the ``gh_api_with_status``
responder hook, so nothing reaches the network or needs ``gh`` installed.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from darnit.config.framework_schema import HandlerInvocation
from darnit.core import utils
from darnit.core.utils import RecordedGhApi, set_gh_api_responder
from darnit.sieve.builtin_handlers import gh_api_handler
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus, get_sieve_handler_registry
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator

PROTECTION = "/repos/octo/hello/branches/main/protection"
STEP = {"handler": "gh_api", "endpoint": "/repos/$OWNER/$REPO/branches/$BRANCH/protection"}


@pytest.fixture()
def recorded():
    """Install a recorded responder; yield a function that sets the responses."""
    previous = set_gh_api_responder(None)

    def install(responses=None, **kwargs) -> RecordedGhApi:
        responder = RecordedGhApi(responses, **kwargs)
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)


def _ctx() -> HandlerContext:
    return HandlerContext(local_path="/tmp", owner="octo", repo="hello", default_branch="main", control_id="GH-01")


def _run(config: dict) -> object:
    return gh_api_handler({**STEP, **config}, _ctx())


def test_registered_with_pass_fail_ceiling() -> None:
    info = get_sieve_handler_registry().get("gh_api")
    assert info is not None
    assert info.ceiling == frozenset({"pass", "fail"})
    assert info.existence_ceiling is None


class TestSuccessfulResponses:
    def test_endpoint_substitution(self, recorded) -> None:
        responder = recorded({PROTECTION: {"status": 200, "body": {}}})
        result = _run({})
        assert responder.calls == [PROTECTION]
        assert result.evidence["endpoint"] == PROTECTION

    def test_200_without_expr_passes(self, recorded) -> None:
        recorded({PROTECTION: {"status": 200, "body": {"enabled": True}}})
        result = _run({})
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["response"] == {"status_code": 200, "body": {"enabled": True}}

    def test_200_expr_true_passes(self, recorded) -> None:
        recorded({PROTECTION: {"status": 200, "body": {"required_pull_request_reviews": {"count": 1}}}})
        result = _run({"expr": "has(response.body.required_pull_request_reviews)"})
        assert result.status == HandlerResultStatus.PASS
        assert result.error_class is None

    def test_200_expr_false_fails(self, recorded) -> None:
        recorded({PROTECTION: {"status": 200, "body": {"enforce_admins": {"enabled": False}}}})
        result = _run({"expr": "has(response.body.required_pull_request_reviews)"})
        assert result.status == HandlerResultStatus.FAIL
        assert result.error_class is None

    def test_expr_over_status_code(self, recorded) -> None:
        recorded({PROTECTION: {"status": 200, "body": None}})
        assert _run({"expr": "response.status_code == 200"}).status == HandlerResultStatus.PASS

    def test_expr_that_cannot_be_evaluated_is_error(self, recorded) -> None:
        recorded({PROTECTION: {"status": 200, "body": ["not", "an", "object"]}})
        result = _run({"expr": "response.body.enabled == true"})
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"


class TestDeclaredFailure:
    def test_404_declared_fails(self, recorded) -> None:
        recorded({PROTECTION: {"status": 404, "error": "HTTP 404: Branch not protected"}})
        result = _run({"fail_on_status": [404]})
        assert result.status == HandlerResultStatus.FAIL
        assert result.error_class is None
        assert result.evidence["response"]["status_code"] == 404

    def test_404_undeclared_is_error(self, recorded) -> None:
        recorded({PROTECTION: {"status": 404, "error": "HTTP 404: Not Found"}})
        result = _run({})
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "unavailable"

    def test_rate_limited_403_never_proves_failure(self, recorded) -> None:
        recorded({PROTECTION: {"status": 403, "error": "HTTP 403: API rate limit exceeded for user"}})
        result = _run({"fail_on_status": [403]})
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "rate_limit"


class TestBrokenMeasurements:
    @pytest.mark.parametrize(
        ("status", "error", "expected"),
        [
            (401, "HTTP 401: Bad credentials", "auth"),
            (403, "HTTP 403: Resource not accessible by integration", "auth"),
            (429, "HTTP 429: Too Many Requests", "rate_limit"),
            (403, "HTTP 403: You have exceeded a secondary rate limit", "rate_limit"),
            (500, "HTTP 500: Internal Server Error", "unavailable"),
            (502, "HTTP 502: Bad Gateway", "unavailable"),
        ],
    )
    def test_status_classes(self, recorded, status, error, expected) -> None:
        recorded({PROTECTION: {"status": status, "error": error}})
        result = _run({"fail_on_status": [404]})
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == expected
        assert expected in result.message

    def test_transport_failure_is_unavailable(self, recorded) -> None:
        recorded({})
        result = _run({"fail_on_status": [404]})
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "unavailable"

    def test_gh_missing_is_missing_tool(self, recorded) -> None:
        recorded(gh_missing=True)
        result = _run({"fail_on_status": [404]})
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "missing_tool"

    def test_gh_missing_without_responder(self) -> None:
        previous = set_gh_api_responder(None)
        try:
            with patch("darnit.core.utils.subprocess.run", side_effect=FileNotFoundError("gh")):
                result = _run({})
        finally:
            set_gh_api_responder(previous)
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "missing_tool"

    def test_real_gh_stderr_is_classified(self) -> None:
        cp = subprocess.CompletedProcess(args=["gh"], returncode=1, stdout="", stderr="HTTP 403: Forbidden (x)")
        previous = set_gh_api_responder(None)
        try:
            with patch("darnit.core.utils.subprocess.run", return_value=cp):
                result = _run({"fail_on_status": [404]})
        finally:
            set_gh_api_responder(previous)
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "auth"

    def test_missing_endpoint_is_error(self) -> None:
        result = gh_api_handler({"handler": "gh_api"}, _ctx())
        assert result.status == HandlerResultStatus.ERROR


class TestResponder:
    def test_responder_restores_previous(self) -> None:
        first = RecordedGhApi({})
        original = set_gh_api_responder(first)
        try:
            assert set_gh_api_responder(None) is first
        finally:
            set_gh_api_responder(original)

    def test_recorded_error_status_has_no_body(self) -> None:
        body, status, error = RecordedGhApi({"x": {"status": 404, "body": {"ignored": 1}}})("/x")
        assert (body, status) == (None, 404)
        assert error == "HTTP 404"

    def test_responder_bypasses_gh(self, recorded) -> None:
        recorded({"/x": {"status": 200, "body": {"a": 1}}})
        with patch("darnit.core.utils.subprocess.run", side_effect=AssertionError("gh must not run")):
            assert utils.gh_api_with_status("/x") == ({"a": 1}, 200, "")


def _verify(*invocations: HandlerInvocation):
    spec = ControlSpec(
        control_id="GH-01",
        level=1,
        domain="GH",
        name="Platform",
        description="Platform",
        metadata={"handler_invocations": list(invocations)},
    )
    ctx = CheckContext(owner="octo", repo="hello", local_path="/tmp", default_branch="main", control_id="GH-01")
    return SieveOrchestrator().verify(spec, ctx)


class TestThroughOrchestrator:
    """The step declaration ``fail_on_status`` reaches the handler and decides the control."""

    def test_declared_404_concludes_fail(self, recorded) -> None:
        recorded({PROTECTION: {"status": 404, "error": "HTTP 404: Branch not protected"}})
        result = _verify(
            HandlerInvocation(handler="gh_api", endpoint=STEP["endpoint"], fail_on_status=[404]),
            HandlerInvocation(handler="manual", steps=["Check branch protection"]),
        )
        assert result.status == "FAIL"
        assert result.concluded_by == "gh_api"

    def test_forbidden_ends_error_with_cause(self, recorded) -> None:
        recorded({PROTECTION: {"status": 403, "error": "HTTP 403: Resource not accessible by integration"}})
        result = _verify(
            HandlerInvocation(handler="gh_api", endpoint=STEP["endpoint"], fail_on_status=[404]),
            HandlerInvocation(handler="manual", steps=["Check branch protection"]),
        )
        assert result.status == "ERROR"
        assert result.error["class"] == "auth"
        assert "403" in result.error["cause"]
        assert result.to_legacy_dict()["error"] == result.error

    def test_expr_evaluated_once_by_handler(self, recorded, caplog) -> None:
        recorded({PROTECTION: {"status": 200, "body": {"required_pull_request_reviews": {}}}})
        with caplog.at_level("WARNING"):
            result = _verify(
                HandlerInvocation(
                    handler="gh_api",
                    endpoint=STEP["endpoint"],
                    expr="has(response.body.required_pull_request_reviews)",
                ),
            )
        assert result.status == "PASS"
        assert not [r for r in caplog.records if "CEL evaluation failed" in r.getMessage()]
