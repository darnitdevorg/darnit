"""Resolve project context values with their standing (feature 042, research R2 to R5).

Every consumer of context reads through :func:`resolve_context`, and only
from :meth:`ResolvedContext.usable`: confirmed values plus values of
``auto_detect = true`` keys concluded by a detection that ran to completion
in this run. A value stored without a matching confirmation record, or a
detected value of a user-judgment key, is a candidate: it may be shown to a
person, labelled with its origin, and is never consumed as the key's value.

Reading never writes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from darnit.config.context_keys import canonical_key, normalize_value, value_digest
from darnit.config.context_schema import (
    ConfirmationRecord,
    ContextDefinition,
    ContextValue,
    Origin,
    OriginKind,
    ResolvedValue,
    Standing,
)
from darnit.config.loader import PROJECT_DIR, ProjectFiles, load_project_config_checked
from darnit.core.logging import get_logger

if TYPE_CHECKING:
    from darnit.config.operator.schema import OperatorConfig

logger = get_logger("config.context_resolve")

EXTENSION_FILE = f"{PROJECT_DIR}/darnit.yaml"
PROJECT_FILE = f"{PROJECT_DIR}/project.yaml"
DEFAULT_AUTO_ACCEPT_CONFIDENCE = 0.8

CANDIDATE_LABEL = "UNCONFIRMED candidate - show it to the person; do not confirm without their answer"
ANSWER_PLACEHOLDER = "<the person's answer>"
DIGEST_PLACEHOLDER = "<candidate digest if the person accepts it>"


def candidate_payload(resolved: ResolvedValue | None) -> dict[str, Any] | None:
    """A value no person has confirmed, as data to show one (FR-013): value, origin, digest, label.

    The digest is what ``confirm_project_data(accept_candidates=...)`` checks
    the current candidate against.
    """
    if resolved is None or resolved.value is None or resolved.standing not in (Standing.CANDIDATE, Standing.CONCLUDED):
        return None
    return {
        "value": resolved.value,
        "origin": resolved.origin.model_dump(mode="json") if resolved.origin else None,
        "digest": value_digest(resolved.key, resolved.value),
        "label": CANDIDATE_LABEL,
    }


def confirmation_template(key: str, *, candidate: bool) -> str:
    """The ``confirm_project_data`` call(s) for ``key`` with placeholders only, never a value (FR-013)."""
    answer = f"confirm_project_data({key}={ANSWER_PLACEHOLDER}, owner=..., repo=...)"
    if not candidate:
        return answer
    accept = f'confirm_project_data(accept_candidates={{"{key}": "{DIGEST_PLACEHOLDER}"}}, owner=..., repo=...)'
    return f"{accept}  OR  {answer}"


@dataclass
class ResolvedContext:
    """Every defined key's value and standing for one run."""

    values: dict[str, ResolvedValue]
    definitions: dict[str, ContextDefinition] = field(default_factory=dict)

    def get(self, key: str) -> ResolvedValue | None:
        return self.values.get(canonical_key(key))

    def usable(self) -> dict[str, Any]:
        """The only mapping consumers may read values from."""
        usable: dict[str, Any] = {}
        for key, resolved in self.values.items():
            if resolved.standing is Standing.CONFIRMED or (
                resolved.standing is Standing.CONCLUDED and self._detectable(key)
            ):
                usable[key] = resolved.value
        return usable

    def unusable_keys(self) -> frozenset[str]:
        """Defined keys without a usable value; remediation refuses to read them (FR-007)."""
        return frozenset(self.values) - self.usable().keys()

    def pending(self, control_ids: Iterable[str] | None = None) -> list[ResolvedValue]:
        """Candidate and unknown keys that affect a loaded control (or one of ``control_ids``)."""
        wanted = set(control_ids) if control_ids else None
        pending = []
        for key, resolved in self.values.items():
            if resolved.standing not in (Standing.CANDIDATE, Standing.UNKNOWN):
                continue
            affects = self.definitions[key].affects if key in self.definitions else []
            if wanted is not None:
                affects = [c for c in affects if c in wanted]
            if affects:
                pending.append(resolved)
        return pending

    def stored_unconfirmed(self) -> list[ResolvedValue]:
        """Stored values no confirmation record matches (the review list, FR-010)."""
        return [
            v
            for v in self.values.values()
            if v.standing is Standing.CANDIDATE
            and v.origin is not None
            and v.origin.kind is OriginKind.STORED_UNCONFIRMED
        ]

    def _detectable(self, key: str) -> bool:
        definition = self.definitions.get(key)
        return definition is not None and definition.auto_detect


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def lapsed(record: ConfirmationRecord, definition: ContextDefinition | None, now: datetime) -> bool:
    """Whether a confirmation has lapsed: the earliest of ``expires_at`` and ``last_validated + validity_days``."""
    last_validated = _parse_time(record.last_validated)
    if last_validated is None:
        return True
    limits = []
    if record.expires_at is not None:
        expires = _parse_time(record.expires_at)
        if expires is None:
            return True
        limits.append(expires)
    if definition is not None and definition.validity_days:
        limits.append(last_validated + timedelta(days=definition.validity_days))
    return any(now >= limit for limit in limits)


def _stored_values(files: ProjectFiles) -> dict[str, list[tuple[Any, str]]]:
    """Stored values per canonical key, each with the file and field it was read from.

    darnit's extension file comes first, canonical names before legacy ones.
    """
    stored: dict[str, list[tuple[Any, str]]] = {}

    def add(key: str, raw: Any, location: str) -> None:
        if isinstance(raw, dict) and "value" in raw and "source" in raw:
            raw = raw["value"]
        value = normalize_value(key, raw)
        if value is not None:
            stored.setdefault(key, []).append((value, location))

    extension = files.extension.data if files.extension.state == "valid" else None
    if extension:
        context = extension.get("context")
        if isinstance(context, dict):
            names = sorted(context, key=lambda name: canonical_key(name) != name)
            for name in names:
                add(canonical_key(str(name)), context[name], f"{EXTENSION_FILE}:context.{name}")
        ci = extension.get("ci")
        if isinstance(ci, dict) and ci.get("provider") is not None:
            add("ci_provider", ci["provider"], f"{EXTENSION_FILE}:ci.provider")

    project = files.project.data if files.project.state == "valid" else None
    if project:
        security = project.get("security")
        contact = security.get("contact") if isinstance(security, dict) else None
        if isinstance(contact, dict):
            contact = contact.get("email")
        if contact is not None:
            add("security_contact", contact, f"{PROJECT_FILE}:security.contact")
    return stored


def _timestamp_text(value: Any) -> Any:
    """A YAML timestamp a person wrote unquoted, as the text darnit writes."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _repository_records(files: ProjectFiles) -> dict[str, ConfirmationRecord]:
    extension = files.extension.data if files.extension.state == "valid" else None
    confirmations = extension.get("confirmations") if extension else None
    if not isinstance(confirmations, dict):
        return {}
    records = {}
    for name, entry in confirmations.items():
        try:
            fields = {k: _timestamp_text(v) for k, v in entry.items()}
            records[canonical_key(str(name))] = ConfirmationRecord.model_validate({**fields, "location": "repository"})
        except (TypeError, ValueError) as exc:
            logger.warning("Ignoring %s confirmations.%s: %s", EXTENSION_FILE, name, exc)
    return records


def _operator_records(local_path: str, repository: str | None) -> tuple[dict[str, ConfirmationRecord], dict[str, Any]]:
    """Operator-side records for ``repository`` and the values they confirmed, per key."""
    if repository is None:
        return {}, {}
    from darnit.trust.confirmations import CONTEXT_VALUE_CLAIM, load_confirmations, load_context_bases

    records = {}
    for confirmation in load_confirmations(repository, checkout=local_path):
        if confirmation.claim != CONTEXT_VALUE_CLAIM:
            continue
        records[confirmation.control_id] = ConfirmationRecord(
            value_digest=confirmation.evidence_digest,
            confirmed_by=confirmation.confirmed_by,
            confirmed_at=confirmation.confirmed_at,
            last_validated=confirmation.confirmed_at,
            expires_at=confirmation.expires_at,
            location="operator",
        )
    values = {}
    for basis in load_context_bases(repository, checkout=local_path):
        record = records.get(basis.key)
        if record is not None and record.value_digest == basis.value_digest:
            values[basis.key] = basis.value
            if basis.origin:
                records[basis.key] = record.model_copy(update={"basis": {"value": basis.value, "origin": basis.origin}})
    return records, values


def _repository_identity(
    local_path: str, target: str | None, operator: OperatorConfig | None, env: Mapping[str, str] | None
) -> str | None:
    """Canonical identity operator-side records are read for, when the operator or CI names it."""
    if operator is None:
        return None
    from darnit.trust.decision import decide_trust

    identity = decide_trust(target, operator, local_path, env).repository
    return identity.canonical if identity is not None and identity.trusted_eligible else None


def _detect(
    key: str, definition: ContextDefinition, local_path: str, owner: str | None, repo: str | None
) -> tuple[ContextValue | None, OriginKind | None]:
    """Run the key's detection for this run: its detect pipeline, then the context sieve.

    The sieve runs for a detectable key, or for a judgment key whose
    definition allows proposing sieve hints.
    """
    from darnit.config.context_storage import _apply_detect_filter, _run_detect_pipeline, _try_sieve_detection

    detected, kind = None, None
    if definition.detect:
        detected = _run_detect_pipeline(key, definition.detect, local_path, owner, repo)
        kind = OriginKind.DETECTOR
    if detected is None and (definition.auto_detect or definition.allow_sieve_hints):
        detected = _try_sieve_detection(key, local_path, owner, repo)
        kind = OriginKind.SIEVE_HINT
    if detected is not None:
        detected = _apply_detect_filter(key, definition, detected)
    return (detected, kind) if detected is not None else (None, None)


def _load_operator(local_path: str) -> OperatorConfig | None:
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config

    try:
        return resolve_operator_config(local_path).config
    except OperatorConfigError as exc:
        logger.warning("Operator-side context confirmations are not read: %s", exc)
        return None


def _auto_accept_confidence(local_path: str) -> float:
    try:
        from darnit.config.merger import load_effective_config_auto

        framework = load_effective_config_auto()._framework_config
        if framework is not None:
            return framework.context.auto_accept_confidence
    except Exception as exc:  # noqa: BLE001 - a read must not fail on config
        logger.debug("Using the default auto_accept_confidence: %s", exc)
    return DEFAULT_AUTO_ACCEPT_CONFIDENCE


def _matching(
    record: ConfirmationRecord | None, digest: str, definition: ContextDefinition, now: datetime
) -> tuple[ConfirmationRecord | None, ConfirmationRecord | None]:
    """(valid record, lapsed record) for a value with ``digest``."""
    if record is None:
        return None, None
    if record.value_digest != digest:
        return None, record
    if lapsed(record, definition, now):
        return None, record
    return record, None


def _resolve_key(
    key: str,
    definition: ContextDefinition,
    stored: list[tuple[Any, str]],
    repository_record: ConfirmationRecord | None,
    operator_record: ConfirmationRecord | None,
    operator_value: Any,
    detect: Callable[[], tuple[ContextValue | None, OriginKind | None]] | None,
    threshold: float,
    now: datetime,
) -> ResolvedValue:
    candidates = stored or ([(operator_value, None)] if operator_value is not None else [])
    stale: ConfirmationRecord | None = None
    expired: tuple[Any, str | None] | None = None
    for value, location in candidates:
        digest = value_digest(key, value)
        for record in (repository_record, operator_record):
            valid, lapsed_record = _matching(record, digest, definition, now)
            if valid is not None:
                return ResolvedValue(
                    key=key, standing=Standing.CONFIRMED, value=value, confirmation=valid, location=location
                )
            if lapsed_record is not None and lapsed_record.value_digest == digest and expired is None:
                expired, stale = (value, location), lapsed_record
            elif lapsed_record is not None and stale is None:
                stale = lapsed_record

    judgment = not definition.auto_detect
    if detect is not None and (not stored or not judgment):
        detected, kind = detect()
        if detected is not None:
            origin = Origin(kind=kind, method=detected.detection_method, confidence=detected.confidence)
            value = normalize_value(key, detected.value)
            if value is not None and not judgment and detected.confidence >= threshold:
                return ResolvedValue(key=key, standing=Standing.CONCLUDED, value=value, origin=origin, lapsed=stale)
            if value is not None and not stored:
                return ResolvedValue(key=key, standing=Standing.CANDIDATE, value=value, origin=origin, lapsed=stale)

    if expired is not None:
        value, location = expired
        origin = Origin(kind=OriginKind.EXPIRED_CONFIRMATION, method=location or "operator-side confirmation")
        return ResolvedValue(
            key=key, standing=Standing.CANDIDATE, value=value, origin=origin, lapsed=stale, location=location
        )
    if stored:
        value, location = stored[0]
        return ResolvedValue(
            key=key,
            standing=Standing.CANDIDATE,
            value=value,
            origin=Origin(kind=OriginKind.STORED_UNCONFIRMED, method=location),
            lapsed=stale,
            location=location,
        )
    return ResolvedValue(key=key, standing=Standing.UNKNOWN, lapsed=stale)


def resolve_context(
    local_path: str,
    definitions: Mapping[str, ContextDefinition] | None = None,
    *,
    target: str | None = None,
    operator: OperatorConfig | None = None,
    owner: str | None = None,
    repo: str | None = None,
    detect: bool = True,
    auto_accept_confidence: float | None = None,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedContext:
    """Resolve every defined context key's value and standing for this run.

    Args:
        local_path: Repository root.
        definitions: Context definitions (default: the framework's).
        target: Repository identity the operator named; operator-side
            records are read only for an operator- or CI-named repository.
        operator: Operator configuration (default: resolved for ``local_path``).
        owner: Repository owner, for detection.
        repo: Repository name, for detection.
        detect: Run detection for keys without a confirmed value.
        auto_accept_confidence: Threshold for concluding a detectable key
            (default: the framework's ``[context].auto_accept_confidence``).
        now: Current time, for lapse.
        env: Environment CI metadata is read from (default: the process environment).
    """
    if definitions is None:
        from darnit.config.context_storage import get_context_definitions

        definitions = get_context_definitions(local_path)
    definitions = {canonical_key(k): d for k, d in definitions.items()}
    now = now or datetime.now(UTC)
    if operator is None:
        operator = _load_operator(local_path)
    threshold = auto_accept_confidence if auto_accept_confidence is not None else _auto_accept_confidence(local_path)

    files = load_project_config_checked(local_path)
    for error in files.errors:
        logger.warning("Context from an invalid project file is not read: %s", error)
    stored = _stored_values(files)
    repository_records = _repository_records(files)
    operator_records, operator_values = _operator_records(
        local_path, _repository_identity(local_path, target, operator, env)
    )

    values = {}
    for key, definition in definitions.items():
        run_detection = (lambda k=key, d=definition: _detect(k, d, local_path, owner, repo)) if detect else None
        values[key] = _resolve_key(
            key,
            definition,
            stored.get(key, []),
            repository_records.get(key),
            operator_records.get(key),
            operator_values.get(key),
            run_detection,
            threshold,
            now,
        )
    return ResolvedContext(values=values, definitions=definitions)
