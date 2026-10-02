"""The ``gh`` responder seam serves method-keyed recordings (feature 043 T002, T003; research R12)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from darnit.core import utils
from darnit.core.utils import GhApiCall, RecordedGhApi, set_gh_api_responder
from tests.darnit.remediation.platform.conftest import PLATFORM_FIXTURES, recorded_gh

PROTECTION = "/repos/o/r/branches/main/protection"


@pytest.fixture()
def installed():
    previous = set_gh_api_responder(None)

    def install(responses=None, **kwargs) -> RecordedGhApi:
        responder = RecordedGhApi(responses, **kwargs)
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)


class TestResponderSignature:
    def test_get_caller_reaches_responder_as_get(self) -> None:
        seen: list[tuple] = []

        def responder(method, endpoint, body):
            seen.append((method, endpoint, body))
            return {"ok": True}, 200, ""

        previous = set_gh_api_responder(responder)
        try:
            assert utils.gh_api_with_status("/x", paginate=True) == ({"ok": True}, 200, "")
        finally:
            set_gh_api_responder(previous)
        assert seen == [("GET", "/x", None)]

    def test_gh_api_wrapper_still_served(self, installed) -> None:
        installed({"/repos/o/r": {"status": 200, "body": {"default_branch": "main"}}})
        assert utils.gh_api("/repos/o/r") == {"default_branch": "main"}


class TestRecordedKeys:
    def test_bare_path_is_get(self) -> None:
        responder = RecordedGhApi({PROTECTION: {"status": 200, "body": {"a": 1}}})
        assert responder("GET", PROTECTION, None) == ({"a": 1}, 200, "")
        assert responder("PUT", PROTECTION, {"a": 2})[1] == 0

    def test_method_keys(self) -> None:
        responder = RecordedGhApi(
            {
                f"GET {PROTECTION}": {"status": 200, "body": {"before": True}},
                f"PUT {PROTECTION}": {"status": 200, "body": {"after": True}},
                f"patch {PROTECTION}/required_pull_request_reviews": {"status": 403, "error": "HTTP 403: Forbidden"},
            }
        )
        assert responder("GET", PROTECTION, None) == ({"before": True}, 200, "")
        assert responder("PUT", PROTECTION, {}) == ({"after": True}, 200, "")
        assert responder("PATCH", PROTECTION + "/required_pull_request_reviews", {}) == (
            None,
            403,
            "HTTP 403: Forbidden",
        )

    def test_leading_slash_optional(self) -> None:
        responder = RecordedGhApi({"PUT repos/o/r/x": {"status": 204}})
        assert responder("put", "/repos/o/r/x", {}) == (None, 204, "")

    def test_unrecorded_write_is_transport_failure(self) -> None:
        body, status, error = RecordedGhApi({})("POST", "/repos/o/r/x", {"a": 1})
        assert (body, status) == (None, 0)
        assert "POST /repos/o/r/x" in error

    def test_single_argument_call_is_get(self) -> None:
        assert RecordedGhApi({"/x": {"status": 200, "body": [1]}})("/x") == ([1], 200, "")

    def test_gh_missing_answers_writes(self) -> None:
        assert RecordedGhApi(gh_missing=True)("PUT", "/x", {})[2] == utils._GH_CLI_MISSING_MESSAGE

    def test_record_replaces_a_response(self) -> None:
        responder = RecordedGhApi({PROTECTION: {"status": 404, "error": "HTTP 404: Branch not protected"}})
        responder.record(PROTECTION, {"status": 200, "body": {"x": 1}})
        assert responder("GET", PROTECTION, None) == ({"x": 1}, 200, "")


class TestRecordedCalls:
    def test_calls_carry_method_endpoint_body(self) -> None:
        responder = RecordedGhApi({})
        responder("GET", "/a", None)
        responder("PUT", "/b", {"enforce_admins": True})
        assert responder.calls == [GhApiCall("GET", "/a", None), GhApiCall("PUT", "/b", {"enforce_admins": True})]
        method, endpoint, body = responder.calls[1]
        assert (method, endpoint, body) == ("PUT", "/b", {"enforce_admins": True})
        assert responder.calls[1].body == {"enforce_admins": True}

    def test_get_call_equals_its_path(self) -> None:
        responder = RecordedGhApi({})
        responder("/a")
        responder("PUT", "/a", {})
        assert responder.calls == ["/a", "PUT /a"]
        assert responder.calls[0] == "GET /a"
        assert responder.calls[1] != "/a"

    def test_writes_lists_non_get_calls(self) -> None:
        responder = RecordedGhApi({})
        responder("GET", "/a", None)
        responder("PATCH", "/b", {"x": 1})
        assert responder.writes == [GhApiCall("PATCH", "/b", {"x": 1})]

    def test_calls_are_hashable(self) -> None:
        assert len({GhApiCall("GET", "/a", None), GhApiCall("GET", "/a", None)}) == 1

    def test_write_body_is_recorded_through_gh_api_write(self, installed) -> None:
        responder = installed({f"PUT {PROTECTION}": {"status": 200, "body": {}}})
        with patch("darnit.core.utils.subprocess.run", side_effect=AssertionError("gh must not run")):
            assert utils.gh_api_write("PUT", PROTECTION, {"enforce_admins": True}) == ({}, 200, "")
        assert responder.calls == [GhApiCall("PUT", PROTECTION, {"enforce_admins": True})]


EXPECTED_FIXTURES = {
    "unprotected",
    "stricter",
    "satisfied",
    "ruleset_only",
    "read_only_token",
    "read_failure",
    "unknown_field",
    "default_branch_release",
    "private_repo",
    "pvr_disabled",
}


def _get(name: str, endpoint: str):
    with recorded_gh(PLATFORM_FIXTURES[name]()):
        return utils.gh_api_with_status(endpoint)


def _protection(name: str, branch: str = "main") -> dict:
    body, status, _ = _get(name, f"/repos/o/r/branches/{branch}/protection")
    assert status == 200
    return body


class TestPlatformFixtures:
    def test_every_fixture_is_present(self) -> None:
        assert set(PLATFORM_FIXTURES) == EXPECTED_FIXTURES

    @pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES))
    def test_fixture_serves_every_recording(self, name: str) -> None:
        responses = PLATFORM_FIXTURES[name]()
        responder = RecordedGhApi(responses)
        for key, recorded in responses.items():
            method, _, path = key.partition(" ") if " " in key else ("GET", "", key)
            body = None if method == "GET" else {}
            assert responder(method, path, body)[1] == int(recorded.get("status", 200)), key
        assert len(responder.calls) == len(responses)

    @pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES - {"read_failure"}))
    def test_repository_and_default_branch_readable(self, name: str) -> None:
        repo, status, _ = _get(name, "/repos/o/r")
        assert status == 200
        branch, status, _ = _get(name, f"/repos/o/r/branches/{repo['default_branch']}")
        assert status == 200
        assert isinstance(branch["protected"], bool)

    def test_fixtures_are_fresh_copies(self) -> None:
        first = PLATFORM_FIXTURES["stricter"]()
        first["/repos/o/r"]["body"]["default_branch"] = "mutated"
        assert PLATFORM_FIXTURES["stricter"]()["/repos/o/r"]["body"]["default_branch"] == "main"

    def test_unprotected(self) -> None:
        assert _get("unprotected", "/repos/o/r/branches/main")[0]["protected"] is False
        assert _get("unprotected", PROTECTION)[1] == 404
        with recorded_gh(PLATFORM_FIXTURES["unprotected"]()):
            assert utils.gh_api_write("PUT", PROTECTION, {})[1] == 200

    def test_stricter_shape(self) -> None:
        protection = _protection("stricter")
        reviews = protection["required_pull_request_reviews"]
        assert reviews["required_approving_review_count"] == 2
        assert reviews["require_code_owner_reviews"] is True
        checks = protection["required_status_checks"]
        assert checks["contexts"] == ["ci/build", "ci/test"]
        assert [c["context"] for c in checks["checks"]] == checks["contexts"]
        assert all(isinstance(c["app_id"], int) for c in checks["checks"])
        restrictions = protection["restrictions"]
        assert [u["login"] for u in restrictions["users"]] == ["octocat"]
        assert [t["slug"] for t in restrictions["teams"]] == ["release-managers"]
        assert [a["slug"] for a in restrictions["apps"]] == ["deploy-bot"]
        assert protection["enforce_admins"] == {"url": protection["enforce_admins"]["url"], "enabled": True}
        assert protection["required_linear_history"] == {"enabled": True}
        assert protection["required_conversation_resolution"] == {"enabled": True}
        assert protection["allow_force_pushes"] == {"enabled": False}
        assert protection["allow_deletions"] == {"enabled": True}

    def test_satisfied(self) -> None:
        protection = _protection("satisfied")
        assert protection["required_pull_request_reviews"]["required_approving_review_count"] >= 1
        assert protection["enforce_admins"]["enabled"] is True
        assert protection["allow_deletions"] == {"enabled": False}
        assert protection["allow_force_pushes"] == {"enabled": False}

    def test_ruleset_only(self) -> None:
        assert _get("ruleset_only", PROTECTION)[1] == 404
        rules, status, _ = _get("ruleset_only", "/repos/o/r/rules/branches/main")
        assert status == 200
        assert {r["type"] for r in rules} == {"pull_request", "deletion"}

    def test_read_only_token(self) -> None:
        assert _get("read_only_token", PROTECTION)[1] == 200
        with recorded_gh(PLATFORM_FIXTURES["read_only_token"]()) as responder:
            for method, endpoint in [
                ("PUT", PROTECTION),
                ("PATCH", PROTECTION + "/required_pull_request_reviews"),
                ("POST", PROTECTION + "/enforce_admins"),
            ]:
                assert utils.gh_api_write(method, endpoint, {})[1] == 403
        assert len(responder.writes) == 3

    def test_read_failure(self) -> None:
        assert _get("read_failure", PROTECTION)[1] == 502
        assert _get("read_failure", "/repos/o/r/rules/branches/main")[1] == 0
        with recorded_gh(PLATFORM_FIXTURES["read_failure"]()):
            assert utils.gh_api_write("PUT", PROTECTION, {})[1] == 0

    def test_unknown_field(self) -> None:
        known = set(_protection("stricter"))
        assert set(_protection("unknown_field")) - known == {"future_setting"}

    def test_default_branch_release(self) -> None:
        assert _get("default_branch_release", "/repos/o/r")[0]["default_branch"] == "release"
        assert _get("default_branch_release", "/repos/o/r/branches/release")[0]["protected"] is False
        assert _get("default_branch_release", "/repos/o/r/branches/release/protection")[1] == 404
        assert _protection("default_branch_release", "main")["allow_deletions"] == {"enabled": False}
        with recorded_gh(PLATFORM_FIXTURES["default_branch_release"]()):
            assert utils.gh_api_write("PUT", "/repos/o/r/branches/release/protection", {})[1] == 200
            assert utils.gh_api_write("PUT", PROTECTION, {})[1] == 0

    def test_private_repo(self) -> None:
        repo = _get("private_repo", "/repos/o/r")[0]
        assert (repo["private"], repo["visibility"]) == (True, "private")

    def test_pvr_disabled(self) -> None:
        assert _get("pvr_disabled", "/repos/o/r/private-vulnerability-reporting")[0] == {"enabled": False}
        assert _get("unprotected", "/repos/o/r/private-vulnerability-reporting")[0] == {"enabled": True}

    def test_recorded_gh_restores_previous_responder(self) -> None:
        outer = RecordedGhApi({})
        original = set_gh_api_responder(outer)
        try:
            with recorded_gh({}) as inner:
                assert utils._gh_api_responder is inner
            assert utils._gh_api_responder is outer
        finally:
            set_gh_api_responder(original)
