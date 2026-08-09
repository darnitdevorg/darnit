"""Tests for InteractiveTerminalResolver (feature 027 T012).

Covers contract IR-1..IR-31 from contracts/interactive-resolver-behavior.md.

Streams are injected via `input_stream` / `output_stream` constructor args so
tests don't touch /dev/tty. IR-6 is verified by mocking `open` at module level.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest

from darnit.harness.driver import HarnessSetupError
from darnit.harness.interactive_resolver import InteractiveTerminalResolver
from darnit.harness.question_resolvers import Answer, InteractiveAborted


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Question:
    def __init__(
        self,
        control_id: str = "OSPS-GV-01.01",
        question: str = "Who is the security contact?",
        help_md: str = "",
    ) -> None:
        self.control_id = control_id
        self.question = question
        self.help_md = help_md


class TestIR1Name:
    def test_name_is_interactive_terminal(self) -> None:
        assert InteractiveTerminalResolver.name == "interactive_terminal"
        assert InteractiveTerminalResolver().name == "interactive_terminal"


class TestIR4And5StreamsIsolatedFromStdoutStderr:
    def test_prompt_lands_only_on_injected_output_stream(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """IR-4 + IR-5: prompt goes to injected stream, NOT stdout/stderr."""
        in_stream = io.StringIO("security@example.com\n")
        out_stream = io.StringIO()
        r = InteractiveTerminalResolver(
            input_stream=in_stream, output_stream=out_stream,
        )
        _run(r.resolve(_Question(), position=1, total=1))
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert "Who is the security contact?" in out_stream.getvalue()


class TestIR6FailsFastWhenTtyUnavailable:
    def test_open_devtty_failure_raises_setup_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """IR-6: /dev/tty unavailable -> HarnessSetupError."""
        import builtins

        real_open = builtins.open

        def _fail_open(path: Any, *args: Any, **kwargs: Any) -> Any:
            if path == "/dev/tty":
                raise OSError("no tty in test env")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _fail_open)
        r = InteractiveTerminalResolver()
        with pytest.raises(HarnessSetupError, match="/dev/tty not openable"):
            _run(r.resolve(_Question()))


class TestIR10PromptFormat:
    def test_prompt_contains_position_control_id_question(self) -> None:
        """IR-10: position header, control_id, question text, chevron."""
        out_stream = io.StringIO()
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO("\n"), output_stream=out_stream,
        )
        _run(
            r.resolve(
                _Question(
                    control_id="OSPS-GV-01.01",
                    question="Who is the security contact?",
                    help_md="A person who handles vulnerability reports.",
                ),
                position=2,
                total=5,
            ),
        )
        prompt = out_stream.getvalue()
        assert "[2 of 5]" in prompt
        assert "OSPS-GV-01.01" in prompt
        assert "Who is the security contact?" in prompt
        assert "Help: A person who handles vulnerability reports." in prompt
        assert prompt.endswith("> ")

    def test_prompt_without_help_omits_help_line(self) -> None:
        out_stream = io.StringIO()
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO("\n"), output_stream=out_stream,
        )
        _run(r.resolve(_Question(help_md=""), position=1, total=1))
        assert "Help:" not in out_stream.getvalue()


class TestIR11PromptDoesNotLeakSecrets:
    def test_prompt_does_not_contain_api_key(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """IR-11: ANTHROPIC_API_KEY must never appear in the prompt payload."""
        secret = "sk-ant-DISTINCTIVE-XYZ-9zz"
        monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
        out_stream = io.StringIO()
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO("\n"), output_stream=out_stream,
        )
        _run(r.resolve(_Question(), position=1, total=1))
        assert secret not in out_stream.getvalue()


class TestIR13Through16InputHandling:
    def test_typed_answer_returns_answer(self) -> None:
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO("security@example.com\n"),
            output_stream=io.StringIO(),
        )
        result = _run(r.resolve(_Question()))
        assert isinstance(result, Answer)
        assert result.value == "security@example.com"
        assert result.origin == "interactive_terminal"
        assert result.authority == "asserted"

    def test_empty_input_returns_none(self) -> None:
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO("\n"),
            output_stream=io.StringIO(),
        )
        result = _run(r.resolve(_Question()))
        assert result is None

    def test_whitespace_only_input_returns_none(self) -> None:
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO("   \t  \n"),
            output_stream=io.StringIO(),
        )
        result = _run(r.resolve(_Question()))
        assert result is None

    def test_leading_trailing_whitespace_stripped(self) -> None:
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO("   value-with-spaces   \n"),
            output_stream=io.StringIO(),
        )
        result = _run(r.resolve(_Question()))
        assert result is not None
        assert result.value == "value-with-spaces"


class TestIR17And18InterruptHandling:
    def test_keyboard_interrupt_raises_interactive_aborted(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """IR-17: readline() KeyboardInterrupt -> InteractiveAborted."""

        class _InterruptingStream:
            def readline(self) -> str:
                raise KeyboardInterrupt

        r = InteractiveTerminalResolver(
            input_stream=_InterruptingStream(),
            output_stream=io.StringIO(),
        )
        with pytest.raises(InteractiveAborted):
            _run(r.resolve(_Question()))

    def test_eof_raises_interactive_aborted(self) -> None:
        """IR-18: readline() returns empty (EOF/Ctrl+D) -> InteractiveAborted."""
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO(""),  # empty, immediate EOF
            output_stream=io.StringIO(),
        )
        with pytest.raises(InteractiveAborted):
            _run(r.resolve(_Question()))


class TestIR22CloseLifecycle:
    def test_close_is_idempotent(self) -> None:
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )
        r.close()
        r.close()  # second call is a no-op

    def test_resolve_after_close_raises(self) -> None:
        r = InteractiveTerminalResolver(
            input_stream=io.StringIO("v\n"),
            output_stream=io.StringIO(),
        )
        r.close()
        with pytest.raises(RuntimeError, match="closed"):
            _run(r.resolve(_Question()))
