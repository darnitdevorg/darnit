"""Unit tests for the `gh_api_with_status` helper (feature 032).

Mocks `subprocess.run` directly to exercise the helper's status-code
extraction from `gh`'s stderr. Verifies the thin-wrapper contracts of
`gh_api` and `gh_api_safe` are preserved.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from darnit.core import utils


def _cp(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["gh", "api", "..."], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestGhApiStatus:
    def test_200_dict_body(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(0, '{"a":1}')):
            body, status, err = utils.gh_api_with_status("/x")
        assert body == {"a": 1}
        assert status == 200
        assert err == ""

    def test_200_list_body(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(0, '[{"id":1}]')):
            body, status, err = utils.gh_api_with_status("/repos/x/y/rulesets")
        assert body == [{"id": 1}]
        assert status == 200
        assert err == ""

    def test_200_empty_body(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(0, "")):
            body, status, err = utils.gh_api_with_status("/x")
        assert body is None
        assert status == 200

    def test_404_parses_from_stderr(self):
        stderr = "HTTP 404: Not Found (https://api.github.com/repos/x/y/branches/main/protection)"
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", stderr)):
            body, status, err = utils.gh_api_with_status("/x")
        assert body is None
        assert status == 404
        assert "HTTP 404" in err

    def test_403_parses(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", "HTTP 403: Forbidden")):
            body, status, _ = utils.gh_api_with_status("/x")
        assert status == 403

    def test_401_parses(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", "HTTP 401: Unauthorized")):
            _, status, _ = utils.gh_api_with_status("/x")
        assert status == 401

    def test_429_parses(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", "HTTP 429: Too Many Requests")):
            _, status, _ = utils.gh_api_with_status("/x")
        assert status == 429

    def test_5xx_parses(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", "HTTP 502: Bad Gateway")):
            _, status, _ = utils.gh_api_with_status("/x")
        assert status == 502

    def test_unparseable_stderr_returns_zero(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", "connection reset by peer")):
            body, status, err = utils.gh_api_with_status("/x")
        assert body is None
        assert status == 0
        assert "connection reset" in err

    def test_empty_stderr_returns_zero(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", "")):
            body, status, err = utils.gh_api_with_status("/x")
        assert status == 0
        assert "exit code 1" in err

    def test_paginate_flag_in_argv(self):
        captured = {}

        def _run(args, capture_output=None, text=None):
            captured["args"] = args
            return _cp(0, "[]")

        with patch("darnit.core.utils.subprocess.run", side_effect=_run):
            utils.gh_api_with_status("/repos/x/y/rulesets", paginate=True)
        assert captured["args"] == ["gh", "api", "--paginate", "/repos/x/y/rulesets"]

    def test_paginate_false_by_default(self):
        captured = {}

        def _run(args, capture_output=None, text=None):
            captured["args"] = args
            return _cp(0, "{}")

        with patch("darnit.core.utils.subprocess.run", side_effect=_run):
            utils.gh_api_with_status("/x")
        assert "--paginate" not in captured["args"]

    def test_gh_not_found(self):
        with patch("darnit.core.utils.subprocess.run", side_effect=FileNotFoundError()):
            body, status, err = utils.gh_api_with_status("/x")
        assert body is None
        assert status == 0
        assert "gh) not found" in err

    def test_json_decode_error_on_2xx(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(0, "not json")):
            body, status, err = utils.gh_api_with_status("/x")
        assert body is None
        assert status == 0
        assert "invalid JSON" in err


class TestWrapperContracts:
    def test_gh_api_returns_dict(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(0, '{"a":1}')):
            assert utils.gh_api("/x") == {"a": 1}

    def test_gh_api_raises_on_non_200(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", "HTTP 404: Not Found")):
            with pytest.raises(RuntimeError, match="404"):
                utils.gh_api("/x")

    def test_gh_api_raises_on_non_dict_body(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(0, "[1,2]")):
            with pytest.raises(RuntimeError, match="expected dict"):
                utils.gh_api("/x")

    def test_gh_api_safe_returns_dict(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(0, '{"a":1}')):
            assert utils.gh_api_safe("/x") == {"a": 1}

    def test_gh_api_safe_returns_none_on_failure(self):
        with patch("darnit.core.utils.subprocess.run", return_value=_cp(1, "", "HTTP 404: Not Found")):
            assert utils.gh_api_safe("/x") is None
