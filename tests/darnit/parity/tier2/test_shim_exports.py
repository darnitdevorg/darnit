"""Backwards-compat shim inventory (feature 029 T009a / MC3).

Defensive: imports every public name from feature 028's original module
surface via the shim path. If a future rename drops one of these names,
this test surfaces it explicitly rather than waiting for a downstream test
to break at a distance.
"""

from __future__ import annotations

from pathlib import Path


class TestShimReexports:
    def test_setup_error_reexported(self) -> None:
        from tests.darnit.parity.tier2.claude_agent_sdk_client import (
            SetupError,
        )

        assert issubclass(SetupError, RuntimeError)

    def test_skill_invocation_result_reexported(self) -> None:
        from tests.darnit.parity.tier2.claude_agent_sdk_client import (
            SkillInvocationResult,
        )

        # Frozen dataclass with the feature 028 field set at minimum.
        instance = SkillInvocationResult(
            final_message="x",
            model="y",
            turn_count=1,
        )
        assert instance.final_message == "x"

    def test_invoke_skill_reexported_and_callable(self) -> None:
        from tests.darnit.parity.tier2.claude_agent_sdk_client import (
            invoke_skill,
        )

        assert callable(invoke_skill)

    def test_prompt_snapshot_path_reexported_as_path(self) -> None:
        from tests.darnit.parity.tier2.claude_agent_sdk_client import (
            PROMPT_SNAPSHOT_PATH,
        )

        assert isinstance(PROMPT_SNAPSHOT_PATH, Path)
        assert PROMPT_SNAPSHOT_PATH.exists()
