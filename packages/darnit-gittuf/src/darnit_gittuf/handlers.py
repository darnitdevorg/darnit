"""Gittuf sieve handlers.

These are the functions that actually run the checks.
Each one receives a config dict and a HandlerContext,
and returns a HandlerResult saying PASS, FAIL, or INCONCLUSIVE.
"""

import subprocess
from typing import Any

from darnit.core.logging import get_logger
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus

logger = get_logger("darnit_gittuf.handlers")


def gittuf_verify_policy_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check that the Gittuf policy passes verification.

    Runs: gittuf verify-ref HEAD
    PASS if exit code is 0, FAIL otherwise.
    INCONCLUSIVE if gittuf is not installed.
    """
    try:
        result = subprocess.run(
            ["gittuf", "verify-ref", "HEAD"],
            cwd=ctx.local_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="Gittuf policy verification passed",
                confidence=1.0,
                evidence={"gittuf_output": result.stdout.strip()},
            )
        else:
            return HandlerResult(
                status=HandlerResultStatus.FAIL,
                message=f"Gittuf policy verification failed: {result.stderr.strip()}",
                confidence=1.0,
                evidence={
                    "gittuf_output": result.stdout.strip(),
                    "gittuf_error": result.stderr.strip(),
                },
            )

    except FileNotFoundError:
        # gittuf is not installed on this machine
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="gittuf binary not found — cannot verify policy",
            confidence=0.0,
        )
    except subprocess.TimeoutExpired:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="gittuf verify-ref timed out after 30 seconds",
            confidence=0.0,
        )
    except Exception as e:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"Unexpected error running gittuf: {e}",
            confidence=0.0,
        )


def gittuf_commits_signed_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check that recent commits are cryptographically signed.

    Looks at the last 5 commits. PASS if all are signed, FAIL if any
    are unsigned, INCONCLUSIVE if git is not available.

    Note: SSH-signed commits require gpg.ssh.allowedSignersFile to be
    configured for git to verify them. Without it, SSH-signed commits
    report as unsigned. This handler warns when this condition is detected.
    """
    # Check if allowedSignersFile is configured for SSH signing verification
    try:
        signers_check = subprocess.run(
            ["git", "config", "gpg.ssh.allowedSignersFile"],
            cwd=ctx.local_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        ssh_signers_configured = signers_check.returncode == 0
    except Exception:
        ssh_signers_configured = False

    try:
        result = subprocess.run(
            ["git", "log", "--format=%G?%n%GK", "-5"],
            cwd=ctx.local_path,
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="Could not read git log",
                confidence=0.0,
            )

        lines = result.stdout.strip().splitlines()

        # %G? and %GK alternate — collect signature status lines
        sig_statuses = [line.strip() for i, line in enumerate(lines) if i % 2 == 0 and line.strip()]
        sig_keys = [line.strip() for i, line in enumerate(lines) if i % 2 == 1]

        if not sig_statuses:
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="No commits found to check",
                confidence=0.0,
            )

        unsigned = [s for s in sig_statuses if s == "N"]
        bad = [s for s in sig_statuses if s == "B"]
        signed = [s for s in sig_statuses if s in ("G", "U", "E", "X")]

        # Detect if SSH keys are in use without allowedSignersFile
        has_ssh_keys = any(k.startswith("ssh-") for k in sig_keys if k)
        if unsigned and has_ssh_keys and not ssh_signers_configured:
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message=(
                    "SSH-signed commits detected but gpg.ssh.allowedSignersFile "
                    "is not configured — git cannot verify SSH signatures. "
                    "Set gpg.ssh.allowedSignersFile to enable verification."
                ),
                confidence=0.0,
                evidence={
                    "total_checked": len(sig_statuses),
                    "ssh_signers_configured": False,
                    "hint": "Run: git config gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers",
                },
            )

        evidence = {
            "total_checked": len(sig_statuses),
            "signed": len(signed),
            "unsigned": len(unsigned),
            "bad_signature": len(bad),
            "ssh_signers_configured": ssh_signers_configured,
        }

        if bad:
            return HandlerResult(
                status=HandlerResultStatus.FAIL,
                message=f"{len(bad)} commits have BAD signatures",
                confidence=1.0,
                evidence=evidence,
            )

        if unsigned:
            return HandlerResult(
                status=HandlerResultStatus.FAIL,
                message=f"{len(unsigned)} of last {len(sig_statuses)} commits are unsigned",
                confidence=1.0,
                evidence=evidence,
            )

        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"All {len(signed)} recent commits are signed",
            confidence=1.0,
            evidence=evidence,
        )

    except FileNotFoundError:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="git binary not found",
            confidence=0.0,
        )
    except Exception as e:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"Unexpected error checking commit signatures: {e}",
            confidence=0.0,
        )
