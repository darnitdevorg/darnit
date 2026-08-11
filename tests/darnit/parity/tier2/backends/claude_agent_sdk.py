"""Claude Agent SDK backend (feature 029 T004).

Refactored from feature 028's `claude_agent_sdk_client.py::invoke_skill`
into a class satisfying the `SkillInvocationBackend` Protocol. Body is the
feature 028 logic unchanged; only the shape (class vs free function) is
different.

The old import path (`tests.darnit.parity.tier2.claude_agent_sdk_client`)
continues to work via a shim module that re-exports names from here.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.darnit.parity.tier2.backends.base import (
    SetupError,
    SkillInvocationResult,
)

# The skill prompt snapshot lives ONE level up from this module (in
# tests/darnit/parity/tier2/, alongside claude_agent_sdk_client.py).
PROMPT_SNAPSHOT_PATH = Path(__file__).parent.parent / "skill_prompt_snapshot.md"


def _load_skill_prompt() -> str:
    if not PROMPT_SNAPSHOT_PATH.exists():
        raise SetupError(
            f"skill prompt snapshot missing: {PROMPT_SNAPSHOT_PATH}. Run T022 to capture it before invoking Tier 2.",
        )
    return PROMPT_SNAPSHOT_PATH.read_text()


class ClaudeAgentSdkBackend:
    """Feature 028's Claude Agent SDK client, wrapped as a Protocol-conforming
    class."""

    name = "claude_agent_sdk"

    @classmethod
    def check_env(cls) -> None:
        """FR-008: fail fast when ANTHROPIC_API_KEY is absent."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SetupError(
                "Tier 2 requires ANTHROPIC_API_KEY. Configure the "
                "`parity-tier2` GitHub Actions Environment (or export the "
                "var for a local run).",
            )

    async def invoke(
        self,
        fixture_dir: Path,
        model: str,
        max_turns: int,
    ) -> SkillInvocationResult:
        """Invoke the /darnit-audit skill against `fixture_dir`.

        Returns a `SkillInvocationResult`. The caller has already validated
        env via `check_env()`; this method assumes the SDK is importable
        and ANTHROPIC_API_KEY is set.
        """
        skill_prompt = _load_skill_prompt()

        # Import here so unit tests exercising the SetupError path don't
        # require the SDK to be importable.
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        user_prompt = (
            f"{skill_prompt}\n\n"
            f"Run the audit against the repository at {fixture_dir}. "
            f"Summarize the results per the skill's usual format."
        )

        # PR #370 review fix: wire the darnit MCP server, allow the audit
        # tool, and lock the agent down so it can't reach for out-of-band
        # settings. Previously ClaudeAgentOptions passed only model, cwd,
        # and max_turns -- the agent had NO way to call
        # audit_openssf_baseline and the parity test measured "skill does
        # nothing" instead of "skill vs tool".
        options = ClaudeAgentOptions(
            # SDK expects a bare model name.
            model=model.replace("anthropic:", ""),
            max_turns=max_turns,
            cwd=str(fixture_dir),
            mcp_servers={
                "darnit": {
                    "type": "stdio",
                    "command": "darnit",
                    "args": ["serve", "--framework", "openssf-baseline"],
                },
            },
            # Restrict to the specific MCP tool the parity test needs.
            allowed_tools=["mcp__darnit__audit_openssf_baseline"],
            # Auto-accept the tool call; parity CI is non-interactive.
            permission_mode="acceptEdits",
            # Isolate from the running host's Claude Code settings.
            setting_sources=[],
        )

        final_text: str = ""
        turn_count = 0
        result_meta: dict[str, object] = {}

        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn_count += 1
                for block in message.content:
                    if isinstance(block, TextBlock):
                        final_text = block.text  # keep only the LAST turn's text
            elif isinstance(message, ResultMessage):
                result_meta = {
                    "duration_ms": getattr(message, "duration_ms", None),
                    "num_turns": getattr(message, "num_turns", turn_count),
                }

        return SkillInvocationResult(
            final_message=final_text,
            model=model,
            turn_count=turn_count,
            metadata=result_meta,
        )


__all__ = (
    "ClaudeAgentSdkBackend",
    "PROMPT_SNAPSHOT_PATH",
)
