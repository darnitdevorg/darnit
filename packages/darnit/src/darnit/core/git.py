"""Centralized, hardened git execution for untrusted repositories (issue #617)."""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path


@functools.lru_cache(maxsize=1)
def _auditor_signing_programs() -> tuple[str, str]:
    """Resolve the auditor's default gpg.program and gpg.ssh.program outside any repo."""
    defaults: list[str] = []
    for key, fallback in (("gpg.program", "gpg"), ("gpg.ssh.program", "ssh-keygen")):
        value = fallback
        for scope in ("--global", "--system"):
            try:
                proc = subprocess.run(
                    ["git", "config", scope, "--get", key],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    value = proc.stdout.strip()
                    break
            except (OSError, subprocess.SubprocessError):
                break
        defaults.append(value)
    return defaults[0], defaults[1]


def run_git(
    repo: str | Path,
    *args: str,
    stdin: str | None = None,
    timeout: float | None = None,
    verify_signatures: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a git command against ``repo`` hardened against untrusted repo config."""
    hardened_args: list[str] = ["--no-optional-locks", "-c", "core.fsmonitor=false"]
    if verify_signatures:
        gpg_prog, ssh_prog = _auditor_signing_programs()
        hardened_args.extend(["-c", f"gpg.program={gpg_prog}", "-c", f"gpg.ssh.program={ssh_prog}"])
    return subprocess.run(
        ["git", *hardened_args, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=stdin,
        timeout=timeout,
    )


__all__ = ["run_git", "_auditor_signing_programs"]
