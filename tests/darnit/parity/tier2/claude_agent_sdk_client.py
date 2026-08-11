"""Backwards-compat shim (feature 029 T005).

Superseded by `tests/darnit/parity/tier2/backends/claude_agent_sdk.py`.
Kept as an import path for one release cycle so existing feature-028 tests
continue to work without an update.

Do NOT add new callers to this module. Direct new code at
`tests.darnit.parity.tier2.backends.claude_agent_sdk.ClaudeAgentSdkBackend`.
"""

from __future__ import annotations

from pathlib import Path

from tests.darnit.parity.tier2.backends.base import (
    SetupError,
    SkillInvocationResult,
)
from tests.darnit.parity.tier2.backends.claude_agent_sdk import (
    PROMPT_SNAPSHOT_PATH,
    ClaudeAgentSdkBackend,
)


async def invoke_skill(
    fixture_dir: Path,
    model: str = "anthropic:claude-sonnet-5",
    max_turns: int = 20,
) -> SkillInvocationResult:
    """Deprecated: use `ClaudeAgentSdkBackend().invoke()` directly.

    Preserves feature 028's fail-fast semantics: check env before invoking.
    The new Backend Protocol splits check_env and invoke into separate
    calls (so the runner can fail fast without constructing a backend).
    This shim reunites them to keep feature 028 tests green.
    """
    ClaudeAgentSdkBackend.check_env()
    return await ClaudeAgentSdkBackend().invoke(fixture_dir, model, max_turns)


__all__ = (
    "SetupError",
    "SkillInvocationResult",
    "invoke_skill",
    "PROMPT_SNAPSHOT_PATH",
    "ClaudeAgentSdkBackend",
)
