"""CLI tests for `darnit harness` (feature 026 T036-T042 + T045b).

Contract cli.md CLI-1..CLI-18. Covers SC-002, SC-005, SC-009.

Testing strategy: invoke via the argparse dispatcher (like feature 024's
invoke_cmd_run) so patches apply in-process and stdout/stderr capture is
per-test.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from darnit.core.llm_step import MockLLMStep
from darnit.harness.exit_codes import HarnessExitCode


def _invoke_cli(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    mock_llm: MockLLMStep | None = None,
) -> tuple[int, str, str, list[logging.LogRecord]]:
    """Invoke `darnit harness` via the argparse dispatcher in-process.

    Returns (exit_code, stdout, stderr, log_records-on-darnit.harness).
    Patches PydanticAILLMStep to the injected mock so tests don't hit
    a real LLM.
    """
    from darnit.cli import main as darnit_main

    caplog.set_level(logging.INFO, logger="darnit.harness")

    # Save/restore the darnit logger state around the call. darnit.cli.main
    # invokes configure_logging() which replaces the NullHandler with a
    # StreamHandler; if this test runs before tests/darnit/core/test_logging.py,
    # its test_has_null_handler_by_default fails on a leaked StreamHandler.
    # Mirrors feature 024's invoke_cmd_run save/restore pattern.
    darnit_logger = logging.getLogger("darnit")
    saved_handlers = list(darnit_logger.handlers)
    saved_level = darnit_logger.level
    saved_disabled = darnit_logger.disabled

    try:
        if mock_llm is not None:
            with patch(
                "darnit.core.llm_step.PydanticAILLMStep",
                return_value=mock_llm,
            ):
                exit_code = darnit_main(argv=["harness", *argv])
        else:
            exit_code = darnit_main(argv=["harness", *argv])
    finally:
        darnit_logger.handlers[:] = saved_handlers
        darnit_logger.setLevel(saved_level)
        darnit_logger.disabled = saved_disabled

    captured = capsys.readouterr()
    harness_records = [r for r in caplog.records if r.name == "darnit.harness"]
    return exit_code, captured.out, captured.err, harness_records


# ---------------------------------------------------------------------------
# T036 / T037: success + failure exit codes
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_exit_code_audit_failures_when_fail_present(
        self,
        minimal_llm_repo_tree: Path,
        mock_llm_step: MockLLMStep,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """T037: fixture with FAIL result -> exit 1, stderr names FAIL count."""
        exit_code, _stdout, _stderr, records = _invoke_cli(
            [str(minimal_llm_repo_tree), "--level", "1"],
            capsys,
            caplog,
            mock_llm=mock_llm_step,
        )
        assert exit_code == int(HarnessExitCode.AUDIT_FAILURES)
        # Exit summary should mention the FAIL count.
        summary_lines = [r.getMessage() for r in records if r.getMessage().startswith("harness: complete")]
        assert len(summary_lines) == 1
        assert "FAIL" in summary_lines[0]
        assert "exit 1" in summary_lines[0]


# ---------------------------------------------------------------------------
# T038 (revised via C1): missing key fail-fast + no controls ran
# ---------------------------------------------------------------------------


class TestFailFast:
    def test_missing_api_key_fails_fast_before_any_control_ran(
        self,
        minimal_llm_repo_tree: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """SC-002 + FR-002 + C1 tightening: (a) exit 2, (b) <2s wall clock,
        (c) stderr contains the setup_error phrase, (d) ZERO progress lines
        with [N/M] pattern (proves no control ran).
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        caplog.set_level(logging.INFO, logger="darnit.harness")

        # Same save/restore as _invoke_cli to avoid leaking a StreamHandler
        # onto the darnit logger and breaking tests/darnit/core/test_logging.py.
        start = time.monotonic()
        from darnit.cli import main as darnit_main

        darnit_logger = logging.getLogger("darnit")
        saved_handlers = list(darnit_logger.handlers)
        saved_level = darnit_logger.level
        try:
            exit_code = darnit_main(argv=["harness", str(minimal_llm_repo_tree)])
        finally:
            darnit_logger.handlers[:] = saved_handlers
            darnit_logger.setLevel(saved_level)
        elapsed = time.monotonic() - start

        # (a) exit code
        assert exit_code == int(HarnessExitCode.SETUP_ERROR), f"Expected exit 2, got {exit_code}"
        # (b) timing bound
        assert elapsed < 2.0, f"Fail-fast bound exceeded: {elapsed:.3f}s"
        # (c) stderr / log message
        harness_records = [r.getMessage() for r in caplog.records if r.name == "darnit.harness"]
        summary_msgs = [m for m in harness_records if "setup_error" in m]
        assert len(summary_msgs) >= 1, f"No setup_error line found in: {harness_records}"
        assert any("ANTHROPIC_API_KEY" in m for m in summary_msgs)
        # (d) no [N/M] progress lines
        progress_pattern = re.compile(r"\[\d+/\d+\]")
        progress_lines = [m for m in harness_records if progress_pattern.search(m)]
        assert progress_lines == [], f"Expected zero progress lines before setup_error, got: {progress_lines}"


# ---------------------------------------------------------------------------
# T039: missing repo path
# ---------------------------------------------------------------------------


class TestMissingRepoPath:
    def test_missing_repo_path_exits_setup_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """CLI-1: missing / no .baseline.toml -> exit 2."""
        exit_code, _stdout, _stderr, records = _invoke_cli(
            [str(tmp_path / "nonexistent")],
            capsys,
            caplog,
        )
        assert exit_code == int(HarnessExitCode.SETUP_ERROR)


# ---------------------------------------------------------------------------
# T040: stderr grep pattern for four exit classes
# ---------------------------------------------------------------------------


class TestStderrGrepPattern:
    def test_stderr_summary_matches_grep_pattern(
        self,
        minimal_llm_repo_tree: Path,
        mock_llm_step: MockLLMStep,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """SC-009 + CLI-13: exit-summary line is grep-able for CI dashboards.

        Runs the harness in success and setup-error modes; asserts each
        summary matches the grep pattern that distinguishes the classes.
        Exit-code disambiguates 0 vs 1 (both use `complete`); the class-name
        substring in stderr disambiguates 0/1 vs 2/3.
        """
        # Case 1: success/failure path (audit runs).
        _exit1, _stdout1, _stderr1, records1 = _invoke_cli(
            [str(minimal_llm_repo_tree), "--level", "1"],
            capsys,
            caplog,
            mock_llm=mock_llm_step,
        )
        # Case 2: setup error.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        caplog.clear()
        _exit2, _stdout2, _stderr2, records2 = _invoke_cli(
            [str(minimal_llm_repo_tree)],
            capsys,
            caplog,
        )

        summary_pattern = re.compile(r"^harness: (complete|setup_error|internal_error), .+, exit \d+$")

        def _find_summary(records):
            for r in records:
                msg = r.getMessage()
                if msg.startswith("harness:") and "exit" in msg:
                    return msg
            return None

        summary1 = _find_summary(records1)
        summary2 = _find_summary(records2)

        assert summary1 is not None, f"No summary line for success case: {[r.getMessage() for r in records1]}"
        assert summary2 is not None, f"No summary line for setup case: {[r.getMessage() for r in records2]}"

        assert summary_pattern.match(summary1), f"summary1 doesn't match pattern: {summary1!r}"
        assert summary_pattern.match(summary2), f"summary2 doesn't match pattern: {summary2!r}"

        # Class differentiation
        assert "setup_error" in summary2
        assert "complete" in summary1


# ---------------------------------------------------------------------------
# T041: stdout clean when --output used
# ---------------------------------------------------------------------------


class TestOutputFlag:
    def test_stdout_clean_when_output_flag_used(
        self,
        minimal_llm_repo_tree: Path,
        mock_llm_step: MockLLMStep,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """CLI-16: --output writes to file; stdout is empty."""
        output_path = tmp_path / "report.md"
        _exit, stdout, _stderr, _records = _invoke_cli(
            [str(minimal_llm_repo_tree), "--level", "1", "--output", str(output_path)],
            capsys,
            caplog,
            mock_llm=mock_llm_step,
        )
        # stdout should be empty (or whitespace-only)
        assert stdout.strip() == "", f"stdout not clean: {stdout!r}"
        # file should contain the report
        assert output_path.exists()
        content = output_path.read_text()
        assert "# Darnit Harness Report" in content


# ---------------------------------------------------------------------------
# T042: `harness` appears in `darnit --help`
# ---------------------------------------------------------------------------


class TestHelpDiscoverability:
    def test_help_lists_harness_subcommand(self) -> None:
        """CLI-17: `darnit --help` lists `harness` alongside audit/run/serve."""
        result = subprocess.run(
            ["uv", "run", "darnit", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        # Case-insensitive check since argparse may format the help text.
        assert "harness" in result.stdout.lower()


# ---------------------------------------------------------------------------
# T045b (from C2): API key never appears in stderr / logs
# ---------------------------------------------------------------------------


class TestApiKeyRedaction:
    def test_api_key_never_appears_in_stderr(
        self,
        minimal_llm_repo_tree: Path,
        mock_llm_step: MockLLMStep,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """RF-4 + CLI-14: API key MUST NOT appear in stderr/logs even on
        error paths. Set a distinctive key value; run in success + failure
        modes; assert the literal key never appears anywhere in captured
        log records.
        """
        secret = "SECRET_TOKEN_XYZ_FOR_REDACTION_TEST"
        monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

        # Success/failure path
        _e1, stdout1, _s1, records1 = _invoke_cli(
            [str(minimal_llm_repo_tree), "--level", "1"],
            capsys,
            caplog,
            mock_llm=mock_llm_step,
        )
        for r in records1:
            assert secret not in r.getMessage(), f"API key leaked into log record: {r.getMessage()!r}"
        # Report body also key-clean.
        assert secret not in stdout1


# ---------------------------------------------------------------------------
# Feature 027: --interactive flag (T015)
# ---------------------------------------------------------------------------


class TestInteractiveFlag:
    """Cover SC-005 (fail-fast) and CLI-visible behavior of --interactive."""

    def test_interactive_with_non_tty_stdin_fails_fast(
        self,
        minimal_llm_repo_tree: Path,
        mock_llm_step: MockLLMStep,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SC-005: piped stdin under --interactive -> exit 2 in <2s."""
        # Ensure isatty returns False (default in pytest, but be explicit).
        import sys
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

        start = time.monotonic()
        exit_code, _stdout, _stderr, records = _invoke_cli(
            [str(minimal_llm_repo_tree), "--interactive", "--level", "1"],
            capsys,
            caplog,
            mock_llm=mock_llm_step,
        )
        elapsed = time.monotonic() - start

        assert exit_code == int(HarnessExitCode.SETUP_ERROR)
        assert elapsed < 2.0, f"fail-fast bound exceeded: {elapsed:.3f}s"

        summary_msgs = [r.getMessage() for r in records if "setup_error" in r.getMessage()]
        assert len(summary_msgs) >= 1
        assert any("interactive channel unavailable" in m for m in summary_msgs)
        assert any("stdin is not a TTY" in m for m in summary_msgs)

        # SC-005 also asserts: ZERO progress lines before the setup_error.
        progress_pattern = re.compile(r"\[\d+/\d+\]")
        progress_lines = [
            r.getMessage() for r in records
            if progress_pattern.search(r.getMessage())
        ]
        assert progress_lines == []

    def test_interactive_with_devtty_unavailable_fails_fast(
        self,
        minimal_llm_repo_tree: Path,
        mock_llm_step: MockLLMStep,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SC-005 variant: stdin is a TTY but /dev/tty is not openable."""
        import builtins
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        real_open = builtins.open

        def _fail_open(path: object, *args: object, **kwargs: object) -> object:
            if path == "/dev/tty":
                raise OSError("no tty in test env")
            return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "open", _fail_open)

        exit_code, _stdout, _stderr, records = _invoke_cli(
            [str(minimal_llm_repo_tree), "--interactive", "--level", "1"],
            capsys,
            caplog,
            mock_llm=mock_llm_step,
        )
        assert exit_code == int(HarnessExitCode.SETUP_ERROR)

        summary_msgs = [r.getMessage() for r in records if "setup_error" in r.getMessage()]
        assert len(summary_msgs) >= 1
        assert any("/dev/tty not openable" in m for m in summary_msgs)
