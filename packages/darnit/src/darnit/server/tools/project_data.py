"""Project data confirmation tool.

Records a person's confirmation of project context values (feature 042):
the person's answer for a context key the server's framework defines,
acceptance of a candidate by its digest, or review of values stored without
a confirmation. Also confirms a repository's pending not-applicable claims
on the operator side (feature 040) and PASS candidates from model judgments
(feature 041).
"""

import functools
import inspect
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Annotated, Any

from pydantic import Field

from darnit.config.context_keys import canonical_key, vocabulary
from darnit.config.context_resolve import ANSWER_PLACEHOLDER, DIGEST_PLACEHOLDER
from darnit.config.context_schema import ContextDefinition
from darnit.core.logging import get_logger
from darnit.core.utils import validate_local_path

logger = get_logger("server.tools.project_data")

_LIST_TYPES = ("list", "list_or_path")
TOOL_NAME = "confirm_project_data"


def confirmable_definitions(framework_name: str | None, local_path: str = ".") -> dict[str, ContextDefinition]:
    """Context definitions of ``framework_name`` only (contract: "Which server exposes it").

    Without a framework name, the definitions of the framework that applies
    to ``local_path``.
    """
    from darnit.config.context_storage import framework_definitions, get_context_definitions
    from darnit.config.merger import load_framework_by_name

    if not framework_name:
        definitions = get_context_definitions(local_path)
    else:
        try:
            definitions = framework_definitions(load_framework_by_name(framework_name))
        except Exception as exc:  # noqa: BLE001 - a broken framework has no confirmable keys
            logger.warning("Context keys of framework %r are not confirmable: %s", framework_name, exc)
            definitions = {}
    return {canonical_key(key): definition for key, definition in definitions.items()}


def _annotation(definition: ContextDefinition) -> Any:
    if definition.type == "boolean":
        kind: Any = bool
    elif definition.type in _LIST_TYPES:
        kind = list[str] | str
    else:
        kind = str
    description = definition.prompt
    allowed = vocabulary(definition)
    if allowed:
        description += f" One of: {', '.join(allowed)}."
    return Annotated[kind | None, Field(description=description)]


def context_parameters(definitions: Mapping[str, ContextDefinition]) -> list[inspect.Parameter]:
    """One keyword parameter per context key, typed from its definition."""
    return [
        inspect.Parameter(key, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=_annotation(definition))
        for key, definition in definitions.items()
    ]


def with_context_parameters(
    tool: Callable[..., str], definitions: Mapping[str, ContextDefinition]
) -> Callable[..., str]:
    """``tool``, which takes context values as ``**values``, exposed with one parameter per context key.

    The MCP schema is built from the signature, so the tool accepts exactly
    the keys in ``definitions`` (research R7).
    """
    signature = inspect.signature(tool, eval_str=True)
    fixed = [p for p in signature.parameters.values() if p.kind is not inspect.Parameter.VAR_KEYWORD]
    names = {p.name for p in fixed}

    @functools.wraps(tool)
    def exposed(**kwargs: Any) -> str:
        return tool(**kwargs)

    exposed.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[*fixed, *(p for p in context_parameters(definitions) if p.name not in names)]
    )
    return exposed


def _usage(definitions: Mapping[str, ContextDefinition]) -> str:
    lines = [
        "No data values provided.",
        "",
        "Pass the person's answer for a key, accept the candidate get_pending_data showed them by its digest,",
        "or confirm or reject values stored without a confirmation, with owner and repo (and host when not",
        "github.com) naming the repository:",
        "",
        f"    confirm_project_data(<key>={ANSWER_PLACEHOLDER}, owner=..., repo=...)",
        f'    confirm_project_data(accept_candidates={{"<key>": "{DIGEST_PLACEHOLDER}"}}, owner=..., repo=...)',
        '    confirm_project_data(confirm_stored=["<key>"], reject_stored=["<key>"], owner=..., repo=...)',
        "",
        "Keys:",
    ]
    for key, definition in definitions.items():
        allowed = vocabulary(definition)
        kind = f"one of: {', '.join(allowed)}" if allowed else str(definition.type)
        lines.append(f"- `{key}` ({kind}): {definition.prompt}")
    return "\n".join(lines)


def _result_lines(result: Any) -> list[str]:
    if result.outcome == "deleted":
        return [f"- {result.key}: rejected, deleted from {result.file}"]
    if result.outcome == "edit_required":
        return [f"- {result.key}: edit required: {result.file}:{result.reason}"]
    if result.outcome != "confirmed":
        return [f"- {result.key}: refused: {result.reason}", *(f"  - {error}" for error in result.errors)]
    record = result.record
    where = (
        f"confirmed (in-repository), recorded in {result.file}"
        if result.location == "repository"
        else "confirmed (operator-side), nothing written to the repository"
    )
    details = f"; by {record.confirmed_by}, last validated {record.last_validated}"
    if record.expires_at:
        details += f", expires {record.expires_at}"
    origin = (record.basis or {}).get("origin") or {}
    if origin:
        details += f"; basis: {origin.get('kind')} ({origin.get('method')})"
    return [f"- {result.key}: {where}{details}"]


def _parse_expiry(text: Any, now: datetime) -> datetime:
    if isinstance(text, datetime):
        moment = text
    elif isinstance(text, date):
        moment = datetime(text.year, text.month, text.day)
    else:
        try:
            moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"expires_at {text!r} is not a date (YYYY-MM-DD) or ISO 8601 time") from None
    moment = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    if moment <= now:
        raise ValueError(f"expires_at {text!r} is not in the future")
    return moment


def confirm_project_data_impl(
    local_path: str = ".",
    *,
    accept_candidates: dict[str, str] | None = None,
    confirm_stored: list[str] | None = None,
    reject_stored: list[str] | None = None,
    expires_at: dict[str, str] | None = None,
    confirm_not_applicable: list[str] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    host: str | None = None,
    framework_name: str | None = None,
    confirm_pass_candidate: list[str] | None = None,
    **values: Any,
) -> str:
    """Record a person's confirmation of project data values.

    Each value is recorded with who confirmed it, when, on what basis, when
    it was last validated, and an optional expiry (feature 042): in
    ``.project/darnit.yaml`` when the operator trusts the repository named by
    ``owner``/``repo``/``host``, otherwise operator-side. Without ``owner``
    and ``repo`` every value is refused.

    Args:
        local_path: Path to the repository
        accept_candidates: ``{key: candidate digest}`` for candidates the person
                         accepted; each is confirmed only if the current
                         candidate still has that digest, with its value and
                         origin recorded as the basis.
        confirm_stored: Keys whose value stored in ``.project/`` the person
                         confirms (review of stored values).
        reject_stored: Keys whose stored value the person rejects: deleted
                         from ``.project/darnit.yaml`` of a trusted repository;
                         a ``.project/project.yaml`` value is reported with its
                         file and field and left unchanged.
        expires_at: ``{key: date}`` expiry recorded with a key's confirmation.
        confirm_not_applicable: Control IDs whose pending not-applicable claim
                         the operator confirms. Recorded operator-side, never in the repository.
        owner: Owner of the repository whose values or claims are confirmed.
        repo: Name of the repository whose values or claims are confirmed.
        host: Git host of owner/repo (default github.com).
        framework_name: Framework whose context keys and controls apply.
        confirm_pass_candidate: Control IDs whose PASS candidate (a positive
                         model judgment) the operator confirms for the current
                         evidence. Recorded operator-side, never in the repository.
        **values: The person's answer per context key.

    Returns:
        What was recorded, rejected, or refused, per key
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    claims_result = (
        confirm_not_applicable_impl(
            resolved_path, confirm_not_applicable, owner=owner, repo=repo, host=host, framework_name=framework_name
        )
        if confirm_not_applicable
        else ""
    )
    if confirm_pass_candidate:
        candidates_result = confirm_pass_candidates_impl(
            resolved_path, confirm_pass_candidate, owner=owner, repo=repo, host=host, framework_name=framework_name
        )
        claims_result = f"{claims_result}\n\n{candidates_result}" if claims_result else candidates_result

    requests = {
        "answer": {canonical_key(key): value for key, value in values.items() if value is not None},
        "accept": {canonical_key(key): digest for key, digest in (accept_candidates or {}).items()},
        "confirm_stored": dict.fromkeys(canonical_key(key) for key in confirm_stored or ()),
        "reject_stored": dict.fromkeys(canonical_key(key) for key in reject_stored or ()),
    }
    expiries = {canonical_key(key): text for key, text in (expires_at or {}).items()}

    if not any(requests.values()) and not expiries:
        return claims_result or _usage(confirmable_definitions(framework_name, resolved_path))

    from darnit.config.context_writes import (
        WriteResult,
        confirm_stored_values,
        record_value_confirmations,
        reject_stored_value,
    )
    from darnit.config.context_writes import accept_candidates as accept
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.trust.decision import target_from_owner_repo

    results: list[WriteResult] = []
    requested = [key for keys in requests.values() for key in keys]
    if not (owner and repo):
        results = [
            WriteResult(
                key,
                "refused",
                reason="name the repository: owner and repo (and host when not github.com) are required",
            )
            for key in dict.fromkeys([*requested, *expiries])
        ]
        return _report(claims_result, results)

    try:
        operator_config = resolve_operator_config(resolved_path)
    except OperatorConfigError as e:
        return f"Error: {e}"

    definitions = confirmable_definitions(framework_name, resolved_path)
    target = target_from_owner_repo(owner, repo, host)
    now = datetime.now(UTC)

    refused: dict[str, str] = {}
    for key in sorted({key for key in requested if requested.count(key) > 1}):
        refused[key] = (
            "more than one of an answer, accept_candidates, confirm_stored, and reject_stored was given for it; "
            "give one"
        )
    confirming = set(requests["answer"]) | set(requests["accept"]) | set(requests["confirm_stored"])
    expiry: dict[str, datetime] = {}
    for key, text in expiries.items():
        if key not in confirming:
            refused.setdefault(key, "expires_at was given for a key that is not being confirmed")
            continue
        try:
            expiry[key] = _parse_expiry(text, now)
        except ValueError as exc:
            refused.setdefault(key, str(exc))
    results = [WriteResult(key, "refused", reason=reason) for key, reason in refused.items()]

    def wanted(kind: str) -> dict[str, Any]:
        return {key: value for key, value in requests[kind].items() if key not in refused}

    common = {"target": target, "operator": operator_config.config, "definitions": definitions}
    results += record_value_confirmations(resolved_path, wanted("answer"), expires_at=expiry, now=now, **common)
    if wanted("accept"):
        results += accept(resolved_path, wanted("accept"), owner=owner, repo=repo, expires_at=expiry, now=now, **common)
    if wanted("confirm_stored"):
        results += confirm_stored_values(
            resolved_path, list(wanted("confirm_stored")), expires_at=expiry, now=now, **common
        )
    for key in wanted("reject_stored"):
        results += reject_stored_value(resolved_path, key, **common)
    return _report(claims_result, results)


def _report(claims_result: str, results: list[Any]) -> str:
    lines = ["Project data:"]
    for result in results:
        lines.extend(_result_lines(result))
    if any(result.outcome in ("confirmed", "deleted") for result in results):
        lines.append("")
        lines.append("Re-run the audit to see the updated status.")
    claims_section = f"{claims_result}\n\n" if claims_result else ""
    return claims_section + "\n".join(lines)


def stored_unconfirmed(
    local_path: str, definitions: Mapping[str, ContextDefinition] | None = None, *, target: str | None = None
) -> list[dict[str, Any]]:
    """Values stored in ``.project/`` that no confirmation matches, with their locations (FR-010). Writes nothing."""
    from darnit.config.context_resolve import resolve_context

    resolved = resolve_context(local_path, definitions, target=target, detect=False)
    return [{"key": v.key, "value": v.value, "location": v.location} for v in resolved.stored_unconfirmed()]


_NEUTRAL_DESCRIPTION = """Record a person's confirmation of this framework's project context values.
Only on the person's explicit instruction; never pass a detected value the person has not
confirmed, and never type a candidate's value as an answer. Do not edit .project/ files by hand.

`owner` and `repo` (and `host` when not github.com) are required: they name the repository.
Values are recorded in .project/darnit.yaml when the operator trusts that repository,
otherwise operator-side with nothing written to the repository.

- One parameter per context key this framework defines: the person's answer. An enum key
  accepts only its listed values.
- `accept_candidates`: {key: candidate digest} for a candidate shown to the person that the
  person accepted; confirmed only if its digest still matches.
- `confirm_stored` / `reject_stored`: keys whose value stored in .project/ without a
  confirmation the person confirms or rejects. A rejected .project/darnit.yaml value is
  deleted; a .project/project.yaml value is reported with the field to edit and left unchanged.
- `expires_at`: {key: date} optional expiry recorded with a key's confirmation.

Call forms (placeholders only):
confirm_project_data(<key>=<the person's answer>, owner=..., repo=...)
confirm_project_data(accept_candidates={"<key>": "<candidate digest if the person accepts it>"}, owner=..., repo=...)
confirm_project_data(confirm_stored=["<key>"], reject_stored=["<key>"], owner=..., repo=...)
"""


def neutral_confirm_tool(framework_name: str) -> Callable[..., str]:
    """The framework-neutral ``confirm_project_data`` bound to ``framework_name``: context values only."""

    def confirm_project_data(
        local_path: str = ".",
        *,
        accept_candidates: dict[str, str] | None = None,
        confirm_stored: list[str] | None = None,
        reject_stored: list[str] | None = None,
        expires_at: dict[str, str] | None = None,
        owner: str | None = None,
        repo: str | None = None,
        host: str | None = None,
        **values: Any,
    ) -> str:
        return confirm_project_data_impl(
            local_path,
            accept_candidates=accept_candidates,
            confirm_stored=confirm_stored,
            reject_stored=reject_stored,
            expires_at=expires_at,
            owner=owner,
            repo=repo,
            host=host,
            framework_name=framework_name,
            **values,
        )

    return with_context_parameters(confirm_project_data, confirmable_definitions(framework_name))


def register_confirmation_tool(server: Any, framework_name: str | None, defined_tools: Iterable[str]) -> None:
    """Register the neutral ``confirm_project_data`` unless the framework's TOML defines its own.

    A framework with no context keys gets no tool: it would have nothing to confirm.
    """
    if not framework_name or TOOL_NAME in set(defined_tools):
        return
    if not confirmable_definitions(framework_name):
        return
    server.add_tool(neutral_confirm_tool(framework_name), name=TOOL_NAME, description=_NEUTRAL_DESCRIPTION)
    logger.debug("Registered the neutral %s for framework %s", TOOL_NAME, framework_name)


def confirm_not_applicable_impl(
    local_path: str,
    control_ids: list[str],
    *,
    owner: str | None,
    repo: str | None,
    host: str | None = None,
    framework_name: str | None,
) -> str:
    """Confirm pending not-applicable claims in the operator-side store (feature 040, FR-019, FR-019a).

    Each confirmation is bound to the repository the operator names, the
    control, the claim, and a digest of the claim's current reason and
    evidence; it lapses on expiry or when either changes. A claim that
    evidence contradicts is not confirmed.
    """
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.tools.audit import prepare_claim_confirmations
    from darnit.trust.confirmations import record_confirmation
    from darnit.trust.decision import decide_trust, target_from_owner_repo

    if not framework_name:
        return "Error: no framework is configured for confirming claims."
    try:
        operator_config = resolve_operator_config(local_path)
    except OperatorConfigError as e:
        return f"Error: {e}"

    target = target_from_owner_repo(owner, repo, host)
    decision = decide_trust(target, operator_config.config, local_path)
    identity = decision.repository
    if identity is None or not identity.trusted_eligible:
        return (
            "Error: name the repository whose claims you are confirming (owner, repo, and host when "
            "not github.com). A checkout's own remotes cannot identify it."
        )

    try:
        prepared = prepare_claim_confirmations(
            local_path, control_ids, framework_name, operator_config.config, owner, repo, target
        )
    except ValueError as e:
        return f"Error: {e}"

    lines = [f"Not-applicable claims for {identity.canonical}:"]
    for control_id in control_ids:
        entry = prepared.get(control_id)
        if entry is None:
            lines.append(f"- {control_id}: no not-applicable claim found; nothing confirmed")
            continue
        claim, digest, contradiction = entry
        if contradiction:
            lines.append(f"- {control_id}: not confirmed; {contradiction['summary']}")
            continue
        try:
            confirmation = record_confirmation(
                identity.canonical, control_id, claim.claim, digest, operator_config.config, checkout=local_path
            )
        except (OSError, ValueError) as e:
            lines.append(f"- {control_id}: not confirmed; {e}")
            continue
        lines.append(
            f"- {control_id}: confirmed by {confirmation.confirmed_by} until {confirmation.expires_at} "
            f"(claim in {claim.location}: {claim.reason or 'no reason given'})"
        )
    lines.append("")
    lines.append(
        "A confirmation applies until it expires or the claim or its evidence changes. Re-run the audit to see it."
    )
    return "\n".join(lines)


def confirm_pass_candidates_impl(
    local_path: str,
    control_ids: list[str],
    *,
    owner: str | None,
    repo: str | None,
    host: str | None = None,
    framework_name: str | None,
) -> str:
    """Confirm stored PASS candidates in the operator-side store (feature 041, FR-011, FR-012).

    Each confirmation is bound to the repository the operator names, the
    control, claim ``pass_candidate``, and the evidence digest of the
    control's judged content as an audit gathers it now. Only a stored
    candidate for exactly that evidence can be confirmed; the confirmation
    lapses on expiry or when the content or the control's rubric changes.
    """
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.tools.audit import judgment_consultations
    from darnit.trust.confirmations import load_candidates, record_confirmation
    from darnit.trust.decision import decide_trust, target_from_owner_repo
    from darnit.trust.judgments import PASS_CANDIDATE_CLAIM, evidence_digest

    if not framework_name:
        return "Error: no framework is configured for confirming PASS candidates."
    try:
        operator_config = resolve_operator_config(local_path)
    except OperatorConfigError as e:
        return f"Error: {e}"

    target = target_from_owner_repo(owner, repo, host)
    identity = decide_trust(target, operator_config.config, local_path).repository
    if identity is None or not identity.trusted_eligible:
        return (
            "Error: name the repository whose PASS candidates you are confirming (owner, repo, and host when "
            "not github.com). A checkout's own remotes cannot identify it."
        )

    try:
        consultations = judgment_consultations(local_path, control_ids, framework_name, operator_config, owner, repo, target)
    except Exception as e:  # noqa: BLE001 - reported to the operator, nothing confirmed
        return f"Error: could not re-gather the evidence: {e}"

    candidates = load_candidates(identity.canonical, checkout=local_path)
    lines = [f"PASS candidates for {identity.canonical}:"]
    for control_id in control_ids:
        consultation = consultations.get(control_id)
        if consultation is None:
            lines.append(f"- {control_id}: does not reach a model judgment step; nothing confirmed")
            continue
        digest = evidence_digest(consultation)
        candidate = next(
            (
                c
                for c in candidates
                if c.control_id == control_id and c.claim == PASS_CANDIDATE_CLAIM and c.evidence_digest == digest
            ),
            None,
        )
        if candidate is None:
            lines.append(f"- {control_id}: no PASS candidate for the current evidence; nothing confirmed")
            continue
        try:
            confirmation = record_confirmation(
                identity.canonical,
                control_id,
                PASS_CANDIDATE_CLAIM,
                digest,
                operator_config.config,
                checkout=local_path,
            )
        except (OSError, ValueError) as e:
            lines.append(f"- {control_id}: not confirmed; {e}")
            continue
        lines.append(
            f"- {control_id}: confirmed by {confirmation.confirmed_by} until {confirmation.expires_at} "
            f"(judgment by {candidate.candidate.get('model') or 'unknown model'}: "
            f"{candidate.candidate.get('reasoning', '')})"
        )
    lines.append("")
    lines.append(
        "A confirmation applies until it expires or the judged content or the control's rubric changes. "
        "Re-run the audit to see it."
    )
    return "\n".join(lines)
