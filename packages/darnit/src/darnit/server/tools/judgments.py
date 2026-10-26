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


# Claude Code writes a tool result of about 50,000 bytes or more to a file
# instead of showing it to the model (#644).
JUDGMENT_REQUEST_PAGE_BYTES = 40_000


def _judgment_request(result: dict[str, Any], file_keys: list[str]) -> dict[str, Any]:
    from darnit.trust.judgments import evidence_digest

    consultation = (result.get("evidence") or {}).get("llm_consultation") or {}
    request: dict[str, Any] = {
        "control_id": result["id"],
        "kind": (result.get("pending") or {}).get("kind"),
        "prompt": consultation.get("prompt") or "",
        "analysis_hints": list(consultation.get("analysis_hints") or []),
        "evidence_digest": evidence_digest(consultation),
        "files": file_keys,
    }
    if consultation.get("target_key"):
        request["target_key"] = consultation["target_key"]
    return request


def get_judgment_requests_impl(
    owner: str,
    repo: str,
    host: str = "github.com",
    local_path: str = ".",
    control_ids: list[str] | None = None,
    include_judged: bool = False,
    *,
    framework_name: str,
) -> str:
    import hashlib
    import json

    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.core.utils import validate_local_path
    from darnit.server.procedures import judgment_procedure
    from darnit.tools.audit import judgment_audit
    from darnit.trust.decision import decide_trust, target_from_owner_repo
    from darnit.trust.judgments import judged_content

    def dump(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    resolved_path, error = validate_local_path(local_path)
    if error:
        return dump({"status": "error", "error": error})
    try:
        operator_config = resolve_operator_config(resolved_path)
    except OperatorConfigError as exc:
        return dump({"status": "error", "error": str(exc)})

    target = target_from_owner_repo(owner, repo, host)
    identity = decide_trust(target, operator_config.config, resolved_path).repository
    if identity is None or not identity.trusted_eligible:
        return dump(
            {
                "status": "rejected",
                "rejection": {
                    "reason": (
                        "name the audited repository (owner, repo, and host when not github.com); "
                        "a checkout's own remotes cannot identify it"
                    )
                },
            }
        )

    try:
        results = judgment_audit(
            resolved_path, framework_name, operator_config, owner, repo, target, control_ids=control_ids or None
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        logger.warning("get_judgment_requests: could not audit %s: %s", resolved_path, exc)
        return dump({"status": "error", "error": f"could not audit {resolved_path}: {exc}"})

    kinds = {"llm_judgment", "confirmation"} if include_judged else {"llm_judgment"}
    wanted = set(control_ids) if control_ids else None
    pending = sorted(
        (
            r
            for r in results
            if r.get("status") == "PENDING"
            and (r.get("pending") or {}).get("kind") in kinds
            and (r.get("evidence") or {}).get("llm_consultation")
            and (wanted is None or r["id"] in wanted)
        ),
        key=lambda r: r["id"],
    )
    skipped = (
        []
        if include_judged
        else sorted(
            r["id"]
            for r in results
            if r.get("status") == "PENDING"
            and (r.get("pending") or {}).get("kind") == "confirmation"
            and (r.get("evidence") or {}).get("llm_consultation")
            and (wanted is None or r["id"] in wanted)
        )
    )

    page: dict[str, Any] = {
        "status": "ok",
        "procedure": judgment_procedure(owner, repo, host, str(resolved_path)),
        "files": {},
        "requests": [],
        "remaining": [],
        "skipped": skipped,
    }
    oversized = False
    for index, result in enumerate(pending):
        files = dict(page["files"])
        keys = []
        for path, content in judged_content(result["evidence"]["llm_consultation"]).items():
            digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
            key = path
            n = 1
            while key in files and files[key]["digest"] != digest:
                n += 1
                key = f"{path}#{n}"
            files.setdefault(key, {"path": path, "digest": digest, "content": content})
            keys.append(key)
        trial = {
            **page,
            "files": files,
            "requests": [*page["requests"], _judgment_request(result, keys)],
            "remaining": [r["id"] for r in pending[index + 1 :]],
        }
        if len(dump(trial).encode("utf-8")) <= JUDGMENT_REQUEST_PAGE_BYTES:
            page = trial
            continue
        if not page["requests"]:
            page = {**trial, "oversized": True}
            oversized = True
        else:
            page["remaining"] = [r["id"] for r in pending[index:]]
        break
    if oversized:
        page["note"] = (
            f"{page['requests'][0]['control_id']} alone exceeds the {JUDGMENT_REQUEST_PAGE_BYTES}-byte page "
            "limit and is returned on its own page"
        )
    return dump(page)


CONFIRM_OPTIONS = (
    ("Confirm", "It reflects the project's actual practice: record my confirmation"),
    ("Do not confirm", "It does not: the control stays non-compliant"),
    ("Skip for now", "Decide later: the control stays non-compliant"),
)


def _question_header(control_id: str) -> str:
    """A header within the question tool's 12 characters: the control id without its framework prefix."""
    if len(control_id) > 12 and "-" in control_id:
        control_id = control_id.split("-", 1)[1]
    return control_id[:12]


def _confirmation_question(entry: dict[str, Any]) -> dict[str, Any]:
    """One question per candidate; the candidate itself is shown before the question, never inside it."""
    files = ", ".join(entry["files"]) or "no files"
    return {
        "question": f"Confirm the PASS candidate for {entry['control_id']} ({files})?",
        "header": _question_header(entry["control_id"]),
        "multiSelect": False,
        "options": [{"label": label, "description": description} for label, description in CONFIRM_OPTIONS],
    }


def get_pass_candidates_impl(
    owner: str,
    repo: str,
    host: str = "github.com",
    local_path: str = ".",
    control_ids: list[str] | None = None,
    run_id: str | None = None,
    *,
    framework_name: str,
) -> str:
    import json
    from pathlib import Path

    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.core.utils import validate_local_path
    from darnit.remediation import manifest
    from darnit.remediation.plan import content_digest
    from darnit.server.procedures import confirmation_procedure
    from darnit.tools.audit import _claim_controls, _load_framework, judgment_audit
    from darnit.trust.decision import decide_trust, target_from_owner_repo
    from darnit.trust.judgments import judged_content

    def dump(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    resolved_path, error = validate_local_path(local_path)
    if error:
        return dump({"status": "error", "error": error})
    try:
        operator_config = resolve_operator_config(resolved_path)
    except OperatorConfigError as exc:
        return dump({"status": "error", "error": str(exc)})

    target = target_from_owner_repo(owner, repo, host)
    identity = decide_trust(target, operator_config.config, resolved_path).repository
    if identity is None or not identity.trusted_eligible:
        return dump(
            {
                "status": "rejected",
                "rejection": {
                    "reason": (
                        "name the audited repository (owner, repo, and host when not github.com); "
                        "a checkout's own remotes cannot identify it"
                    )
                },
            }
        )

    try:
        results = judgment_audit(
            resolved_path, framework_name, operator_config, owner, repo, target, control_ids=control_ids or None
        )
        controls = _claim_controls(_load_framework(framework_name), operator_config.config)
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        logger.warning("get_pass_candidates: could not audit %s: %s", resolved_path, exc)
        return dump({"status": "error", "error": f"could not audit {resolved_path}: {exc}"})

    wanted = set(control_ids) if control_ids else None

    def awaits(result: dict[str, Any], kind: str) -> bool:
        return (
            result.get("status") == "PENDING"
            and (result.get("pending") or {}).get("kind") == kind
            and (wanted is None or result["id"] in wanted)
        )

    pending = sorted((r for r in results if awaits(r, "confirmation") and r.get("candidate")), key=lambda r: r["id"])

    written: dict[str, str] = {}
    note = None
    if run_id:
        try:
            run = manifest.load_run(
                manifest.repository_identity(resolved_path, owner, repo), run_id, checkout=resolved_path
            )
        except ValueError:
            run = None
        if run is None:
            note = f"run {run_id} not found for {identity.canonical}"
        else:
            written = {f.path: f.after_digest for f in run.files}

    def entry(result: dict[str, Any]) -> dict[str, Any]:
        candidate = result["candidate"]
        control = controls.get(result["id"])
        files = list(judged_content((result.get("evidence") or {}).get("llm_consultation")))
        item: dict[str, Any] = {
            "control_id": result["id"],
            "title": getattr(control, "name", "") or "",
            "description": getattr(control, "description", "") or "",
            "files": files,
            "reasoning": candidate.get("reasoning", ""),
            "cited_evidence": list(candidate.get("cited_evidence") or []),
            "model": candidate.get("model"),
            "model_version": candidate.get("model_version"),
            "source": candidate.get("source"),
            "evidence_digest": candidate.get("evidence_digest"),
        }
        for path in files:
            if path in written:
                current = Path(resolved_path) / path
                digest = content_digest(current.read_bytes()) if current.is_file() else None
                item["remediation"] = {
                    "run_id": run_id,
                    "path": path,
                    "written": True,
                    "edited_after_write": digest != written[path],
                }
                break
        return item

    page: dict[str, Any] = {
        "status": "ok",
        "procedure": confirmation_procedure(owner, repo, host, str(resolved_path)),
        "candidates": [],
        "ask_user_batch": [],
        "awaiting_judgment": sorted(r["id"] for r in results if awaits(r, "llm_judgment")),
        "remaining": [],
    }
    if note:
        page["note"] = note
    for index, result in enumerate(pending):
        item = entry(result)
        trial = {
            **page,
            "candidates": [*page["candidates"], item],
            "ask_user_batch": [*page["ask_user_batch"], _confirmation_question(item)],
            "remaining": [r["id"] for r in pending[index + 1 :]],
        }
        if len(dump(trial).encode("utf-8")) <= JUDGMENT_REQUEST_PAGE_BYTES or not page["candidates"]:
            page = trial
            continue
        page["remaining"] = [r["id"] for r in pending[index:]]
        break
    return dump(page)


async def get_judgment_requests(
    owner: str,
    repo: str,
    host: str = "github.com",
    local_path: str = ".",
    control_ids: list[str] | None = None,
    include_judged: bool = False,
    _framework_name: str | None = None,
) -> str:
    """Get the judgment requests for controls awaiting a judgment (PENDING, pending.kind = "llm_judgment").

    Returns JSON: ``procedure`` (the steps to follow with this page),
    ``requests`` (one per control: ``control_id``, ``prompt``,
    ``analysis_hints``, ``evidence_digest``, and ``files``, keys into the
    shared ``files`` map), ``files`` (``path``, ``digest``, and ``content``,
    exactly the content ``submit_judgment`` checks citations against), and
    ``remaining`` (controls not on this page), and ``skipped`` (controls
    left out because they have a stored PASS candidate). Pages stay under 40,000
    bytes; call again with ``control_ids`` set to ``remaining`` until it
    is empty. Read only: records nothing.

    Args:
        owner: Owner of the audited repository.
        repo: Name of the audited repository.
        host: Git host of owner/repo.
        local_path: Path to the audited checkout.
        control_ids: Limit to these controls (pass the previous page's ``remaining``).
        include_judged: Also return controls that already have a stored PASS candidate.
    """
    import json

    if not _framework_name:
        return json.dumps({"status": "error", "error": "no framework is configured for this server"})
    return await asyncio.to_thread(
        get_judgment_requests_impl,
        owner,
        repo,
        host,
        local_path,
        list(control_ids) if control_ids else None,
        include_judged,
        framework_name=_framework_name,
    )


async def get_pass_candidates(
    owner: str,
    repo: str,
    host: str = "github.com",
    local_path: str = ".",
    control_ids: list[str] | None = None,
    run_id: str | None = None,
    _framework_name: str | None = None,
) -> str:
    """Get the PASS candidates awaiting the operator's confirmation (PENDING, pending.kind = "confirmation").

    Returns JSON: ``procedure`` (the steps for asking the operator; follow
    it), ``candidates`` (one per control whose stored candidate matches the
    current evidence: ``control_id``, ``title``, ``description``, ``files``,
    ``reasoning``, ``cited_evidence``, ``model``, ``model_version``,
    ``source``, ``evidence_digest``, and, with ``run_id``, ``remediation``
    for a document that run wrote), ``ask_user_batch`` (one question per
    candidate), ``awaiting_judgment`` (controls to judge first), and
    ``remaining`` (candidates not on this page). Read only: records
    nothing. Confirm only what the operator names, with
    confirm_pass_candidate.

    Args:
        owner: Owner of the audited repository.
        repo: Name of the audited repository.
        host: Git host of owner/repo.
        local_path: Path to the audited checkout.
        control_ids: Limit to these controls (pass the previous page's ``remaining``).
        run_id: The remediation run whose written documents to mark.
    """
    import json

    if not _framework_name:
        return json.dumps({"status": "error", "error": "no framework is configured for this server"})
    return await asyncio.to_thread(
        get_pass_candidates_impl,
        owner,
        repo,
        host,
        local_path,
        list(control_ids) if control_ids else None,
        run_id,
        framework_name=_framework_name,
    )


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
        cited_evidence: Passages you relied on, copied verbatim from the
            control's files as get_judgment_requests returns them (the same
            content as the control's evidence.llm_consultation.file_contents).
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
    """Register the judgment and PASS-candidate tools bound to the server's framework."""
    if not framework_name:
        logger.debug("No framework name; judgment tools not registered")
        return

    server.add_tool(
        _bind_framework(get_judgment_requests, framework_name),
        name="get_judgment_requests",
        description=(
            "Get what you need to judge the controls awaiting a judgment (PENDING, pending.kind = "
            "llm_judgment): each control's prompt, analysis hints, and the keys of its files in a shared "
            "files map holding exactly the content submit_judgment checks citations against. Pages stay "
            "under 40,000 bytes; call again with control_ids set to 'remaining' until it is empty. "
            "Controls with a stored PASS candidate are left out unless include_judged is true. Records nothing."
        ),
        # The page is sized as this text; a structured copy would wrap and
        # re-escape it, and the client may show that copy instead.
        structured_output=False,
    )

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
        _bind_framework(get_pass_candidates, framework_name),
        name="get_pass_candidates",
        description=(
            "Get the PASS candidates awaiting the operator's confirmation (PENDING, pending.kind = "
            "confirmation) that match the current evidence: each control's title, requirement, files, "
            "the judgment's reasoning, and its cited passages, and, with run_id, whether remediation wrote "
            "the document. Follow the returned procedure: show every candidate, ask about each, and pass "
            "to confirm_pass_candidate only the controls the operator confirms. Records nothing."
        ),
        structured_output=False,
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
