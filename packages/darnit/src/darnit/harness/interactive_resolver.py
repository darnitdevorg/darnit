"""InteractiveTerminalResolver: the reference QuestionResolver (feature 027 T008).

Prompts on `/dev/tty` -- the private operator channel used by git, ssh, sudo.
Isolated from stdout (report body) and stderr (progress + exit summary), so
feature 026's stream contracts stay intact even when a user runs the harness
interactively.

Contract:
  - contracts/interactive-resolver-behavior.md (IR-1..IR-31)
  - contracts/question-resolver-protocol.md (QR-*)

Design notes:
  - Stream injection: tests pass `io.StringIO` for both streams; production
    uses `/dev/tty`. The two-argument constructor exists exclusively for tests.
  - Lazy /dev/tty open: on first `resolve()`, not on `__init__`.
  - Empty / whitespace-only input -> None (skip).
  - Ctrl+C (KeyboardInterrupt) or EOF (empty readline) -> InteractiveAborted.

See specs/027-interactive-resolvers/plan.md + research.md R3.
"""

from __future__ import annotations

import asyncio
from typing import Any, TextIO

from darnit.harness.question_resolvers import (
    Answer,
    InteractiveAborted,
    QuestionResolver,
)


class InteractiveTerminalResolver:
    """Reference implementation of `QuestionResolver`. Prompts on `/dev/tty`."""

    name = "interactive_terminal"

    def __init__(
        self,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        # Both streams None => open /dev/tty lazily on first resolve().
        # Either non-None => tests / library callers supplied a channel.
        self._input_stream = input_stream
        self._output_stream = output_stream
        self._tty: TextIO | None = None
        self._closed = False

    def _ensure_streams(self) -> tuple[TextIO, TextIO]:
        """Return (input, output) streams; open /dev/tty on demand.

        Per contract IR-23: /dev/tty is NOT opened when EITHER argument
        is non-None. Per IR-25, partial injection is not supported --
        callers who wire only one side silently lost the other before
        PR #367 review fixed it; that now raises a programming error.
        """
        if (self._input_stream is None) != (self._output_stream is None):
            raise ValueError(
                "InteractiveTerminalResolver requires both input_stream and "
                "output_stream, or neither. Providing only one is a "
                "programming error (contract IR-25).",
            )
        if self._input_stream is not None and self._output_stream is not None:
            return self._input_stream, self._output_stream

        if self._tty is None:
            # Import here so a HarnessSetupError from darnit.harness.driver
            # doesn't create an import-cycle at module load time.
            from darnit.harness.driver import HarnessSetupError

            try:
                self._tty = open("/dev/tty", "r+", buffering=1)  # noqa: SIM115
            except OSError as exc:
                raise HarnessSetupError(
                    "interactive channel unavailable (/dev/tty not openable): "
                    f"{exc.strerror or type(exc).__name__}",
                ) from exc

        return self._tty, self._tty

    def _format_prompt(
        self,
        question: Any,
        position: int,
        total: int,
    ) -> str:
        """Produce the prompt payload written to /dev/tty (IR-10).

        Order: blank line, `[N of M]`, control_id, question text, optional
        Help block, `> ` chevron with no trailing newline.
        """
        control_id = getattr(question, "control_id", None) or (
            question.get("control_id", "") if isinstance(question, dict) else ""
        )
        question_text = getattr(question, "question", None) or (
            question.get("question", "") if isinstance(question, dict) else ""
        )
        help_text = getattr(question, "help_md", None) or (
            question.get("help_md", "") if isinstance(question, dict) else ""
        )

        lines: list[str] = []
        lines.append("")  # blank separator
        lines.append(f"[{position} of {total}]")
        lines.append(str(control_id))
        lines.append(str(question_text))
        if help_text:
            lines.append(f"  Help: {help_text}")
        # Final line: chevron without newline (input appears inline).
        return "\n".join(lines) + "\n> "

    async def resolve(
        self,
        question: Any,
        *,
        position: int = 1,
        total: int = 1,
    ) -> Answer | None:
        """Prompt the operator for one question. Return Answer or None (skip).

        Raises InteractiveAborted on Ctrl+C or EOF.
        """
        if self._closed:
            raise RuntimeError("resolver is closed")

        in_stream, out_stream = self._ensure_streams()

        prompt = self._format_prompt(question, position=position, total=total)
        out_stream.write(prompt)
        out_stream.flush()

        # PR #367 review blocker fix: readline() is blocking and, when
        # called directly in an async def, freezes the event loop -- so
        # the driver's `asyncio.wait_for(coro, per_resolver_timeout_s)`
        # never fires and operator think-time can't be preempted. Wrap
        # the blocking call in `asyncio.to_thread` so the event loop
        # keeps running and the driver's timeout is honored.
        try:
            raw = await asyncio.to_thread(in_stream.readline)
        except KeyboardInterrupt as exc:
            raise InteractiveAborted("operator sent SIGINT during prompt") from exc

        # EOF (Ctrl+D or piped-stdin exhausted).
        if raw == "":
            raise InteractiveAborted("EOF at interactive prompt")

        stripped = raw.rstrip("\n").strip()
        if not stripped:
            return None  # skip

        return Answer(value=stripped, origin=self.name)

    def close(self) -> None:
        """Release /dev/tty. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._tty is not None:
            try:
                self._tty.close()
            except OSError:
                pass
            self._tty = None


def build() -> QuestionResolver:
    """Entry-point factory for `darnit.question_resolvers = interactive_terminal`."""
    return InteractiveTerminalResolver()


__all__ = ("InteractiveTerminalResolver", "build")
