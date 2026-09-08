"""Feature 036: environmental-failure classification at each producer site.

Covers the decision tables in contracts/error-class.md sections 2.1-2.4
plus the two HandlerResult validation rules from section 6.

The load-bearing distinction throughout: a check that RAN and found the
repository non-compliant carries NO error_class. Only a check that could
not run to completion does. Tests assert both directions -- it is as
important that a clean FAIL stays unannotated as it is that a timeout
gets annotated.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from darnit.core.error_class import ERROR_CLASSES
from darnit.sieve.builtin_handlers import exec_handler
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)


def _ctx(local_path: Path) -> HandlerContext:
    return HandlerContext(
        local_path=str(local_path),
        owner="test-owner",
        repo="test-repo",
        default_branch="main",
        control_id="TEST-01.01",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results={},
    )


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestHandlerResultValidation:
    """Contract section 6: two invariants, both enforced in __post_init__."""

    @pytest.mark.unit
    def test_pass_with_error_class_is_rejected(self) -> None:
        """Rule 2: a handler that could not complete cannot produce a PASS."""
        with pytest.raises(ValueError, match="incompatible with status=PASS"):
            HandlerResult(
                status=HandlerResultStatus.PASS,
                message="ok",
                error_class="crashed",
            )

    @pytest.mark.unit
    def test_unknown_error_class_is_rejected(self) -> None:
        """Rule 1 (FR-002a): the frozenset guard, not the Literal, enforces this.

        A bare `Literal` annotation is erased at runtime and would accept
        this silently, letting an uninterpretable failure cause reach a
        report and an attestation.
        """
        with pytest.raises(ValueError, match="not a known ErrorClass"):
            HandlerResult(
                status=HandlerResultStatus.ERROR,
                message="boom",
                error_class="bogus_value",
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("value", sorted(ERROR_CLASSES))
    def test_each_valid_value_constructs(self, value: str) -> None:
        result = HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="boom",
            error_class=value,  # type: ignore[arg-type]
        )
        assert result.error_class == value

    @pytest.mark.unit
    def test_none_is_always_allowed_including_on_pass(self) -> None:
        result = HandlerResult(status=HandlerResultStatus.PASS, message="ok")
        assert result.error_class is None


class TestExecHandlerClassification:
    """Contract section 2.1: exec decision table, checked in order."""

    @pytest.mark.unit
    def test_timeout_classifies_as_timeout(self, tmp_path: Path) -> None:
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=30),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["gh", "api", "/repos/x/y"], "timeout": 30},
                _ctx(tmp_path),
            )
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "timeout"

    @pytest.mark.unit
    def test_missing_binary_classifies_as_not_found(self, tmp_path: Path) -> None:
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            side_effect=FileNotFoundError("no such file"),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["definitely-not-a-real-binary"]},
                _ctx(tmp_path),
            )
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "not_found"

    @pytest.mark.unit
    def test_rate_limit_stderr_classifies_as_rate_limit(self, tmp_path: Path) -> None:
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(1, stderr="gh: API rate limit exceeded for user ID 1234."),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["gh", "api", "/repos/x/y"]},
                _ctx(tmp_path),
            )
        assert result.error_class == "rate_limit"

    @pytest.mark.unit
    def test_secondary_rate_limit_classifies_as_rate_limit(self, tmp_path: Path) -> None:
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(1, stderr="You have exceeded a secondary rate limit."),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["gh", "api", "/repos/x/y"]},
                _ctx(tmp_path),
            )
        assert result.error_class == "rate_limit"

    @pytest.mark.unit
    def test_auth_stderr_classifies_as_auth(self, tmp_path: Path) -> None:
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(1, stderr="gh: Bad credentials (HTTP 401)"),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["gh", "api", "/repos/x/y"]},
                _ctx(tmp_path),
            )
        assert result.error_class == "auth"

    @pytest.mark.unit
    def test_rate_limit_wins_over_auth_when_both_could_match(
        self, tmp_path: Path
    ) -> None:
        """GitHub returns 403 for both; the rate-limit signal is more specific.

        Contract section 2.1 mandates rate-limit patterns are checked FIRST
        so a 403-plus-rate-limit body does not misclassify as auth.
        """
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(
                1,
                stderr="gh: HTTP 403: You have exceeded a secondary rate limit.",
            ),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["gh", "api", "/repos/x/y"]},
                _ctx(tmp_path),
            )
        assert result.error_class == "rate_limit"

    @pytest.mark.unit
    def test_unmatched_stderr_falls_back_to_network(self, tmp_path: Path) -> None:
        """FR-005a: non-GitHub / unrecognized failure is the network bucket."""
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(128, stderr="fatal: not a git repository"),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["git", "rev-parse", "HEAD"]},
                _ctx(tmp_path),
            )
        assert result.error_class == "network"

    @pytest.mark.unit
    def test_success_carries_no_error_class(self, tmp_path: Path) -> None:
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(0, stdout="all good"),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["true"]}, _ctx(tmp_path)
            )
        assert result.status == HandlerResultStatus.PASS
        assert result.error_class is None

    @pytest.mark.unit
    def test_clean_definitive_failure_carries_no_error_class(
        self, tmp_path: Path
    ) -> None:
        """The check RAN and the repo does not comply. Not an environment problem.

        This is the assertion that keeps the feature honest -- if declared
        fail_exit_codes started producing an error_class, every real finding
        would look like an infrastructure blip.
        """
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(1, stdout="", stderr="policy not satisfied"),
        ):
            result = exec_handler(
                {
                    "handler": "exec",
                    "command": ["some-checker"],
                    "pass_exit_codes": [0],
                    "fail_exit_codes": [1],
                },
                _ctx(tmp_path),
            )
        assert result.status == HandlerResultStatus.FAIL
        assert result.error_class is None


class TestExecHandlerWarnLogging:
    """Contract section 7: environmental failures log at WARN, not DEBUG."""

    @pytest.mark.unit
    def test_timeout_logs_warn_naming_control_and_error_class(
        self, tmp_path: Path, caplog
    ) -> None:
        with caplog.at_level(logging.WARNING):
            with patch(
                "darnit.sieve.builtin_handlers.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=30),
            ):
                exec_handler(
                    {"handler": "exec", "command": ["gh", "api", "/x"], "timeout": 30},
                    _ctx(tmp_path),
                )

        warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warns, "environmental failure must log at WARN, not DEBUG"
        joined = " ".join(r.getMessage() for r in warns)
        assert "TEST-01.01" in joined, "log must name the control"
        assert "timeout" in joined, "log must name the error_class"

    @pytest.mark.unit
    def test_clean_failure_does_not_log_warn(self, tmp_path: Path, caplog) -> None:
        """Happy-path / real-finding paths stay quiet at WARN."""
        with caplog.at_level(logging.WARNING):
            with patch(
                "darnit.sieve.builtin_handlers.subprocess.run",
                return_value=_proc(1, stderr="policy not satisfied"),
            ):
                exec_handler(
                    {
                        "handler": "exec",
                        "command": ["some-checker"],
                        "pass_exit_codes": [0],
                        "fail_exit_codes": [1],
                    },
                    _ctx(tmp_path),
                )

        assert [
            r for r in caplog.records if r.levelno >= logging.WARNING
        ] == [], "a clean definitive failure must not produce a WARN"


class TestDriverLevelErrorClassSurfacing:
    """SC-001: the operator can triage from the markdown report alone."""

    @pytest.mark.unit
    def test_markdown_annotates_env_failure_and_leaves_real_finding_bare(
        self,
    ) -> None:
        """The whole point of the feature, end to end at the formatter.

        Two controls with identical FAIL status: one could not reach the
        GitHub API (auth), one ran cleanly and found the repo
        non-compliant. The report must make them distinguishable.
        """
        from darnit.tools.audit import format_results_markdown

        results = [
            {
                "id": "OSPS-LE-02.02",
                "status": "FAIL",
                "details": "Command exited with unexpected code 1",
                "level": 1,
                "error_class": "auth",
            },
            {
                "id": "OSPS-QA-04.01",
                "status": "FAIL",
                "details": "Pattern not found in any file",
                "level": 1,
            },
        ]
        md = format_results_markdown(
            owner="o",
            repo="r",
            results=results,
            summary={"PASS": 0, "FAIL": 2, "WARN": 0, "N/A": 0, "ERROR": 0, "total": 2},
            compliance={1: False},
            level=1,
        )

        env_line = next(l for l in md.splitlines() if "OSPS-LE-02.02" in l)
        real_line = next(l for l in md.splitlines() if "OSPS-QA-04.01" in l)

        assert "auth" in env_line, (
            "the environmental failure must be annotated with its error_class"
        )
        assert "[" in env_line and "]" in env_line, (
            "annotation should be visually distinct from the message text"
        )
        assert "auth" not in real_line and "[" not in real_line.split("):")[0], (
            "a genuine finding must NOT be annotated -- otherwise every real "
            "failure reads as an infrastructure blip"
        )
