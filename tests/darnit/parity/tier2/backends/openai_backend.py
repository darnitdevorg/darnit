"""OpenAI Tier 2 backend (feature 029 T008 skeleton + T010 body).

Chat Completions API with a hand-rolled tool-call loop. Stateless per
invocation; the darnit MCP audit tool is registered as a function-callable
tool; the model is called with `temperature=0.0` for reproducibility.

See:
  - specs/029-openai-parity-adapter/data-model.md sections 6, 8
  - specs/029-openai-parity-adapter/research.md R3, R4
  - specs/029-openai-parity-adapter/contracts/skill-invocation-backend-protocol.md
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tests.darnit.parity.tier2.backends.base import (
    SetupError,
    SkillInvocationResult,
)
from tests.darnit.parity.tier2.backends.claude_agent_sdk import (
    PROMPT_SNAPSHOT_PATH,
)

# Data-model.md section 8 -- one tool schema for the audit function.
_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "audit_openssf_baseline",
            "description": (
                "Run darnit's OpenSSF Baseline audit on the repository at the "
                "given local_path. Returns a JSON string with per-control "
                "results including status, authority, and level."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "local_path": {
                        "type": "string",
                        "description": ("Absolute path to the repository being audited."),
                    },
                    "level": {
                        "type": "integer",
                        "enum": [1, 2, 3],
                        "default": 3,
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["markdown", "json"],
                        "default": "json",
                    },
                },
                "required": ["local_path"],
            },
        },
    },
]


def _dispatch_tool_call(call: Any, fixture_dir: Path) -> str:
    """Execute a tool call from the OpenAI response.

    Contract B-17: `local_path` is forced to `fixture_dir` even if the
    model's tool-call arguments named a different path -- prevents a
    rogue model from wandering outside the fixture.
    """
    if call.function.name == "audit_openssf_baseline":
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        # PR #371 review fix: pin level + output_format the same way
        # local_path is pinned. Previous `setdefault` let a rogue model
        # ask for `output_format="markdown"` and `level=1`, defeating
        # the comparison against the tool's JSON @ level 3.
        args["local_path"] = str(fixture_dir)
        args["output_format"] = "json"
        args["level"] = 3
        # Force safe defaults.
        args["auto_init_config"] = False
        args["attest"] = False
        args["prefer_upstream"] = False

        # Local import so unit tests exercising the SetupError path don't
        # require darnit-baseline to be importable.
        from darnit_baseline.tools import audit_openssf_baseline

        return audit_openssf_baseline(**args)
    return json.dumps({"error": f"unknown tool: {call.function.name}"})


def _load_skill_prompt() -> str:
    if not PROMPT_SNAPSHOT_PATH.exists():
        raise SetupError(
            f"skill prompt snapshot missing: {PROMPT_SNAPSHOT_PATH}. "
            "Run T022 (feature 028) to capture it before invoking Tier 2.",
        )
    return PROMPT_SNAPSHOT_PATH.read_text()


class OpenAIBackend:
    """OpenAI Chat Completions API backend for Tier 2 parity checks."""

    name = "openai"

    @classmethod
    def check_env(cls) -> None:
        """FR-008: fail fast when OPENAI_API_KEY is absent."""
        if not os.environ.get("OPENAI_API_KEY"):
            raise SetupError(
                "Tier 2 OpenAI backend requires OPENAI_API_KEY. Configure "
                "the `parity-tier2-openai` GitHub Actions Environment (or "
                "export the var for a local run).",
            )

    async def invoke(
        self,
        fixture_dir: Path,
        model: str,
        max_turns: int,
    ) -> SkillInvocationResult:
        """Invoke an OpenAI-based skill against `fixture_dir`.

        Implements research.md R3's Chat Completions loop. On completion:
        - Final text message received -> `turn_cap_exhausted=False`.
        - Turn cap reached without text -> `turn_cap_exhausted=True`,
          empty `final_message`.
        """
        # Local import so unit tests exercising the SetupError path don't
        # require the openai SDK to be importable.
        from openai import AsyncOpenAI

        client = AsyncOpenAI()  # reads OPENAI_API_KEY from env

        skill_prompt = _load_skill_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": skill_prompt},
            {
                "role": "user",
                "content": (
                    f"Run the audit against the repository at {fixture_dir}. "
                    "Use the audit_openssf_baseline tool. Summarize the "
                    "results per the skill's usual format after the tool "
                    "returns."
                ),
            },
        ]

        turn_count = 0
        for _turn in range(max_turns):
            turn_count += 1
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.0,
            )
            msg = response.choices[0].message

            if msg.tool_calls:
                # Append the assistant's tool-call message and each result.
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.function.name,
                                    "arguments": call.function.arguments,
                                },
                            }
                            for call in msg.tool_calls
                        ],
                    }
                )
                for call in msg.tool_calls:
                    result = _dispatch_tool_call(call, fixture_dir)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": result,
                        }
                    )
                continue

            if msg.content:
                return SkillInvocationResult(
                    final_message=msg.content,
                    model=model,
                    turn_count=turn_count,
                    metadata={"backend": "openai"},
                )

            # No tool calls AND no content -- unusual; treat as effectively
            # done and let the parser decide.
            return SkillInvocationResult(
                final_message="",
                model=model,
                turn_count=turn_count,
                metadata={"backend": "openai", "empty_response": True},
            )

        # Fell out of the loop without a final text message.
        return SkillInvocationResult(
            final_message="",
            model=model,
            turn_count=max_turns,
            metadata={"backend": "openai"},
            turn_cap_exhausted=True,
        )


__all__ = (
    "OpenAIBackend",
    "_TOOL_SCHEMAS",
    "_dispatch_tool_call",
)
