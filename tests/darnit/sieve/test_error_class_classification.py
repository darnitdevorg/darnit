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
    def test_unexpected_exit_is_a_known_class(self) -> None:
        """#562: the Literal and the frozenset are edited together."""
        from typing import get_args

        from darnit.core.error_class import ErrorClass

        assert "unexpected_exit" in ERROR_CLASSES
        assert "unexpected_exit" in get_args(ErrorClass)
        assert set(get_args(ErrorClass)) == set(ERROR_CLASSES)

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
    def test_missing_binary_classifies_as_missing_tool(self, tmp_path: Path) -> None:
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            side_effect=FileNotFoundError("no such file"),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["definitely-not-a-real-binary"]},
                _ctx(tmp_path),
            )
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "missing_tool"

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
    def test_unmatched_stderr_is_unexpected_exit_not_network(self, tmp_path: Path) -> None:
        """#562: an unrecognized failure no longer claims a network cause."""
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(128, stderr="fatal: not a git repository"),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["git", "rev-parse", "HEAD"]},
                _ctx(tmp_path),
            )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.error_class == "unexpected_exit"

    @pytest.mark.unit
    def test_unexpected_exit_message_names_command_code_and_stderr(self, tmp_path: Path) -> None:
        """#562: the cause is actionable without rerunning the command."""
        stderr = "grep: .github/workflows/: No such file or directory\n" + "x" * 500 + "\u2603"
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(2, stderr=stderr),
        ):
            result = exec_handler(
                {"handler": "exec", "command": ["grep", "-r", "uses:", ".github/workflows/"]},
                _ctx(tmp_path),
            )
        assert result.error_class == "unexpected_exit"
        assert "grep -r uses: .github/workflows/" in result.message
        assert "code 2" in result.message
        assert "grep: .github/workflows/: No such file or directory x" in result.message
        assert "\n" not in result.message
        assert result.message.isascii()
        assert "x" * 300 not in result.message

    @pytest.mark.unit
    def test_unexpected_exit_with_empty_stderr_says_so(self, tmp_path: Path) -> None:
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(3),
        ):
            result = exec_handler({"handler": "exec", "command": ["some-checker"]}, _ctx(tmp_path))
        assert result.error_class == "unexpected_exit"
        assert "code 3" in result.message
        assert "some-checker" in result.message
        assert "no stderr" in result.message

    @pytest.mark.unit
    def test_exit_127_is_missing_tool(self, tmp_path: Path) -> None:
        """#562: a shell or env wrapper reports a missing binary as exit 127."""
        with patch(
            "darnit.sieve.builtin_handlers.subprocess.run",
            return_value=_proc(127, stderr="env: 'scorecard': No such file or directory"),
        ):
            result = exec_handler({"handler": "exec", "command": ["env", "scorecard"]}, _ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.error_class == "missing_tool"

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


class TestClassifyExecFailure:
    """#562: the undeclared-exit decision table, first match wins."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("stderr", "exit_code", "expected"),
        [
            ("gh: API rate limit exceeded for user ID 1234.", 1, "rate_limit"),
            ("You have exceeded a secondary rate limit.", 1, "rate_limit"),
            ("gh: HTTP 403: You have exceeded a secondary rate limit.", 1, "rate_limit"),
            ("gh: Bad credentials (HTTP 401)", 1, "auth"),
            ("To get started with GitHub CLI, please run:  gh auth login", 4, "auth"),
            ("You are not logged into any GitHub hosts.", 4, "auth"),
            ("", 127, "missing_tool"),
            ("bash: scorecard: command not found", 1, "missing_tool"),
            ("sh: 1: scorecard: not found", 2, "missing_tool"),
            ("fatal: unable to access 'https://github.com/o/r/': Could not resolve host: github.com", 128, "network"),
            ("curl: (6) Could not resolve host: example.com", 6, "network"),
            ("ssh: Could not resolve hostname github.com: Name or service not known", 255, "network"),
            ("ssh: github.com: Temporary failure in name resolution", 255, "network"),
            (
                "ssh: Could not resolve hostname github.com: nodename nor servname provided, or not known",
                255,
                "network",
            ),
            ("dial tcp: lookup api.github.com: no such host", 1, "network"),
            ("curl: (7) Failed to connect to localhost port 1: Connection refused", 7, "network"),
            ("fetch-pack: unexpected disconnect: Connection reset by peer", 128, "network"),
            ("connect: Network is unreachable", 1, "network"),
            ("ssh: connect to host github.com port 22: No route to host", 255, "network"),
            ("ssh: connect to host github.com port 22: Connection timed out", 255, "network"),
            ("curl: (28) Failed to connect to example.com port 443: Operation timed out", 28, "network"),
            ("dial tcp 140.82.112.6:443: i/o timeout", 1, "network"),
            ("error connecting to api.github.com", 1, "network"),
            ("curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to example.com:443", 35, "network"),
            ("net/http: TLS handshake timeout", 1, "network"),
            ("SSL certificate problem: unable to get local issuer certificate", 60, "network"),
            ("x509: certificate signed by unknown authority", 1, "network"),
            ("server certificate verification failed. CAfile: none CRLfile: none", 128, "network"),
            ("error: RPC failed; curl 56 OpenSSL SSL_read: Connection was reset, errno 10054", 128, "network"),
            ("fatal: unable to access 'https://example.com/r/': gnutls_handshake() failed", 128, "network"),
            (
                "fatal: unable to access 'https://example.com/r/': The requested URL returned error: 404",
                128,
                "unexpected_exit",
            ),
            ("grep: .github/workflows/: No such file or directory", 2, "unexpected_exit"),
            ("fatal: not a git repository (or any of the parent directories): .git", 128, "unexpected_exit"),
            ("error: No such remote 'upstream'", 2, "unexpected_exit"),
            ("gh: Not Found (HTTP 404)", 1, "unexpected_exit"),
            ("", 1, "unexpected_exit"),
            ("", None, "unexpected_exit"),
        ],
    )
    def test_table(self, stderr: str, exit_code: int | None, expected: str) -> None:
        from darnit.sieve.builtin_handlers import _classify_exec_failure

        assert _classify_exec_failure(stderr, exit_code, "scorecard") == expected

    @pytest.mark.unit
    def test_not_found_names_only_the_executable(self) -> None:
        """A bare "not found" about some other thing is not a missing tool."""
        from darnit.sieve.builtin_handlers import _classify_exec_failure

        assert _classify_exec_failure("gh: Not Found (HTTP 404)", 1, "gh") == "unexpected_exit"
        assert _classify_exec_failure("sh: 1: gh: not found", 1, "/usr/bin/gh") == "missing_tool"


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

        lines = md.splitlines()
        env_line = next(ln for ln in lines if "OSPS-LE-02.02" in ln)
        real_line = next(ln for ln in lines if "OSPS-QA-04.01" in ln)

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


class TestAutoDetectGitFailureLogging:
    """Contract section 2.4: git failures log; a missing remote does not."""

    @pytest.mark.unit
    def test_git_timeout_warns(self, tmp_path: Path, caplog) -> None:
        from darnit.context.auto_detect import _get_remote_url

        with caplog.at_level(logging.WARNING):
            with patch(
                "darnit.context.auto_detect.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=5),
            ):
                assert _get_remote_url("origin", str(tmp_path)) is None

        joined = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "timeout" in joined
        assert "origin" in joined

    @pytest.mark.unit
    def test_missing_git_binary_warns_not_found(self, tmp_path: Path, caplog) -> None:
        from darnit.context.auto_detect import _get_remote_url

        with caplog.at_level(logging.WARNING):
            with patch(
                "darnit.context.auto_detect.subprocess.run",
                side_effect=FileNotFoundError("git"),
            ):
                assert _get_remote_url("origin", str(tmp_path)) is None

        joined = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "not_found" in joined

    @pytest.mark.unit
    def test_absent_remote_does_not_warn(self, tmp_path: Path, caplog) -> None:
        """git answering "no such remote" is a legitimate answer, not a failure.

        Warning here would make every single-remote repo noisy, which is how
        loud logging becomes ignored logging.
        """
        with caplog.at_level(logging.WARNING):
            with patch(
                "darnit.context.auto_detect.subprocess.run",
                return_value=_proc(2, stderr="error: No such remote 'upstream'"),
            ):
                from darnit.context.auto_detect import _get_remote_url

                assert _get_remote_url("upstream", str(tmp_path)) is None

        assert [
            r for r in caplog.records if r.levelno >= logging.WARNING
        ] == [], "an absent remote must not produce a WARN"


class TestMcpHandlerClassification:
    """Contract section 2.2: all McpPoolError subclasses are classified.

    The pool arrives via ``HandlerContext.mcp_pool``, so the test injects a
    raising stub there rather than patching a module function.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("exc_name", "expected"),
        [
            ("McpToolTimeout", "timeout"),
            ("McpServerHandshakeFailed", "network"),
            ("McpServerBinaryMissing", "missing_tool"),
            ("McpServerVerificationFailed", "auth"),
            ("McpServerUnusable", "network"),
            ("McpToolError", "crashed"),
            ("McpToolResponseNotJson", "crashed"),
        ],
    )
    def test_each_mcp_exception_maps_to_its_error_class(
        self, exc_name: str, expected: str, tmp_path: Path, caplog
    ) -> None:
        """FR-006's three named types plus the five it delegates to the contract."""
        from darnit.sieve import mcp_pool as mcp_pool_mod
        from darnit.sieve.builtin_handlers import mcp_handler

        exc_cls = getattr(mcp_pool_mod, exc_name)
        fake_pool = MagicMock()
        fake_pool.call_tool.side_effect = exc_cls("simulated failure")
        fake_pool._sessions = {}

        ctx = _ctx(tmp_path)
        ctx.mcp_pool = fake_pool

        with caplog.at_level(logging.WARNING):
            result = mcp_handler(
                {
                    "handler": "mcp",
                    "server": "test-server",
                    "tool": "test-tool",
                    "args": {},
                },
                ctx,
            )

        assert result.error_class == expected, (
            f"{exc_name} should classify as {expected}, got {result.error_class!r}"
        )
        joined = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert expected in joined, f"{exc_name} must log its error_class at WARN"


class TestOrchestratorCrashClassification:
    """Contract section 2.3: a raising handler is `crashed`, logged at WARN."""

    @pytest.mark.unit
    def test_raising_handler_yields_crashed_and_warns(self, caplog) -> None:
        from darnit.config.framework_schema import HandlerInvocation
        from darnit.core.plugin import ControlSpec
        from darnit.sieve.handler_registry import get_sieve_handler_registry
        from darnit.sieve.models import CheckContext
        from darnit.sieve.orchestrator import SieveOrchestrator

        def boom(config, ctx):
            raise RuntimeError("simulated handler bug")

        registry = get_sieve_handler_registry()
        registry.register(
            "exploding_handler_036",
            "deterministic",
            boom,
            ceiling={"pass", "fail"},
        )

        control = ControlSpec(
            control_id="TEST-CRASH.01",
            name="Test crash",
            description="A handler that raises",
            level=1,
            domain="TEST",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="exploding_handler_036")
                ]
            },
        )
        context = CheckContext(
            owner="o",
            repo="r",
            local_path="/tmp/test",
            default_branch="main",
            control_id="TEST-CRASH.01",
            project_context={},
        )

        orch = SieveOrchestrator(stop_on_llm=True)
        with caplog.at_level(logging.WARNING):
            result = orch._dispatch_handler_invocations(control, context)

        assert result is not None
        assert result.status == "ERROR"
        assert result.error_class == "crashed", (
            "a handler that raised did not complete, so it is an "
            "environmental failure, not a verdict"
        )
        joined = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "TEST-CRASH.01" in joined, "log must name the control"
        assert "crashed" in joined, "log must name the error_class"
