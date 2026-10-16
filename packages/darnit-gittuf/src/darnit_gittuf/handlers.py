"""Gittuf sieve handlers.

These are the functions that actually run the checks.
Each one receives a config dict and a HandlerContext,
and returns a HandlerResult saying PASS, FAIL, or INCONCLUSIVE.
"""

import subprocess
from collections import Counter
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


# git's %G? letters (git-log(1)): G good signature, B bad, U good with unknown
# validity, X good but expired, Y good by an expired key, R good by a revoked
# key, E cannot be checked, N no signature.
_NOT_GOOD = {
    "N": "unsigned",
    "B": "BAD signature",
    "R": "signed by a revoked key",
    "Y": "signed by an expired key",
    "X": "expired signature",
}
_SIGNATURE_HEADERS = ("gpgsig ", "gpgsig-sha256 ")


def _has_signature_header(local_path: str, sha: str) -> bool:
    """Whether commit ``sha`` carries a signature, whatever git could make of it."""
    result = subprocess.run(
        ["git", "cat-file", "commit", sha],
        cwd=local_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    headers = result.stdout.split("\n\n", 1)[0]
    return any(line.startswith(_SIGNATURE_HEADERS) for line in headers.splitlines())


def gittuf_commits_signed_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check that the last 5 commits carry good signatures (framework-design section 12).

    Only ``G`` counts as signed. FAIL when a commit is unsigned or its
    signature is bad, revoked or expired. ERROR (``evaluation``) when a
    commit carries a signature this machine cannot check: ``E``, or a
    signature git reports as ``N`` because it is not set up to check it
    (an SSH signature without ``gpg.ssh.allowedSignersFile``, or no
    ``gpg``). INCONCLUSIVE for ``U`` (nothing here says the key is
    trusted) and for no commits. A FAIL outweighs an ERROR, which
    outweighs INCONCLUSIVE.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H%x1f%G?%x1f%GK", "-5"],
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

        commits = [line.split("\x1f") for line in result.stdout.splitlines() if line.strip()]
        if not commits:
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="No commits found to check",
                confidence=0.0,
            )

        not_good: Counter[str] = Counter()
        unverifiable: list[str] = []
        unknown_validity: list[str] = []
        for sha, status, _key in commits:
            if status == "G":
                continue
            if status == "U":
                unknown_validity.append(sha)
            elif status == "N" and _has_signature_header(ctx.local_path, sha):
                unverifiable.append(sha)
            elif status in _NOT_GOOD:
                not_good[status] += 1
            else:
                unverifiable.append(sha)

        statuses = Counter(status for _sha, status, _key in commits)
        total = len(commits)
        evidence = {
            "total_checked": total,
            "signed": statuses["G"],
            "unsigned": not_good["N"],
            "bad_signature": not_good["B"],
            "statuses": dict(statuses),
            "unverifiable_commits": unverifiable,
            "unknown_validity_commits": unknown_validity,
        }

        if not_good:
            details = ", ".join(f"{count} {_NOT_GOOD[status]}" for status, count in not_good.items())
            return HandlerResult(
                status=HandlerResultStatus.FAIL,
                message=f"{sum(not_good.values())} of last {total} commits lack a good signature: {details}",
                confidence=1.0,
                evidence=evidence,
            )

        if unverifiable:
            git_said = "; ".join(dict.fromkeys(line.strip() for line in result.stderr.splitlines() if line.strip()))
            cause = git_said or "for example, the signing key is not available"
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=(
                    f"{len(unverifiable)} of last {total} commits carry signatures this machine cannot check ({cause})"
                ),
                evidence=evidence,
                error_class="evaluation",
            )

        if unknown_validity:
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message=(
                    f"{len(unknown_validity)} of last {total} commits have good signatures of unknown "
                    "validity: nothing on this machine says the signing keys are trusted "
                    "(for SSH signatures, gpg.ssh.allowedSignersFile must list them)"
                ),
                confidence=0.0,
                evidence=evidence,
            )

        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"All {total} recent commits have good signatures",
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
