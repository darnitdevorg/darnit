"""``gh_api_write`` sends JSON on stdin and reads the status from ``--include`` (feature 043 T015, research R12)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from darnit.core import utils
from darnit.core.utils import gh_api_write, set_gh_api_responder

ENDPOINT = "/repos/o/r/branches/main/protection"


@pytest.fixture(autouse=True)
def _no_responder():
    previous = set_gh_api_responder(None)
    yield
    set_gh_api_responder(previous)


def _included(status_line: str, body: str = "", headers: str = "Content-Type: application/json; charset=utf-8") -> str:
    return f"{status_line}\r\n{headers}\r\nX-Github-Request-Id: ABCD\r\n\r\n{body}"


def _run(stdout: str = "", stderr: str = "", returncode: int = 0):
    cp = subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)
    return patch("darnit.core.utils.subprocess.run", return_value=cp)


class TestInvocation:
    def test_sends_json_on_stdin(self) -> None:
        payload = {
            "enforce_admins": True,
            "restrictions": None,
            "required_status_checks": {"strict": True, "contexts": ["ci"]},
        }
        with _run(_included("HTTP/2.0 200 OK", "{}")) as run:
            gh_api_write("put", ENDPOINT, payload)
        args = run.call_args.args[0]
        assert args[:4] == ["gh", "api", "-X", "PUT"]
        assert ENDPOINT in args
        assert "--include" in args
        assert args[args.index("--input") + 1] == "-"
        assert not {"-f", "-F", "--field", "--raw-field"} & set(args)
        assert json.loads(run.call_args.kwargs["input"]) == payload

    def test_no_payload_sends_no_input(self) -> None:
        with _run(_included("HTTP/2.0 204 No Content")) as run:
            assert gh_api_write("DELETE", "/repos/o/r/private-vulnerability-reporting") == (None, 204, "")
        assert "--input" not in run.call_args.args[0]
        assert run.call_args.kwargs.get("input") is None

    @pytest.mark.parametrize("method", ["GET", "HEAD", "TRACE", ""])
    def test_rejects_non_write_methods(self, method: str) -> None:
        with pytest.raises(ValueError):
            gh_api_write(method, ENDPOINT, {})


class TestResponses:
    def test_success_body_parsed(self) -> None:
        body = json.dumps({"url": "https://api.github.com" + ENDPOINT, "enforce_admins": {"enabled": True}}, indent=2)
        with _run(_included("HTTP/2.0 200 OK", body)):
            parsed, status, error = gh_api_write("PUT", ENDPOINT, {})
        assert status == 200
        assert parsed["enforce_admins"] == {"enabled": True}
        assert error == ""

    def test_lf_only_headers(self) -> None:
        with _run('HTTP/1.1 201 Created\nContent-Type: application/json\n\n["ci"]'):
            assert gh_api_write("POST", ENDPOINT + "/required_status_checks/contexts", ["ci"]) == (["ci"], 201, "")

    def test_no_content(self) -> None:
        with _run(_included("HTTP/2.0 204 No Content")):
            assert gh_api_write("PUT", "/repos/o/r/private-vulnerability-reporting") == (None, 204, "")

    def test_http_error_does_not_raise(self) -> None:
        body = json.dumps({"message": "Resource not accessible by integration", "status": "403"})
        with _run(
            _included("HTTP/2.0 403 Forbidden", body),
            stderr="gh: Resource not accessible by integration (HTTP 403)\n",
            returncode=1,
        ):
            parsed, status, error = gh_api_write("PUT", ENDPOINT, {})
        assert (parsed, status) == (None, 403)
        assert "Resource not accessible by integration" in error
        assert utils.gh_api_error_class(status, error) == "auth"

    def test_error_message_from_body_without_stderr(self) -> None:
        body = json.dumps({"message": "Validation Failed", "errors": ["bad"]})
        with _run(_included("HTTP/2.0 422 Unprocessable Entity", body), returncode=1):
            parsed, status, error = gh_api_write("PATCH", ENDPOINT, {})
        assert (parsed, status) == (None, 422)
        assert "Validation Failed" in error

    def test_rate_limit_classified(self) -> None:
        with _run(
            _included("HTTP/2.0 403 Forbidden", '{"message": "API rate limit exceeded for user"}'),
            stderr="gh: API rate limit exceeded for user (HTTP 403)",
            returncode=1,
        ):
            _, status, error = gh_api_write("PUT", ENDPOINT, {})
        assert utils.gh_api_error_class(status, error) == "rate_limit"

    def test_status_from_stderr_when_no_headers(self) -> None:
        with _run("", stderr="gh: Bad Gateway (HTTP 502)", returncode=1):
            assert gh_api_write("PUT", ENDPOINT, {})[:2] == (None, 502)

    def test_no_status_is_ambiguous(self) -> None:
        with _run("", stderr="error connecting to api.github.com", returncode=1):
            assert gh_api_write("PUT", ENDPOINT, {}) == (None, 0, "error connecting to api.github.com")

    def test_invalid_json_on_success_is_ambiguous(self) -> None:
        with _run(_included("HTTP/2.0 200 OK", "<html>")):
            body, status, error = gh_api_write("PUT", ENDPOINT, {})
        assert (body, status) == (None, 0)
        assert "invalid JSON" in error

    def test_gh_missing(self) -> None:
        with patch("darnit.core.utils.subprocess.run", side_effect=FileNotFoundError("gh")):
            body, status, error = gh_api_write("PUT", ENDPOINT, {})
        assert (body, status) == (None, 0)
        assert utils.gh_api_error_class(status, error) == "missing_tool"


class TestResponderSeam:
    def test_responder_receives_method_endpoint_payload(self) -> None:
        seen: list[tuple] = []

        def responder(method, endpoint, body):
            seen.append((method, endpoint, body))
            return None, 204, ""

        set_gh_api_responder(responder)
        with patch("darnit.core.utils.subprocess.run", side_effect=AssertionError("gh must not run")):
            assert gh_api_write("patch", ENDPOINT, {"x": 1}) == (None, 204, "")
        assert seen == [("PATCH", ENDPOINT, {"x": 1})]
