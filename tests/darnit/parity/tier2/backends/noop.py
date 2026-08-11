"""Test-only NoopBackend (feature 029 T006).

Used by SC-005 (Protocol conformance) and SC-007 (extensibility). NOT
registered in `BACKEND_REGISTRY` by default; tests inject it explicitly
via `run(backends={"noop": NoopBackend})`.

NOT shipped as a "how to write a backend" template -- a real backend
author reads `contracts/skill-invocation-backend-protocol.md` instead.
"""

from __future__ import annotations

from pathlib import Path

from tests.darnit.parity.tier2.backends.base import SkillInvocationResult


class NoopBackend:
    """No-op backend returning a canned Markdown summary. Zero API calls."""

    name = "noop"

    @classmethod
    def check_env(cls) -> None:
        # No credentials required.
        return None

    async def invoke(
        self,
        fixture_dir: Path,
        model: str,
        max_turns: int,
    ) -> SkillInvocationResult:
        return SkillInvocationResult(
            final_message="# noop backend\n\nPassed: 0\nFailed: 0",
            model=model,
            turn_count=0,
            metadata={"backend": "noop", "fixture_dir": str(fixture_dir)},
        )


__all__ = ("NoopBackend",)
