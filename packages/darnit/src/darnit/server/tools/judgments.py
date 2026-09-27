"""``submit_judgment``: the only path by which a coding agent's judgment reaches an audit (feature 041, FR-015).

The agent's judgment is treated exactly like the headless harness's model
judgment: at most a PASS candidate, never a PASS. The control's judged
content is re-gathered by auditing ``local_path``; the client's copy of the
evidence is never trusted.
"""

import asyncio
from typing import Any, Literal

from darnit.core.logging import get_logger

logger = get_logger("server.tools.judgments")


def submit_judgment_impl(
    control_id: str,
    verdict: str,
    reasoning: str,
    cited_evidence: list[str],
    model: str,
    model_version: str,
    owner: str,
    repo: str,
    host: str = "github.com",
    local_path: str = ".",
    *,
    framework_name: str,
) -> dict[str, Any]:
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.core.utils import validate_local_path
    from darnit.tools.audit import judgment_consultations
    from darnit.trust.decision import decide_trust, target_from_owner_repo
    from darnit.trust.judgments import Judgment, assess_judgment, store_candidate

    def rejected(reason: str, missing: list[str] | None = None) -> dict[str, Any]:
        rejection: dict[str, Any] = {"control_id": control_id, "reason": reason}
        if missing is not None:
            rejection["missing_excerpts"] = missing
        return {"status": "rejected", "rejection": rejection, "stored": False}

    def failed(message: str) -> dict[str, Any]:
        return {"status": "error", "error": message, "stored": False}

    if verdict not in ("pass", "fail"):
        return rejected(f"verdict must be 'pass' or 'fail', got {verdict!r}")

    resolved_path, error = validate_local_path(local_path)
    if error:
        return failed(error)
    try:
        operator_config = resolve_operator_config(resolved_path)
    except OperatorConfigError as exc:
        return failed(str(exc))

    target = target_from_owner_repo(owner, repo, host)
    identity = decide_trust(target, operator_config.config, resolved_path).repository
    if identity is None or not identity.trusted_eligible:
        return rejected(
            "name the audited repository (owner, repo, and host when not github.com); "
            "a checkout's own remotes cannot identify it"
        )

    try:
        consultation = judgment_consultations(
            resolved_path, [control_id], framework_name, operator_config, owner, repo, target
        )[control_id]
    except Exception as exc:  # noqa: BLE001 - surfaced to the client, nothing stored
        logger.warning("submit_judgment: could not re-gather evidence for %s: %s", control_id, exc)
        return failed(f"could not re-gather the evidence for {control_id}: {exc}")
    if consultation is None:
        return rejected(f"{control_id} does not reach a model judgment step in an audit of {resolved_path}")

    judgment = Judgment(
        verdict="pass" if verdict == "pass" else "fail",
        reasoning=reasoning,
        cited_evidence=tuple(cited_evidence or ()),
        model=model,
        model_version=model_version,
    )
    assessment = assess_judgment(judgment, consultation, source="mcp_agent")

    if assessment.kind == "invalid":
        return rejected(assessment.reason, list(assessment.missing_excerpts))
    if assessment.kind == "finding":
        return {
            "status": "finding",
            "finding": {
                "control_id": control_id,
                "status": "FAIL",
                "authority": "suggestive",
                "concluded_by": "llm_judgment",
                "reasoning": reasoning,
                "cited_evidence": list(judgment.cited_evidence),
            },
            "stored": False,
        }

    candidate = assessment.candidate or {}
    try:
        store_candidate(identity.canonical, control_id, candidate, checkout=resolved_path)
    except (OSError, ValueError) as exc:
        return failed(f"PASS candidate not stored: {exc}")
    return {
        "status": "candidate",
        "candidate": {"control_id": control_id, **candidate},
        "stored": True,
        "message": (
            f"{control_id} is a PASS candidate for {identity.canonical}. It counts as non-compliant until "
            "the operator confirms it; confirm only on the operator's explicit instruction."
        ),
    }


async def submit_judgment(
    control_id: str,
    verdict: Literal["pass", "fail"],
    reasoning: str,
    cited_evidence: list[str],
    model: str,
    model_version: str,
    owner: str,
    repo: str,
    host: str = "github.com",
    local_path: str = ".",
    _framework_name: str | None = None,
) -> dict[str, Any]:
    """Submit your judgment for a control awaiting one (PENDING, pending.kind = "llm_judgment").

    A judgment never makes a control PASS. A "pass" verdict whose cited
    excerpts all appear verbatim in the files the control's model step read
    is recorded as a PASS candidate, which stays non-compliant until the
    operator confirms it. A "fail" verdict is returned as a suggestive FAIL
    finding and not stored. A judgment citing text that is not in those
    files, or a "pass" citing nothing, is rejected.

    Args:
        control_id: The control you judged.
        verdict: "pass" or "fail".
        reasoning: Why the evidence does or does not satisfy the control.
        cited_evidence: Passages you relied on, copied verbatim from the files
            in the control's evidence.llm_consultation.file_contents.
        model: The model that made the judgment.
        model_version: That model's version.
        owner: Owner of the audited repository.
        repo: Name of the audited repository.
        host: Git host of owner/repo.
        local_path: Path to the audited checkout.
    """
    if not _framework_name:
        return {"status": "error", "error": "no framework is configured for this server", "stored": False}
    return await asyncio.to_thread(
        submit_judgment_impl,
        control_id,
        verdict,
        reasoning,
        list(cited_evidence or []),
        model,
        model_version,
        owner,
        repo,
        host,
        local_path,
        framework_name=_framework_name,
    )


async def confirm_pass_candidate(
    control_ids: list[str],
    owner: str,
    repo: str,
    host: str = "github.com",
    local_path: str = ".",
    _framework_name: str | None = None,
) -> str:
    """Confirm stored PASS candidates for the named repository.

    Call this ONLY when the operator explicitly tells you to confirm. A
    confirmation applies to the evidence as it is now and lapses when it
    expires or the judged content or the control's rubric changes.

    Args:
        control_ids: Controls whose PASS candidate the operator confirms.
        owner: Owner of the audited repository.
        repo: Name of the audited repository.
        host: Git host of owner/repo.
        local_path: Path to the audited checkout.
    """
    from darnit.server.tools.project_data import confirm_pass_candidates_impl

    return await asyncio.to_thread(
        confirm_pass_candidates_impl,
        local_path,
        list(control_ids or []),
        owner=owner,
        repo=repo,
        host=host,
        framework_name=_framework_name,
    )


def _bind_framework(fn: Any, framework_name: str) -> Any:
    import functools
    import inspect

    @functools.wraps(fn)
    async def bound(**kwargs: Any) -> Any:
        kwargs["_framework_name"] = framework_name
        return await fn(**kwargs)

    sig = inspect.signature(fn)
    bound.__signature__ = sig.replace(  # type: ignore[attr-defined]
        parameters=[p for name, p in sig.parameters.items() if name != "_framework_name"]
    )
    return bound


def register_judgment_tools(server: Any, framework_name: str | None) -> None:
    """Register ``submit_judgment`` and ``confirm_pass_candidate`` bound to the server's framework."""
    if not framework_name:
        logger.debug("No framework name; judgment tools not registered")
        return

    server.add_tool(
        _bind_framework(submit_judgment, framework_name),
        name="submit_judgment",
        description=(
            "Submit a judgment for a control awaiting one (PENDING, pending.kind = llm_judgment). "
            "Never makes a control PASS: a 'pass' verdict whose cited_evidence excerpts all appear "
            "verbatim in the files the control's model step read becomes a PASS candidate, "
            "non-compliant until the operator confirms it; a 'fail' verdict is a suggestive FAIL "
            "finding; unverifiable citations are rejected. Never state your verdict as the audit result."
        ),
    )
    server.add_tool(
        _bind_framework(confirm_pass_candidate, framework_name),
        name="confirm_pass_candidate",
        description=(
            "Confirm stored PASS candidates (PENDING, pending.kind = confirmation) for the named "
            "repository. Call ONLY on the operator's explicit instruction; never on your own "
            "judgment. Confirms only a candidate for the current evidence; the confirmation lapses "
            "on expiry or when the judged content or rubric changes."
        ),
    )
    logger.debug("Registered judgment tools for framework %s", framework_name)
