"""Project assertions: what the audited repository says about itself (feature 040, research R6).

A not-applicable claim is read from ``.project/darnit.yaml`` ``controls``
and, during the ``.baseline.toml`` deprecation period, from per-control
``status``/``reason`` in ``.baseline.toml``. Claims are repository content:
they are recorded and reported with their origin and asserter, and they do
not decide on their own whether a control counts.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from darnit.config.schema import ControlOverride, ControlStatusValue
from darnit.core.logging import get_logger

logger = get_logger("trust.assertions")

PROJECT_ASSERTIONS_FILE = ".project/darnit.yaml"
BASELINE_TOML = ".baseline.toml"
DEFAULT_ASSERTER = "repository content"
_NOT_APPLICABLE = frozenset({ControlStatusValue.NA.value, ControlStatusValue.DISABLED.value})

AssertionOutcome = Literal["honored", "pending", "contradicted"]


@dataclass(frozen=True)
class ProjectAssertion:
    control_id: str
    claim: Literal["not_applicable"]
    reason: str | None
    asserted_by: str
    location: str
    origin: str

    def report(self, outcome: AssertionOutcome) -> dict[str, Any]:
        """The per-control ``assertion`` block (contracts/asserted-results.md)."""
        return {
            "outcome": outcome,
            "origin": self.origin,
            "reason": self.reason,
            "asserted_by": self.asserted_by,
            "location": self.location,
            "confirmation": None,
            "contradiction": None,
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


def collect_assertions(local_path: str | Path, framework_control_ids: Collection[str]) -> list[ProjectAssertion]:
    """Explicit not-applicable claims the audited repository makes about the framework's controls.

    A claim in ``.project/darnit.yaml`` takes precedence over one for the
    same control in ``.baseline.toml``. Claims about controls the framework
    does not define are reported and ignored.
    """
    repo = Path(local_path)
    claims: dict[str, ProjectAssertion] = {}
    for claim in [*_project_claims(repo), *_baseline_claims(repo)]:
        if claim.control_id not in framework_control_ids:
            logger.warning(
                "Ignoring not-applicable claim in %s for unknown control %s",
                claim.location.split(":", 1)[0],
                claim.control_id,
            )
            continue
        claims.setdefault(claim.control_id, claim)
    return list(claims.values())
