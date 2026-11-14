"""GitHub context detectors for the OpenSSF Baseline."""

from typing import Any

from darnit.context.auto_detect import detect_platform
from darnit.core.utils import gh_api_with_status
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus


def github_repository_owner_type(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Resolve the owner type, using Unknown when GitHub cannot establish it."""
    owner_type = "Unknown"
    if context.owner and context.repo and detect_platform(context.local_path) in (None, "github"):
        body, status, _ = gh_api_with_status(f"/repos/{context.owner}/{context.repo}")
        if 200 <= status < 300 and isinstance(body, dict):
            owner = body.get("owner")
            if isinstance(owner, dict) and owner.get("type") in ("User", "Organization"):
                owner_type = owner["type"]

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"GitHub repository owner type: {owner_type}",
        evidence={"value": owner_type},
        confidence=1.0,
    )
