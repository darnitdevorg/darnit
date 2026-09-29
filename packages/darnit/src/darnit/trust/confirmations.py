"""Operator-side confirmations of not-applicable claims (feature 040, FR-019, FR-019a).

A confirmation records that a person on the operator side accepted a
repository's not-applicable claim. It is keyed by canonical repository
identity, control, claim, and a digest of the claim and the evidence observed
when it was confirmed, and it lapses when it expires or that digest changes.
Confirmations live under the darnit data root, never in the audited
repository.

The same store holds PASS candidates (feature 041, claim ``pass_candidate``):
positive model judgments awaiting a person. A stored candidate is never a
confirmation; only ``record_confirmation`` makes one.

It also holds operator-side confirmations of project context values
(feature 042, claim ``context_value``) for repositories the operator does not
trust; the confirmed value and the candidate it was based on are kept in the
``context_bases`` section. Their expiry is explicit, never the operator's
``confirmation_expiry_days`` policy.
"""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from darnit.core.logging import get_logger
from darnit.stores.defaults.platform_paths import user_data_root

if TYPE_CHECKING:
    from darnit.config.operator.schema import OperatorConfig

logger = get_logger("trust.confirmations")

SCHEMA_VERSION = 1
CONTEXT_VALUE_CLAIM = "context_value"

_POLICY_EXPIRY: Any = object()


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Confirmation:
    repository: str
    control_id: str
    claim: str
    evidence_digest: str
    confirmed_by: str
    confirmed_at: str
    expires_at: str | None

    def expired(self, now: datetime) -> bool:
        if self.expires_at is None:
            return False
        expires = _parse_timestamp(self.expires_at)
        return expires is None or now >= expires

    def report(self) -> dict[str, str | None]:
        """The ``assertion.confirmation`` block (contracts/asserted-results.md)."""
        return {"confirmed_by": self.confirmed_by, "confirmed_at": self.confirmed_at, "expires_at": self.expires_at}


@dataclass(frozen=True)
class StoredCandidate:
    repository: str
    control_id: str
    claim: str
    evidence_digest: str
    recorded_at: str
    candidate: dict[str, Any]


@dataclass(frozen=True)
class ContextBasis:
    """The value an operator-side context confirmation confirmed, and the candidate origin it was based on."""

    repository: str
    key: str
    value_digest: str
    value: Any
    origin: dict[str, Any] | None = None


def store_path() -> Path:
    return user_data_root() / "trust" / "confirmations.json"


def _inside(path: Path, checkout: str | Path | None) -> bool:
    if checkout is None:
        return False
    return path.resolve().is_relative_to(Path(checkout).resolve())


def load_confirmations(repository: str | None = None, *, checkout: str | Path | None = None) -> list[Confirmation]:
    """Stored confirmations, optionally only those for ``repository``.

    A store that lies inside the audited checkout is repository content and
    is not read.
    """
    stored = _load_section("confirmations", Confirmation, checkout)
    return [c for c in stored if repository is None or c.repository == repository]


def load_candidates(repository: str | None = None, *, checkout: str | Path | None = None) -> list[StoredCandidate]:
    """Stored PASS candidates, optionally only those for ``repository``."""
    stored = _load_section("candidates", StoredCandidate, checkout)
    return [c for c in stored if repository is None or c.repository == repository]


def load_context_bases(repository: str | None = None, *, checkout: str | Path | None = None) -> list[ContextBasis]:
    """Stored values of operator-side context confirmations, optionally only those for ``repository``."""
    stored = _load_section("context_bases", ContextBasis, checkout)
    return [b for b in stored if repository is None or b.repository == repository]


def _load_section(section: str, entry_type: type, checkout: str | Path | None) -> list[Any]:
    path = store_path()
    if _inside(path, checkout) or not path.is_file():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get(section, [])
        return [entry_type(**entry) for entry in entries]
    except (OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Ignoring unreadable confirmation store %s: %s", path, exc)
        return []


def find_confirmation(
    confirmations: Iterable[Confirmation],
    repository: str | None,
    control_id: str,
    claim: str,
    evidence_digest: str,
    *,
    now: datetime | None = None,
) -> Confirmation | None:
    """The confirmation that applies to exactly this claim and evidence, if any."""
    if repository is None:
        return None
    now = now or datetime.now(UTC)
    for confirmation in confirmations:
        if (
            confirmation.repository == repository
            and confirmation.control_id == control_id
            and confirmation.claim == claim
            and confirmation.evidence_digest == evidence_digest
            and not confirmation.expired(now)
        ):
            return confirmation
    return None


def _save(
    path: Path,
    confirmations: list[Confirmation],
    candidates: list[StoredCandidate],
    bases: list[ContextBasis] | None = None,
) -> None:
    data: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "confirmations": [asdict(c) for c in confirmations]}
    if candidates:
        data["candidates"] = [asdict(c) for c in candidates]
    bases = load_context_bases() if bases is None else bases
    if bases:
        data["context_bases"] = [asdict(b) for b in bases]
    _write(path, data)


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".confirmations-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def record_confirmation(
    repository: str,
    control_id: str,
    claim: str,
    evidence_digest: str,
    operator: OperatorConfig,
    *,
    checkout: str | Path | None = None,
    now: datetime | None = None,
    expires_at: datetime | None = _POLICY_EXPIRY,
) -> Confirmation:
    """Store a confirmation, replacing any earlier one for the same repository, control, and claim.

    ``expires_at`` defaults to the operator's ``confirmation_expiry_days``
    policy; pass a time, or None for no expiry, to set it explicitly.
    """
    path = store_path()
    if _inside(path, checkout):
        raise ValueError(f"refusing to store confirmations at {path}: it is inside the audited repository")

    now = now or datetime.now(UTC)
    if expires_at is _POLICY_EXPIRY:
        expires_at = now + timedelta(days=operator.policy.confirmation_expiry_days)
    confirmation = Confirmation(
        repository=repository,
        control_id=control_id,
        claim=claim,
        evidence_digest=evidence_digest,
        confirmed_by=operator.operator.identity or getpass.getuser(),
        confirmed_at=_timestamp(now),
        expires_at=None if expires_at is None else _timestamp(expires_at),
    )
    kept = [c for c in load_confirmations() if (c.repository, c.control_id, c.claim) != (repository, control_id, claim)]
    _save(path, [*kept, confirmation], load_candidates())
    return confirmation


def record_context_confirmation(
    repository: str,
    key: str,
    value_digest: str,
    value: Any,
    origin: dict[str, Any] | None,
    operator: OperatorConfig,
    *,
    expires_at: datetime | None = None,
    checkout: str | Path | None = None,
    now: datetime | None = None,
) -> Confirmation:
    """Store an operator-side confirmation of a context value (claim ``context_value``) and its value."""
    confirmation = record_confirmation(
        repository,
        key,
        CONTEXT_VALUE_CLAIM,
        value_digest,
        operator,
        checkout=checkout,
        now=now,
        expires_at=expires_at,
    )
    basis = ContextBasis(repository=repository, key=key, value_digest=value_digest, value=value, origin=origin)
    bases = [b for b in load_context_bases() if (b.repository, b.key) != (repository, key)]
    _save(store_path(), load_confirmations(), load_candidates(), [*bases, basis])
    return confirmation


def record_candidate(
    repository: str,
    control_id: str,
    claim: str,
    evidence_digest: str,
    candidate: dict[str, Any],
    *,
    checkout: str | Path | None = None,
    now: datetime | None = None,
) -> StoredCandidate:
    """Store a candidate, replacing any earlier one for the same repository, control, and claim.

    Confirmations of the same claim that no longer apply to ``evidence_digest``
    (expired, or for other evidence) are removed, so a lapsed confirmation
    cannot shadow the new candidate. A confirmation that still applies is kept.
    """
    path = store_path()
    if _inside(path, checkout):
        raise ValueError(f"refusing to store candidates at {path}: it is inside the audited repository")

    now = now or datetime.now(UTC)
    stored = StoredCandidate(
        repository=repository,
        control_id=control_id,
        claim=claim,
        evidence_digest=evidence_digest,
        recorded_at=_timestamp(now),
        candidate=dict(candidate),
    )
    key = (repository, control_id, claim)
    confirmations = [
        c
        for c in load_confirmations()
        if (c.repository, c.control_id, c.claim) != key or (c.evidence_digest == evidence_digest and not c.expired(now))
    ]
    candidates = [c for c in load_candidates() if (c.repository, c.control_id, c.claim) != key]
    _save(path, confirmations, [*candidates, stored])
    return stored
