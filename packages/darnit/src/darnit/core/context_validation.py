"""Validation for user-supplied context answer values.

Context answers are eventually substituted into shell-style command
templates by ``RemediationExecutor._substitute_command``. Even without
``shell=True``, null bytes and newlines can break argument handling, and
shell metacharacters have no legitimate use in compliance context values
(paths, maintainer names, policy filenames, etc.). Reject them at the
validation boundary.

Both the legacy agent-graph confirmation flow (agent/graph.py) and the
new action-plan collect_context integration (core/action_plan.py) must
call the same validator. Living in ``core`` avoids a
``core -> agent -> core`` import cycle.
"""

from __future__ import annotations

_INVALID_ANSWER_CHARS = frozenset("\x00\n\r;|&$`(){}[]<>\\")


def validate_context_answer(key: str, value: str) -> None:
    """Raise ValueError if *value* contains characters unsafe for context substitution.

    Args:
        key: The context key (used only for the error message).
        value: The user-supplied answer string to validate.

    Raises:
        ValueError: If the value contains shell metacharacters, newlines, or
            null bytes that could enable injection via command substitution.
    """
    found = _INVALID_ANSWER_CHARS & set(value)
    if found:
        raise ValueError(
            f"Context answer for {key!r} contains disallowed character(s) "
            f"{sorted(found)!r}. Values must not include shell metacharacters, "
            "newlines, or null bytes."
        )


__all__ = ["validate_context_answer"]
