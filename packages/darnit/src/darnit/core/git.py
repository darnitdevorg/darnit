"""Core git execution helpers with sanitized configurations."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence


def _auditor_signing_programs() -> list[str]:
    """Signing programs configured by the auditor (not the audited repo)."""
    return []


def run_git(
    args: Sequence[str],
    cwd: str | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git command with sanitized configuration (harden read-side git calls)."""
    cmd = ["git", "-c", "core.fsmonitor=", "-c", "gpg.program=", "-c", "gpg.ssh.program="] + list(args)
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=True,
    )
