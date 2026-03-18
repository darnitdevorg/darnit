"""Gittuf sieve handlers.

These are the functions that actually run the checks.
Each one receives a config dict and a HandlerContext,
and returns a HandlerResult saying PASS, FAIL, or INCONCLUSIVE.
"""

import subprocess
from typing import Any

from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus
from darnit.core.logging import get_logger

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
    """
    try:
        result = subprocess.run(
            ["git", "log", "--format=%G?", "-5"],
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

        # %G? returns one character per commit:
        # G = good signature, B = bad signature, N = no signature
        # U = good signature, unknown validity
        signatures = result.stdout.strip().splitlines()

        if not signatures:
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="No commits found to check",
                confidence=0.0,
            )

        unsigned = [s for s in signatures if s.strip() == "N"]
        bad = [s for s in signatures if s.strip() == "B"]
        signed = [s for s in signatures if s.strip() in ("G", "U")]

        evidence = {
            "total_checked": len(signatures),
            "signed": len(signed),
            "unsigned": len(unsigned),
            "bad_signature": len(bad),
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
                message=f"{len(unsigned)} of last {len(signatures)} commits are unsigned",
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