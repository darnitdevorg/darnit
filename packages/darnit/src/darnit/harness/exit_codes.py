"""Exit-code contract for `darnit harness`.

Per FR-008 + contract cli.md CLI-11. A CI script uses these to distinguish
"audit ran and found issues" from "audit couldn't run at all."

See specs/026-darnit-harness/contracts/cli.md.
"""

from __future__ import annotations

from enum import IntEnum


class HarnessExitCode(IntEnum):
    """The four documented exit-code classes.

    - SUCCESS (0): Audit completed. Zero FAIL results.
    - AUDIT_FAILURES (1): Audit completed. At least one FAIL.
    - SETUP_ERROR (2): Missing credentials, missing repo, bad args, unparseable
      answers file. Audit did NOT run.
    - INTERNAL_ERROR (3): Unhandled exception, total-run timeout, invariant
      violation. Audit may have partial results.
    """

    SUCCESS = 0
    AUDIT_FAILURES = 1
    SETUP_ERROR = 2
    INTERNAL_ERROR = 3


__all__ = ["HarnessExitCode"]
