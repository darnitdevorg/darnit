"""GitHub context detectors for the OpenSSF Baseline."""

from typing import Any

from darnit.context.auto_detect import detect_platform
from darnit.core.utils import gh_api_error_class, gh_api_with_status
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus


def github_repository_owner_type(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Resolve the owner type from GitHub repository metadata."""
    if not context.owner or not context.repo or detect_platform(context.local_path) not in (None, "github"):
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="GitHub repository identity is unavailable for owner type detection",
            error_class="unavailable",
        )

    endpoint = f"/repos/{context.owner}/{context.repo}"
    body, status, error = gh_api_with_status(endpoint)
    if not 200 <= status < 300:
        detail = error or (f"HTTP {status}" if status else "no response")
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Could not detect GitHub owner type from {endpoint}: {detail}",
            error_class=gh_api_error_class(status, error),
        )

    owner = body.get("owner") if isinstance(body, dict) else None
    owner_type = owner.get("type") if isinstance(owner, dict) else None
    if owner_type not in ("User", "Organization"):
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"GitHub response from {endpoint} has no recognized owner type",
            error_class="unavailable",
        )

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"GitHub repository owner type: {owner_type}",
        evidence={"value": owner_type},
        confidence=1.0,
    )
