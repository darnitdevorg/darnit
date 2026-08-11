"""SkillInvocationBackend Protocol + shared types (feature 029 T003).

Defines the Protocol every Tier 2 provider adapter conforms to. See:
  - specs/029-openai-parity-adapter/data-model.md sections 1-3
  - specs/029-openai-parity-adapter/contracts/skill-invocation-backend-protocol.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class SetupError(RuntimeError):
    """Raised by a backend's `check_env()` when the provider's credentials
    or environment are not configured. The runner catches this and returns
    exit code 3 (setup). Contract B-11..B-13.
    """


@dataclass(frozen=True)
class SkillInvocationResult:
    """Return type for `SkillInvocationBackend.invoke()`.

    Fields:
      final_message: the string the parser will consume. Empty only when
        `turn_cap_exhausted=True`.
      model: the exact model identifier the backend used (e.g. the pinned
        version-suffixed string from the workflow YAML).
      turn_count: number of assistant turns actually taken. Non-negative.
      metadata: provider-specific extras (backend name, usage stats, etc.).
      turn_cap_exhausted: True iff the model exhausted its turn cap without
        emitting a final text message. Feature 029 addition -- default False
        so feature 028's Claude adapter can construct results without
        setting it. See spec.md FR-010 and SC-011.
    """

    final_message: str
    model: str
    turn_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    turn_cap_exhausted: bool = False


@runtime_checkable
class SkillInvocationBackend(Protocol):
    """Protocol every Tier 2 provider adapter conforms to.

    See `contracts/skill-invocation-backend-protocol.md` rules B-1..B-23.

    - `name`: stable identifier used as the `--backend` CLI value and the
      `BACKEND_REGISTRY` key.
    - `invoke()`: async; caller (runner) supplies `model` and `max_turns`.
    - `check_env()`: classmethod so the runner can fail fast on missing
      credentials without constructing an instance.
    """

    name: str

    async def invoke(
        self,
        fixture_dir: Path,
        model: str,
        max_turns: int,
    ) -> SkillInvocationResult: ...

    @classmethod
    def check_env(cls) -> None: ...


__all__ = (
    "SetupError",
    "SkillInvocationBackend",
    "SkillInvocationResult",
)
