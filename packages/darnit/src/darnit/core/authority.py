"""Evidence authority classification.

RFC-0001 Stage 1. See specs/025-rfc0001-stage1/data-model.md section 1.

Authority is a first-class attribute on every step definition and result.
Only ``dispositive`` and ``asserted`` results may conclude a control;
``suggestive`` results attach as evidence but never conclude. The strategy
runner enforces this in ``resolve_step_result``.
"""

from __future__ import annotations

from typing import Literal

Authority = Literal["dispositive", "suggestive", "asserted"]

# Values that terminate a control's strategy list on a PASS/FAIL outcome.
_TERMINAL_AUTHORITIES: frozenset[Authority] = frozenset(("dispositive", "asserted"))


def is_terminal_authority(authority: Authority | None) -> bool:
    """Return True iff ``authority`` may conclude a control's verdict.

    ``None`` and unknown-string inputs return False -- the safety property
    from FR-001: an authority-less result never concludes.
    """
    return authority in _TERMINAL_AUTHORITIES
