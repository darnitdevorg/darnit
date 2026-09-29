"""The only writer of project context values and confirmation records (feature 042, research R1, R3, R10).

A confirmation is written into the repository's ``.project/darnit.yaml``
(the value under ``context:`` and the record under ``confirmations:``) when
the operator trusts the target repository; otherwise it is recorded
operator-side (feature 040 store, claim ``context_value``) and nothing is
written into the repository. Every write is refused, with the errors, when
``.project/project.yaml`` or ``.project/darnit.yaml`` is present but invalid.
``.project/project.yaml`` is never written here.

Callers: explicit confirmation by a person only (``confirm_project_data``,
answers typed into ``darnit run``) and the ``init_project_config`` tool.
"""

from __future__ import annotations

import getpass
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from darnit.config.context_keys import (
    canonical_key,
    coerce_value,
    in_vocabulary,
    legacy_names,
    normalize_value,
    value_digest,
    vocabulary,
)
from darnit.config.context_schema import ConfirmationRecord, ContextDefinition
from darnit.config.loader import (
    PROJECT_DIR,
    get_default_extension,
    load_project_config_checked,
    update_extension_file,
)
from darnit.core.logging import get_logger

if TYPE_CHECKING:
    from darnit.config.operator.schema import OperatorConfig

logger = get_logger("config.context_writes")

EXTENSION_FILE = f"{PROJECT_DIR}/{get_default_extension().filename}"
PROJECT_FILE = f"{PROJECT_DIR}/project.yaml"

Outcome = Literal["confirmed", "refused", "deleted", "edit_required", "created"]


@dataclass(frozen=True)
class WriteResult:
    """What one write did for one key.

    ``location`` is ``repository`` or ``operator`` for a confirmation;
    ``file`` is the repository file written or to edit; for
    ``edit_required`` ``reason`` names the field.
    """

    key: str
    outcome: Outcome
    location: Literal["repository", "operator"] | None = None
    file: str | None = None
    reason: str | None = None
    record: ConfirmationRecord | None = None
    errors: tuple[str, ...] = ()


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _refuse_invalid(local_path: str, key: str) -> WriteResult | None:
    files = load_project_config_checked(local_path)
    if not files.invalid:
        return None
    return WriteResult(
        key,
        "refused",
        reason="a project file is present but invalid; fix it before recording values",
        errors=tuple(files.errors),
    )


def _definitions(local_path: str, definitions: Mapping[str, ContextDefinition] | None) -> dict[str, ContextDefinition]:
    if definitions is None:
        from darnit.config.context_storage import get_context_definitions

        definitions = get_context_definitions(local_path)
    return {canonical_key(k): d for k, d in definitions.items()}


def _plain(value: Any) -> Any:
    return list(value) if isinstance(value, (list, tuple)) else value


def _set_value_and_record(key: str, value: Any, record: dict[str, Any]):
    def mutate(data: Any) -> None:
        context = data.get("context")
        if not isinstance(context, dict):
            context = data["context"] = {}
        for legacy in legacy_names(key):
            context.pop(legacy, None)
        context[key] = _plain(value)
        confirmations = data.get("confirmations")
        if not isinstance(confirmations, dict):
            confirmations = data["confirmations"] = {}
        confirmations[key] = record

    return mutate


def _repository_record(
    local_path: str,
    key: str,
    digest: str,
    confirmed_by: str,
    now: datetime,
    expires_at: datetime | None,
    basis: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The in-repository record.

    Re-confirming the same value keeps ``confirmed_at`` and ``confirmed_by``;
    a recorded ``expires_at`` is kept unless a new one is given.
    """
    files = load_project_config_checked(local_path)
    existing = ((files.extension.data or {}).get("confirmations") or {}).get(key)
    existing = existing if isinstance(existing, dict) else {}
    project_expiry = existing.get("expires_at")
    if existing.get("value_digest") != digest:
        existing = {}
    record: dict[str, Any] = {
        "value_digest": digest,
        "confirmed_by": existing.get("confirmed_by", confirmed_by),
        "confirmed_at": str(existing.get("confirmed_at") or _timestamp(now)),
        "last_validated": _timestamp(now),
    }
    if expires_at is not None:
        record["expires_at"] = _timestamp(expires_at)
    elif project_expiry is not None:
        record["expires_at"] = project_expiry
    if basis:
        record["basis"] = {"value": _plain(basis.get("value")), "origin": dict(basis.get("origin") or {})}
    return record


def record_value_confirmation(
    local_path: str,
    key: str,
    value: Any,
    *,
    target: str | None,
    operator: OperatorConfig,
    definitions: Mapping[str, ContextDefinition] | None = None,
    basis: Mapping[str, Any] | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> WriteResult:
    """Record a person's confirmation of ``value`` for ``key`` (FR-009, FR-011).

    Args:
        local_path: Repository root.
        key: Context key (legacy names are accepted and written canonically).
        value: The confirmed value.
        target: Repository identity the operator named; decides the location.
        operator: Operator configuration (trust list, identity).
        definitions: Context definitions (default: the framework's).
        basis: The candidate the confirmation was based on: ``{"value", "origin"}``.
        expires_at: Optional expiry recorded with the confirmation.
        now: Current time.
        env: Environment CI metadata is read from (default: the process environment).
    """
    key = canonical_key(key)
    refused = _refuse_invalid(local_path, key)
    if refused is not None:
        return refused

    definition = _definitions(local_path, definitions).get(key)
    if definition is None:
        return WriteResult(key, "refused", reason=f"{key!r} is not a context key the framework defines")
    try:
        value = normalize_value(key, coerce_value(definition, value))
    except ValueError as exc:
        return WriteResult(key, "refused", reason=str(exc))
    if value is None:
        return WriteResult(key, "refused", reason="no value given")
    if not in_vocabulary(value, definition):
        return WriteResult(
            key, "refused", reason=f"{value!r} is not an allowed value; allowed: {', '.join(vocabulary(definition))}"
        )

    from darnit.trust.decision import decide_trust

    now = now or datetime.now(UTC)
    digest = value_digest(key, value)
    confirmed_by = operator.operator.identity or getpass.getuser()
    decision = decide_trust(target, operator, local_path, env)

    if decision.trusted:
        record = _repository_record(local_path, key, digest, confirmed_by, now, expires_at, basis)
        update_extension_file(local_path, _set_value_and_record(key, value, record))
        return WriteResult(
            key,
            "confirmed",
            location="repository",
            file=EXTENSION_FILE,
            record=ConfirmationRecord.model_validate({**record, "location": "repository"}),
        )

    identity = decision.repository
    if identity is None or not identity.trusted_eligible:
        return WriteResult(
            key,
            "refused",
            reason=(
                "name the repository (owner, repo, and host when not github.com); "
                "a checkout's own remotes cannot identify it"
            ),
        )

    from darnit.trust.confirmations import record_context_confirmation

    origin = dict(basis["origin"]) if basis and basis.get("origin") else None
    try:
        confirmation = record_context_confirmation(
            identity.canonical,
            key,
            digest,
            value,
            origin,
            operator,
            expires_at=expires_at,
            checkout=local_path,
            now=now,
        )
    except (OSError, ValueError) as exc:
        return WriteResult(key, "refused", reason=str(exc))
    return WriteResult(
        key,
        "confirmed",
        location="operator",
        record=ConfirmationRecord(
            value_digest=digest,
            confirmed_by=confirmation.confirmed_by,
            confirmed_at=confirmation.confirmed_at,
            last_validated=confirmation.confirmed_at,
            expires_at=confirmation.expires_at,
            basis=dict(basis) if basis else None,
            location="operator",
        ),
    )


def record_value_confirmations(
    local_path: str,
    values: Mapping[str, Any],
    *,
    target: str | None,
    operator: OperatorConfig,
    bases: Mapping[str, Mapping[str, Any]] | None = None,
    definitions: Mapping[str, ContextDefinition] | None = None,
    expires_at: Mapping[str, datetime] | None = None,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> list[WriteResult]:
    """Record confirmations of several keys; each key succeeds or is refused on its own."""
    definitions = _definitions(local_path, definitions)
    return [
        record_value_confirmation(
            local_path,
            key,
            value,
            target=target,
            operator=operator,
            definitions=definitions,
            basis=(bases or {}).get(key),
            expires_at=(expires_at or {}).get(key),
            now=now,
            env=env,
        )
        for key, value in values.items()
        if value is not None
    ]


def accept_candidates(
    local_path: str,
    digests: Mapping[str, str],
    *,
    target: str | None,
    operator: OperatorConfig,
    definitions: Mapping[str, ContextDefinition] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    expires_at: Mapping[str, datetime] | None = None,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> list[WriteResult]:
    """Confirm each key's current candidate if its digest still matches (research R6).

    Detection runs again; the candidate the person accepted is recorded only
    when the digest of the current candidate equals the one given, with the
    candidate's value and origin as the basis. Otherwise nothing is written
    for that key.
    """
    from darnit.config.context_resolve import resolve_context
    from darnit.config.context_schema import Standing

    definitions = _definitions(local_path, definitions)
    wanted = {canonical_key(key): digest for key, digest in digests.items()}
    known = {key: definitions[key] for key in wanted if key in definitions}
    resolved = resolve_context(
        local_path, known, target=target, operator=operator, owner=owner, repo=repo, now=now, env=env
    )

    results = []
    for key, digest in wanted.items():
        if key not in known:
            results.append(WriteResult(key, "refused", reason=f"{key!r} is not a context key the framework defines"))
            continue
        current = resolved.get(key)
        if current is None or current.value is None or current.standing not in (Standing.CANDIDATE, Standing.CONCLUDED):
            results.append(WriteResult(key, "refused", reason="no candidate to accept; ask the person for the value"))
            continue
        if value_digest(key, current.value) != digest:
            results.append(
                WriteResult(
                    key,
                    "refused",
                    reason="the candidate changed since it was shown (digest mismatch); show the current one and ask again",
                )
            )
            continue
        origin = current.origin.model_dump(mode="json", exclude_none=True) if current.origin else {}
        results.append(
            record_value_confirmation(
                local_path,
                key,
                current.value,
                target=target,
                operator=operator,
                definitions=definitions,
                basis={"value": current.value, "origin": origin},
                expires_at=(expires_at or {}).get(key),
                now=now,
                env=env,
            )
        )
    return results


def confirm_stored_values(
    local_path: str,
    keys: list[str],
    *,
    target: str | None,
    operator: OperatorConfig,
    definitions: Mapping[str, ContextDefinition] | None = None,
    expires_at: Mapping[str, datetime] | None = None,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> list[WriteResult]:
    """Confirm the value currently stored in ``.project/`` for each key (review, FR-010).

    The basis is the stored value with the origin it was read with
    (``stored_unconfirmed``, or ``expired_confirmation`` for a lapsed record).
    """
    from darnit.config.context_resolve import resolve_context
    from darnit.config.context_schema import OriginKind

    definitions = _definitions(local_path, definitions)
    wanted = [canonical_key(key) for key in keys]
    resolved = resolve_context(
        local_path,
        {key: definitions[key] for key in wanted if key in definitions},
        target=target,
        operator=operator,
        detect=False,
        now=now,
        env=env,
    )

    results = []
    for key in wanted:
        if key not in definitions:
            results.append(WriteResult(key, "refused", reason=f"{key!r} is not a context key the framework defines"))
            continue
        current = resolved.get(key)
        if current is None or current.value is None or current.location is None:
            results.append(WriteResult(key, "refused", reason="no stored value"))
            continue
        origin = (
            current.origin.model_dump(mode="json", exclude_none=True)
            if current.origin
            else {"kind": OriginKind.STORED_UNCONFIRMED.value, "method": current.location}
        )
        results.append(
            record_value_confirmation(
                local_path,
                key,
                current.value,
                target=target,
                operator=operator,
                definitions=definitions,
                basis={"value": current.value, "origin": origin},
                expires_at=(expires_at or {}).get(key),
                now=now,
                env=env,
            )
        )
    return results


def reject_stored_value(
    local_path: str,
    key: str,
    *,
    target: str | None,
    operator: OperatorConfig,
    definitions: Mapping[str, ContextDefinition] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[WriteResult]:
    """Reject the value stored for ``key`` (review, FR-010).

    A value in ``.project/darnit.yaml`` is deleted when the operator trusts
    the target repository; otherwise nothing is written and the result names
    the field for the person to edit. A value in ``.project/project.yaml`` is
    never edited: the result names its file and field.
    """
    from darnit.config.context_resolve import resolve_context

    key = canonical_key(key)
    definitions = _definitions(local_path, definitions)
    if key not in definitions:
        return [WriteResult(key, "refused", reason=f"{key!r} is not a context key the framework defines")]
    refused = _refuse_invalid(local_path, key)
    if refused is not None:
        return [refused]

    def location() -> str | None:
        resolved = resolve_context(local_path, {key: definitions[key]}, operator=operator, detect=False, env=env)
        return resolved.get(key).location

    stored = location()
    if stored is None:
        return [WriteResult(key, "refused", reason="no stored value")]
    if stored.startswith(f"{PROJECT_FILE}:"):
        return [WriteResult(key, "edit_required", file=PROJECT_FILE, reason=stored.split(":", 1)[1])]

    from darnit.trust.decision import decide_trust

    if not decide_trust(target, operator, local_path, env).trusted:
        return [
            WriteResult(
                key,
                "refused",
                reason=(
                    "the operator does not trust this repository, so darnit writes nothing to it; "
                    f"edit {stored} yourself"
                ),
            )
        ]

    results = [delete_stored_value(local_path, key)]
    remaining = location()
    if results[0].outcome == "deleted" and remaining is not None and remaining.startswith(f"{PROJECT_FILE}:"):
        results.append(WriteResult(key, "edit_required", file=PROJECT_FILE, reason=remaining.split(":", 1)[1]))
    return results


def delete_stored_value(local_path: str, key: str) -> WriteResult:
    """Remove a stored value (and its record) from ``.project/darnit.yaml``.

    A value that lives in ``.project/project.yaml`` is not edited: the result
    names the file and field for the person to change (FR-010).
    """
    key = canonical_key(key)
    refused = _refuse_invalid(local_path, key)
    if refused is not None:
        return refused

    files = load_project_config_checked(local_path)
    extension = files.extension.data or {}
    context = extension.get("context") if isinstance(extension.get("context"), dict) else {}
    names = [name for name in (key, *legacy_names(key)) if name in context]
    ci = extension.get("ci")
    in_ci = key == "ci_provider" and isinstance(ci, dict) and ci.get("provider") is not None
    if names or in_ci or key in (extension.get("confirmations") or {}):

        def mutate(data: Any) -> None:
            for name in names:
                data["context"].pop(name, None)
            if in_ci:
                data["ci"].pop("provider", None)
            if isinstance(data.get("confirmations"), dict):
                data["confirmations"].pop(key, None)

        update_extension_file(local_path, mutate)
        return WriteResult(key, "deleted", file=EXTENSION_FILE)

    security = (files.project.data or {}).get("security")
    if key == "security_contact" and isinstance(security, dict) and security.get("contact") is not None:
        return WriteResult(key, "edit_required", file=PROJECT_FILE, reason="security.contact")
    return WriteResult(key, "refused", reason="no stored value")


def create_extension_file(local_path: str) -> WriteResult:
    """Create an empty ``.project/darnit.yaml`` when ``.project/`` does not exist."""
    if os.path.exists(os.path.join(local_path, PROJECT_DIR)):
        return WriteResult("", "refused", reason=f"{PROJECT_DIR}/ already exists")
    update_extension_file(local_path, lambda data: None)
    return WriteResult("", "created", file=EXTENSION_FILE)
