"""Thin wrapper around `claude_agent_sdk.query` for Tier 2 (T018).

Invokes the /darnit-audit skill against a fixture and returns the final
assistant message. Deterministic invocation: no streaming interrupts, no
interactive turns; explicit prompt + model + max_turns.

Per research.md R7:
  - Prompt content is loaded from skill_prompt_snapshot.md.
  - Model defaults to anthropic:claude-sonnet-5 (matches feature 025/026).
  - max_turns cap prevents runaway budget consumption.
  - ANTHROPIC_API_KEY MUST be set (FR-010); absence raises SetupError.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class SetupError(RuntimeError):
    """Raised when Tier 2 lacks the environment it needs to invoke the skill."""


@dataclass(frozen=True)
class SkillInvocationResult:
    """Return type for `invoke_skill`."""

    final_message: str
    model: str
    turn_count: int
    metadata: dict[str, object]


PROMPT_SNAPSHOT_PATH = Path(__file__).parent / "skill_prompt_snapshot.md"


def _load_skill_prompt() -> str:
    if not PROMPT_SNAPSHOT_PATH.exists():
        raise SetupError(
            f"skill prompt snapshot missing: {PROMPT_SNAPSHOT_PATH}. Run T022 to capture it before invoking Tier 2.",
        )
    return PROMPT_SNAPSHOT_PATH.read_text()


def _check_env() -> None:
    """FR-010: fail fast when ANTHROPIC_API_KEY is absent."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SetupError(
            "Tier 2 requires ANTHROPIC_API_KEY. Configure the "
            "`parity-tier2` GitHub Actions Environment (or export the var "
            "for a local run).",
        )


async def invoke_skill(
    fixture_dir: Path,
    model: str = "anthropic:claude-sonnet-5",
    max_turns: int = 20,
) -> SkillInvocationResult:
    """Invoke the /darnit-audit skill against `fixture_dir`.

    Returns a `SkillInvocationResult`. Raises SetupError on missing env
    (before any API call is made).
    """
    _check_env()
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
        model=model.replace("anthropic:", ""),  # SDK expects bare model name
        max_turns=max_turns,
        cwd=str(fixture_dir),
        mcp_servers={
            "darnit": {
                "type": "stdio",
                "command": "darnit",
                "args": ["serve", "--framework", "openssf-baseline"],
            },
        },
        # Restrict to the specific MCP tool the parity test needs. Any
        # off-list tool call is rejected by the SDK.
        allowed_tools=["mcp__darnit__audit_openssf_baseline"],
        # Auto-accept the tool call; parity CI is non-interactive.
        permission_mode="acceptEdits",
        # Isolate from the running host's Claude Code settings so a
        # local dev's project/user config can't influence the run.
        setting_sources=[],
    )

    final_text: str = ""
    turn_count = 0
    result_meta: dict[str, object] = {}

    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            turn_count += 1
            # Concatenate any text blocks from this assistant turn.
            for block in message.content:
                if isinstance(block, TextBlock):
                    final_text = block.text  # keep only the LAST turn's text
        elif isinstance(message, ResultMessage):
            # ResultMessage carries final metadata (usage, cost, etc.)
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
    "SetupError",
    "SkillInvocationResult",
    "invoke_skill",
    "PROMPT_SNAPSHOT_PATH",
)
