"""Project data confirmation tool.

Records a person's confirmation of project context values (feature 042):
the person's answer for any context key an installed framework defines, or
acceptance of a candidate by its digest. Also confirms a repository's
pending not-applicable claims on the operator side (feature 040) and PASS
candidates from model judgments (feature 041).
"""

import functools
import inspect
from collections.abc import Callable, Mapping
from typing import Annotated, Any

from pydantic import Field

from darnit.config.context_keys import canonical_key, vocabulary
from darnit.config.context_resolve import ANSWER_PLACEHOLDER, DIGEST_PLACEHOLDER
from darnit.config.context_schema import ContextDefinition
from darnit.core.logging import get_logger
from darnit.core.utils import validate_local_path

logger = get_logger("server.tools.project_data")

_LIST_TYPES = ("list", "list_or_path")


def confirmable_definitions(framework_name: str | None) -> dict[str, ContextDefinition]:
    """Context definitions of ``framework_name``, then of every other installed framework.

    Every framework's context lives in the same ``.project/darnit.yaml``, so
    one confirmation tool records values for all of them. A key defined by
    more than one framework keeps its first definition.
    """
    from darnit.config.context_storage import framework_definitions
    from darnit.config.merger import load_framework_by_name
    from darnit.core.registry import get_plugin_registry

    names = [framework_name] if framework_name else []
    names += sorted(name for name in get_plugin_registry().list_frameworks() if name != framework_name)
    definitions: dict[str, ContextDefinition] = {}
    for name in names:
        try:
            loaded = framework_definitions(load_framework_by_name(name))
        except Exception as exc:  # noqa: BLE001 - one broken framework must not hide the others' keys
            logger.warning("Context keys of framework %r are not confirmable: %s", name, exc)
            continue
        for key, definition in loaded.items():
            definitions.setdefault(canonical_key(key), definition)
    return definitions


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
    the keys the frameworks define (research R7).
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
        "Pass the person's answer for a key, or accept the candidate get_pending_data showed them by its digest,",
        "with owner and repo (and host when not github.com) naming the repository:",
        "",
        f"    confirm_project_data(<key>={ANSWER_PLACEHOLDER}, owner=..., repo=...)",
        f'    confirm_project_data(accept_candidates={{"<key>": "{DIGEST_PLACEHOLDER}"}}, owner=..., repo=...)',
        "",
        "Keys:",
    ]
    for key, definition in definitions.items():
        allowed = vocabulary(definition)
        kind = f"one of: {', '.join(allowed)}" if allowed else str(definition.type)
        lines.append(f"- `{key}` ({kind}): {definition.prompt}")
    return "\n".join(lines)


def _result_line(result: Any, accepted: bool) -> list[str]:
    if result.outcome != "confirmed":
        return [f"- {result.key}: refused: {result.reason}", *(f"  - {error}" for error in result.errors)]
    where = (
        f"recorded in {result.file}"
        if result.location == "repository"
        else "recorded operator-side (nothing written to the repository)"
    )
    origin = ((result.record.basis or {}).get("origin") or {}) if result.record else {}
    basis = f"; basis: the candidate from {origin.get('kind')} ({origin.get('method')})" if accepted else ""
    return [f"- {result.key}: confirmed, {where}{basis}"]


def confirm_project_data_impl(
    local_path: str = ".",
    *,
    accept_candidates: dict[str, str] | None = None,
    confirm_not_applicable: list[str] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    host: str | None = None,
    framework_name: str | None = None,
    confirm_pass_candidate: list[str] | None = None,
    **values: Any,
) -> str:
    """Record a person's confirmation of project data values.

    Each value is recorded with who confirmed it and when (feature 042): in
    ``.project/darnit.yaml`` when the operator trusts the repository named by
    ``owner``/``repo``/``host``, otherwise operator-side. Without a repository
    identity from the operator or CI, values are refused.

    Args:
        local_path: Path to the repository
        accept_candidates: ``{key: candidate digest}`` for candidates the person
                         accepted; each is confirmed only if the current
                         candidate still has that digest, with its value and
                         origin recorded as the basis.
        confirm_not_applicable: Control IDs whose pending not-applicable claim
                         the operator confirms. Recorded operator-side, never in the repository.
        owner: Owner of the repository whose values or claims are confirmed.
        repo: Name of the repository whose values or claims are confirmed.
        host: Git host of owner/repo (default github.com).
        framework_name: Framework whose controls the claims name; its context
                         keys come first (see ``confirmable_definitions``).
        confirm_pass_candidate: Control IDs whose PASS candidate (a positive
                         model judgment) the operator confirms for the current
                         evidence. Recorded operator-side, never in the repository.
        **values: The person's answer per context key.

    Returns:
        What was recorded or refused, per key
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

    values = {canonical_key(key): value for key, value in values.items() if value is not None}
    accepted = {canonical_key(key): digest for key, digest in (accept_candidates or {}).items()}

    if not values and not accepted:
        return claims_result or _usage(confirmable_definitions(framework_name))

    from darnit.config.context_writes import WriteResult, record_value_confirmations
    from darnit.config.context_writes import accept_candidates as accept
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.trust.decision import target_from_owner_repo

    try:
        operator_config = resolve_operator_config(resolved_path)
    except OperatorConfigError as e:
        return f"Error: {e}"

    definitions = confirmable_definitions(framework_name)
    target = target_from_owner_repo(owner, repo, host)
    both = sorted(set(values) & set(accepted))
    results = [
        WriteResult(key, "refused", reason="both an answer and an accepted candidate were given; give one")
        for key in both
    ]
    results += record_value_confirmations(
        resolved_path,
        {key: value for key, value in values.items() if key not in both},
        target=target,
        operator=operator_config.config,
        definitions=definitions,
    )
    to_accept = {key: digest for key, digest in accepted.items() if key not in both}
    if to_accept:
        results += accept(
            resolved_path,
            to_accept,
            target=target,
            operator=operator_config.config,
            definitions=definitions,
            owner=owner,
            repo=repo,
        )

    lines = ["Project data:"]
    for result in results:
        lines.extend(_result_line(result, result.key in to_accept))
    if any(result.outcome == "confirmed" for result in results):
        lines.append("")
        lines.append(f'Re-run the audit to see the updated status: `audit_openssf_baseline(local_path="{resolved_path}")`')
    claims_section = f"{claims_result}\n\n" if claims_result else ""
    return claims_section + "\n".join(lines)


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
