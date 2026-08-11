"""Tier 2 backend registry (feature 029 T007).

BACKEND_REGISTRY is the source of truth for `--backend <name>` lookup.
Adding a new backend = one line here + a new module file. See
`contracts/skill-invocation-backend-protocol.md` for the Protocol shape.
"""

from __future__ import annotations

from tests.darnit.parity.tier2.backends.base import (
    SetupError,
    SkillInvocationBackend,
    SkillInvocationResult,
)
from tests.darnit.parity.tier2.backends.claude_agent_sdk import (
    ClaudeAgentSdkBackend,
)
from tests.darnit.parity.tier2.backends.openai_backend import OpenAIBackend

BACKEND_REGISTRY: dict[str, type[SkillInvocationBackend]] = {
    "claude_agent_sdk": ClaudeAgentSdkBackend,
    "openai": OpenAIBackend,
    # NoopBackend intentionally not registered here -- tests inject it via
    # `run(backends={"noop": NoopBackend})`.
}


__all__ = (
    "SetupError",
    "SkillInvocationBackend",
    "SkillInvocationResult",
    "ClaudeAgentSdkBackend",
    "OpenAIBackend",
    "BACKEND_REGISTRY",
)
