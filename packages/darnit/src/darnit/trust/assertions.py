"""Project assertions: what the audited repository says about itself (feature 040, research R6).

A not-applicable claim is read from ``.project/darnit.yaml`` ``controls``
and, during the ``.baseline.toml`` deprecation period, from per-control
``status``/``reason`` in ``.baseline.toml``. Project data in ``.project/``
that makes a control not applicable is a claim too (FR-013a). Claims are
repository content: a claim counts only when its outcome is ``honored`` --
the repository is trusted, an explicit claim gives a reason (a project data
value states its own), and no declared evidence contradicts it -- or when an
operator-side confirmation matches it (FR-014 to FR-019).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import ValidationError

from darnit.config.schema import ControlOverride, ControlStatusValue
from darnit.core.logging import get_logger
from darnit.trust.confirmations import Confirmation, find_confirmation

if TYPE_CHECKING:
    from darnit.config.framework_schema import ContradictedBy

logger = get_logger("trust.assertions")

PROJECT_ASSERTIONS_FILE = ".project/darnit.yaml"
BASELINE_TOML = ".baseline.toml"
DEFAULT_ASSERTER = "repository content"
_NOT_APPLICABLE = frozenset({ControlStatusValue.NA.value, ControlStatusValue.DISABLED.value})

AssertionOutcome = Literal["honored", "pending", "contradicted"]
CLAIM_NOT_APPLICABLE = "not_applicable"
CONTEXT_VALUE_ORIGIN = "context_value:"


@dataclass(frozen=True)
class ProjectAssertion:
    control_id: str
    claim: Literal["not_applicable"]
    reason: str | None
    asserted_by: str
    location: str
    origin: str
    value: Any = None

    def report(
        self,
        outcome: AssertionOutcome,
        confirmation: dict[str, Any] | None = None,
        contradiction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The per-control ``assertion`` block (contracts/asserted-results.md)."""
        return {
            "outcome": outcome,
            "origin": self.origin,
            "reason": self.reason,
            "asserted_by": self.asserted_by,
            "location": self.location,
            "confirmation": confirmation,
            "contradiction": contradiction,
        }


def _claim(control_id: str, status: str, reason: Any, asserted_by: Any, file: str) -> ProjectAssertion | None:
    if status not in _NOT_APPLICABLE:
        return None
    reason = reason.strip() if isinstance(reason, str) else None
    asserted_by = asserted_by.strip() if isinstance(asserted_by, str) else None
    return ProjectAssertion(
        control_id=control_id,
        claim="not_applicable",
        reason=reason or None,
        asserted_by=asserted_by or DEFAULT_ASSERTER,
        location=f"{file}:controls.{control_id}",
        origin="explicit_claim",
    )


def _project_claims(repo: Path) -> list[ProjectAssertion]:
    path = repo / PROJECT_ASSERTIONS_FILE
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        logger.warning("Could not read %s: %s", PROJECT_ASSERTIONS_FILE, exc)
        return []
    controls = data.get("controls") if isinstance(data, dict) else None
    if not isinstance(controls, dict):
        return []

    claims = []
    for control_id, entry in controls.items():
        try:
            override = ControlOverride.model_validate(entry)
        except ValidationError as exc:
            logger.warning("Ignoring %s controls.%s: %s", PROJECT_ASSERTIONS_FILE, control_id, exc)
            continue
        claim = _claim(
            str(control_id), override.status.value, override.reason, override.asserted_by, PROJECT_ASSERTIONS_FILE
        )
        if claim:
            claims.append(claim)
    return claims


def _baseline_claims(repo: Path) -> list[ProjectAssertion]:
    from darnit.config.merger import load_user_config_with_report

    try:
        user, _ignored = load_user_config_with_report(repo)
    except Exception as exc:  # noqa: BLE001 - an unreadable repository file yields no claims
        logger.warning("Could not read %s: %s", BASELINE_TOML, exc)
        return []
    if user is None:
        return []

    claims = []
    for control_id in user.controls:
        override = user.get_control_override(control_id)
        status = getattr(override, "status", None)
        if status is None:
            continue
        claim = _claim(control_id, getattr(status, "value", status), override.reason, None, BASELINE_TOML)
        if claim:
            claims.append(claim)
    return claims


def _claims(repo: Path) -> dict[str, ProjectAssertion]:
    claims: dict[str, ProjectAssertion] = {}
    for claim in [*_project_claims(repo), *_baseline_claims(repo)]:
        claims.setdefault(claim.control_id, claim)
    return claims


def collect_assertions(local_path: str | Path, framework_control_ids: Collection[str]) -> list[ProjectAssertion]:
    """Explicit not-applicable claims the audited repository makes about the framework's controls.

    A claim in ``.project/darnit.yaml`` takes precedence over one for the
    same control in ``.baseline.toml``. Claims about controls the framework
    does not define are logged and ignored; :func:`unknown_assertions`
    returns them for reports.
    """
    claims = []
    for claim in _claims(Path(local_path)).values():
        if claim.control_id not in framework_control_ids:
            logger.warning(
                "Ignoring not-applicable claim in %s for unknown control %s",
                claim.location.split(":", 1)[0],
                claim.control_id,
            )
            continue
        claims.append(claim)
    return claims


def unknown_assertions(local_path: str | Path, framework_control_ids: Collection[str]) -> list[ProjectAssertion]:
    """Claims about controls the selected framework does not define; they have no effect."""
    return [c for c in _claims(Path(local_path)).values() if c.control_id not in framework_control_ids]


def context_value_assertions(
    controls_when: Mapping[str, Mapping[str, Any]],
    context: Mapping[str, Any],
    detected: Mapping[str, Any],
    repository_values: Mapping[str, str],
) -> list[ProjectAssertion]:
    """Claims implied by repository-supplied context values (FR-013a).

    Args:
        controls_when: Each control's applicability (``when``) condition.
        context: The context the audit evaluates conditions against.
        detected: Values darnit detected itself, without repository-supplied data.
        repository_values: Keys of ``context`` whose value came from the
            audited repository, mapped to where each was read.

    A control is claimed not applicable by the repository when its condition
    fails against ``context`` but holds once repository-supplied values are
    replaced by detected ones (or dropped).
    """
    from darnit.sieve.orchestrator import evaluate_when_clause

    claims = []
    for control_id, when in controls_when.items():
        if not when or evaluate_when_clause(dict(when), dict(context)):
            continue
        if not evaluate_when_clause(dict(when), neutral_context(when, context, detected, repository_values)):
            continue
        key = next(
            k
            for k, expected in when.items()
            if k in repository_values and context.get(k) is not None and context[k] != expected
        )
        claims.append(
            ProjectAssertion(
                control_id=control_id,
                claim=CLAIM_NOT_APPLICABLE,
                reason=None,
                asserted_by=DEFAULT_ASSERTER,
                location=repository_values[key],
                origin=f"{CONTEXT_VALUE_ORIGIN}{key}",
                value=context[key],
            )
        )
    return claims


def neutral_context(
    when: Mapping[str, Any],
    context: Mapping[str, Any],
    detected: Mapping[str, Any],
    repository_values: Mapping[str, str],
) -> dict[str, Any]:
    """``context`` with repository-supplied values of ``when``'s keys replaced by detected ones."""
    neutral = dict(context)
    for key in when:
        if key not in repository_values:
            continue
        if key in detected:
            neutral[key] = detected[key]
        else:
            neutral.pop(key, None)
    return neutral


@dataclass(frozen=True)
class Evidence:
    """What darnit observed for a control's declared contradicting evidence.

    ``value`` is None when the evidence could not be obtained.
    """

    source: str
    value: Any
    observed_at: str
    method: str | None = None

    @property
    def obtained(self) -> bool:
        return self.value is not None


def evidence_digest(assertion: ProjectAssertion, evidence: Evidence | None) -> str:
    """Digest of a claim and the evidence observed for it; a confirmation is bound to it."""
    payload = {
        "claim": assertion.claim,
        "origin": assertion.origin,
        "reason": assertion.reason or "",
        "value": assertion.value,
        "evidence": None if evidence is None else {"source": evidence.source, "value": evidence.value},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AssertionAssessment:
    assertion: ProjectAssertion
    outcome: AssertionOutcome
    confirmation: Confirmation | None = None
    contradiction: dict[str, Any] | None = None

    def report(self) -> dict[str, Any]:
        return self.assertion.report(
            self.outcome, self.confirmation.report() if self.confirmation else None, self.contradiction
        )


def find_contradiction(contradicted_by: ContradictedBy, evidence: Evidence) -> dict[str, Any] | None:
    """The ``assertion.contradiction`` block when ``evidence`` refutes the claim, else None."""
    if not evidence.obtained or evidence.value != contradicted_by.when_value:
        return None
    return {
        "evidence_source": f"{evidence.source} detection ({evidence.method})" if evidence.method else evidence.source,
        "observed_at": evidence.observed_at,
        "summary": (
            f"{contradicted_by.context} detected as {evidence.value!r}, which contradicts the not-applicable claim"
        ),
    }


def assess_assertion(
    assertion: ProjectAssertion,
    *,
    trusted: bool,
    contradicted_by: ContradictedBy | None,
    observe: Callable[[], Evidence] | None = None,
    repository: str | None = None,
    confirmations: Iterable[Confirmation] = (),
    now: datetime | None = None,
) -> AssertionAssessment:
    """Decide whether a not-applicable claim counts (data-model.md, AssertionOutcome).

    Args:
        assertion: The claim.
        trusted: Whether the operator trusts the audited repository for this run.
        contradicted_by: Evidence the control declares can refute the claim.
        observe: Obtains that evidence; called at most once, and only when needed.
        repository: Canonical identity confirmations must match, or None when
            the identity does not come from the operator or CI.
        confirmations: Operator-side confirmations to consider.
        now: Current time, for confirmation expiry.
    """
    observed: list[Evidence | None] = []

    def evidence() -> Evidence | None:
        if not observed:
            if contradicted_by is None:
                observed.append(None)
            elif observe is None:
                observed.append(Evidence(source=f"context.{contradicted_by.context}", value=None, observed_at=""))
            else:
                observed.append(observe())
        return observed[0]

    if trusted and (assertion.reason or assertion.origin.startswith(CONTEXT_VALUE_ORIGIN)):
        current = evidence()
        if current is None:
            return AssertionAssessment(assertion, "honored")
        if current.obtained:
            contradiction = find_contradiction(contradicted_by, current)
            if contradiction:
                return AssertionAssessment(assertion, "contradicted", contradiction=contradiction)
            return AssertionAssessment(assertion, "honored")

    candidates = [
        c
        for c in confirmations
        if repository is not None and c.repository == repository and c.control_id == assertion.control_id
    ]
    if candidates:
        current = evidence()
        if current is not None and current.obtained:
            contradiction = find_contradiction(contradicted_by, current)
            if contradiction:
                return AssertionAssessment(assertion, "contradicted", contradiction=contradiction)
        confirmation = find_confirmation(
            candidates, repository, assertion.control_id, assertion.claim, evidence_digest(assertion, current), now=now
        )
        if confirmation is not None:
            return AssertionAssessment(assertion, "honored", confirmation=confirmation)
    return AssertionAssessment(assertion, "pending")


def observe_context_evidence(
    contradicted_by: ContradictedBy,
    detect_pipeline: list | None,
    local_path: str,
    owner: str | None,
    repo: str | None,
) -> Evidence:
    """Run a context key's detection to obtain contradicting evidence.

    Detection that errors, cannot conclude, or is not defined yields no value,
    so the claim it would check stays pending (FR-017).
    """
    from darnit.config.context_storage import _run_detect_pipeline

    source = f"context.{contradicted_by.context}"
    observed_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not detect_pipeline:
        return Evidence(source=source, value=None, observed_at=observed_at)
    detected = _run_detect_pipeline(contradicted_by.context, detect_pipeline, local_path, owner, repo, strict=True)
    if detected is None:
        return Evidence(source=source, value=None, observed_at=observed_at)
    return Evidence(source=source, value=detected.value, observed_at=observed_at, method=detected.detection_method)
