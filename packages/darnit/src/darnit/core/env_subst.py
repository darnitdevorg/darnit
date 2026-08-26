"""Shared ``$VAR`` substitution helper.

Feature 033 (research decision R-004) extracted this routine from where it
was duplicated in feature 025's ``exec`` handler and feature 031's mcp
``env`` block. Consumers migrate to this shared implementation via
T005/T006; new consumers (feature 033's ``[stores.<kind>]`` TOML blocks)
call it directly.

Semantics chosen to match the previous behavior of both existing call
sites so no downstream behavior changes:

* ``$VAR`` occurrences substitute the value from ``env``.
* ``$$`` is a literal ``$`` (escape).
* Non-alphanumeric-underscore characters after ``$`` terminate the
  variable name, so ``$FOO/bar`` yields ``value(FOO) + "/bar"``.
* When ``missing_ok=True`` (default), unset variables substitute as
  empty string. Matches features 025/031 semantics.
* When ``missing_ok=False``, unset variables raise ``KeyError(<varname>)``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

__all__ = ["substitute_dollar_vars"]


MissingMode = Literal["empty", "raise", "leave"]


def substitute_dollar_vars(
    template: str,
    env: Mapping[str, str] | None = None,
    *,
    missing: MissingMode = "empty",
) -> str:
    """Substitute ``$VAR`` occurrences in ``template`` with values from ``env``.

    Args:
        template: The string to scan for ``$VAR`` tokens.
        env: Mapping from variable name to value. Defaults to
            :data:`os.environ`.
        missing: Behavior for unset variables. One of:

            * ``"empty"`` (default) -- substitute as empty string. Matches
              features 025 and 031 semantics.
            * ``"raise"`` -- raise ``KeyError(<varname>)``.
            * ``"leave"`` -- keep the ``$NAME`` literal in the output.
              Matches the previous behavior of the mcp-handler
              ``_apply_replacements`` helper for tokens not in a bounded
              replacement dict.

    Returns:
        The substituted string.

    Raises:
        KeyError: When ``missing="raise"`` and a variable is unset.
    """
    if env is None:
        env = os.environ

    result: list[str] = []
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch != "$":
            result.append(ch)
            i += 1
            continue
        # `$` -- check what follows
        if i + 1 < n and template[i + 1] == "$":
            # $$ -> literal $
            result.append("$")
            i += 2
            continue
        # Scan the variable name (alphanumerics + underscore)
        end = i + 1
        while end < n and (template[end].isalnum() or template[end] == "_"):
            end += 1
        if end == i + 1:
            # Lone `$` with nothing name-like after it: keep as literal
            result.append("$")
            i += 1
            continue
        varname = template[i + 1 : end]
        if varname in env:
            result.append(env[varname])
        elif missing == "empty":
            pass  # substitute empty string
        elif missing == "leave":
            result.append(template[i:end])  # keep `$NAME` literal
        else:  # missing == "raise"
            raise KeyError(varname)
        i = end
    return "".join(result)
