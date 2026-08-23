"""Ruleset-aware branch-protection verdict handler.

This module registers the ``github_branch_protection`` sieve handler used by
the four OSPS Baseline branch-protection controls
(``OSPS-AC-03.01``, ``OSPS-AC-03.02``, ``OSPS-QA-03.01``, ``OSPS-QA-07.01``).
It encapsulates the two-surface check that reconciles GitHub's classic
branch-protection API (``/repos/{owner}/{repo}/branches/{branch}/protection``)
with the newer repository-rulesets API (``/repos/{owner}/{repo}/rulesets``
and its per-ruleset detail endpoint) so a repository protected exclusively
via a ruleset resolves PASS rather than FAILing on the classic 404.

Verdict semantics:

* PASS when the classic surface carries the specific required signal (fast
  path -- rulesets NOT consulted).
* PASS when the classic surface did not carry the signal but an active
  repository ruleset that targets the audited branch carries the signal.
* FAIL when both surfaces respond successfully and neither carries the
  signal (locks feature 019's shipped invariant on the true-negative path).
* INCONCLUSIVE (which the trailing manual pass promotes to WARN) when
  either surface returns 401/403/429/5xx or a mid-pagination fetch fails.

The default-branch value used for ``~DEFAULT_BRANCH`` include-list matching
is consumed from ``HandlerContext.default_branch``, which the audit driver
populates. This feature does NOT introduce a ``GET /repos/{owner}/{repo}``
call to resolve it (SC-004's API-call budget invariant).

The sandboxing follow-up (issue #375, feature 031's mcp handler) shares no
state with this module. The ``github_branch_protection`` handler is
stateless: every audit-run's invocation makes fresh API calls; there is no
persistent cache.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, TypedDict

from darnit.core.utils import gh_api_with_status
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_CONSIDERED_RULESETS: int = 20
"""Cap on how many non-satisfying rulesets are enumerated in the evidence
record on FAIL. Research decision R-007. Overflow is tracked separately
via `considered_rulesets_truncated`."""

DEFAULT_TIMEOUT_SECONDS: int = 30
"""Default per-handler-invocation time budget in seconds."""

SUPPORTED_REF_INCLUDE_LITERALS: frozenset[str] = frozenset(
    {"~DEFAULT_BRANCH", "~ALL"}
)
"""Ruleset ``conditions.ref_name.include`` pseudo-refs the matcher
understands beyond exact branch names and ``refs/heads/<name>``."""

_GLOB_METACHARS: frozenset[str] = frozenset({"*", "?", "["})


# =============================================================================
# Enums (public within this module)
# =============================================================================


class ProtectionRequirement(str, Enum):
    """The specific protection a control tests for.

    Set via TOML ``requirement = "..."`` on a
    ``handler = "github_branch_protection"`` pass. See
    ``specs/032-ruleset-branch-protection/data-model.md`` for the full
    requirement-to-signal mapping.
    """

    REQUIRE_PULL_REQUEST = "require_pull_request"
    PREVENT_DELETION = "prevent_deletion"
    REQUIRE_STATUS_CHECKS = "require_status_checks"
    REQUIRE_APPROVALS = "require_approvals"


class VerdictSource(str, Enum):
    """The enumerated ``source`` value recorded in the evidence record.

    Locked by spec FR-016. Downstream reporting groups verdicts by source
    so a maintainer can distinguish "we have PASS via classic" from "we
    have PASS via ruleset" from "we could not tell either way."
    """

    CLASSIC = "classic"
    RULESET = "ruleset"
    NEITHER_SURFACE_PROVIDED_PROTECTION = "neither-surface-provided-protection"
    INSUFFICIENT_ACCESS = "insufficient-access"
    PARTIAL_FETCH = "partial-fetch"


# =============================================================================
# TypedDicts (private -- describe API-response shapes we consume)
# =============================================================================


class _RefNameConditions(TypedDict, total=False):
    include: list[str]
    exclude: list[str]


class _RulesetConditions(TypedDict, total=False):
    ref_name: _RefNameConditions


class _RulesetRule(TypedDict, total=False):
    type: str
    parameters: dict[str, Any]


class _RulesetDetail(TypedDict, total=False):
    id: int
    name: str
    enforcement: Literal["active", "evaluate", "disabled"]
    conditions: _RulesetConditions
    rules: list[_RulesetRule]


class _RulesetSummary(TypedDict, total=False):
    id: int
    name: str
    target: Literal["branch", "tag"]
    enforcement: Literal["active", "evaluate", "disabled"]


# =============================================================================
# Internal helpers
# =============================================================================


def _ref_name_matches(
    branch: str,
    default_branch: str | None,
    include: list[str] | None,
    exclude: list[str] | None,
) -> bool:
    """Return True iff at least one ``include`` covers ``branch`` and no ``exclude`` does.

    Match semantics (research R-003):

    * ``~DEFAULT_BRANCH`` matches iff ``default_branch is not None`` AND
      ``branch == default_branch``. When ``default_branch is None``, this
      pseudo-ref is treated as non-matching (Constitution II).
    * ``~ALL`` matches always.
    * Bare ``<name>`` matches iff equal to ``branch``.
    * ``refs/heads/<name>`` matches iff ``<name> == branch``.
    * Any entry containing a glob metacharacter (``*``, ``?``, ``[``)
      returns False (v0 limitation; documented in the spec).
    """
    include_list = include or []
    exclude_list = exclude or []
    if not any(_ref_matches(entry, branch, default_branch) for entry in include_list):
        return False
    return not any(_ref_matches(entry, branch, default_branch) for entry in exclude_list)


def _ref_matches(entry: str, branch: str, default_branch: str | None) -> bool:
    if not isinstance(entry, str):
        return False
    if any(ch in entry for ch in _GLOB_METACHARS):
        return False
    if entry == "~DEFAULT_BRANCH":
        return default_branch is not None and branch == default_branch
    if entry == "~ALL":
        return True
    if entry.startswith("refs/heads/"):
        return entry[len("refs/heads/") :] == branch
    return entry == branch


def _ruleset_satisfies(
    rule: _RulesetRule,
    requirement: ProtectionRequirement,
    minimum: int,
) -> tuple[bool, str]:
    """Return (satisfied, reason). On no-match, ``reason`` explains why.

    Mirrors the satisfying-signal table in
    ``specs/032-ruleset-branch-protection/data-model.md``.
    """
    rule_type = rule.get("type", "")
    if requirement is ProtectionRequirement.REQUIRE_PULL_REQUEST:
        if rule_type == "pull_request":
            return True, ""
        return False, f"rule type is {rule_type!r}, need 'pull_request'"
    if requirement is ProtectionRequirement.PREVENT_DELETION:
        if rule_type == "deletion":
            return True, ""
        return False, f"rule type is {rule_type!r}, need 'deletion'"
    if requirement is ProtectionRequirement.REQUIRE_STATUS_CHECKS:
        if rule_type == "required_status_checks":
            return True, ""
        return False, f"rule type is {rule_type!r}, need 'required_status_checks'"
    if requirement is ProtectionRequirement.REQUIRE_APPROVALS:
        if rule_type != "pull_request":
            return False, f"rule type is {rule_type!r}, need 'pull_request'"
        params = rule.get("parameters") or {}
        count = params.get("required_approving_review_count", 0)
        try:
            count_i = int(count)
        except (TypeError, ValueError):
            count_i = 0
        if count_i >= minimum:
            return True, ""
        return (
            False,
            f"pull_request rule but required_approving_review_count is {count_i}, "
            f"need >= {minimum}",
        )
    # Defensive: unreachable if the caller validated the requirement enum.
    return False, f"unknown requirement {requirement!r}"


def _classic_carries_signal(
    body: dict[str, Any], requirement: ProtectionRequirement, minimum: int
) -> bool:
    """Return True iff the classic branch-protection response body carries the required signal."""
    if requirement is ProtectionRequirement.REQUIRE_PULL_REQUEST:
        return body.get("required_pull_request_reviews") is not None
    if requirement is ProtectionRequirement.PREVENT_DELETION:
        allow_deletions = body.get("allow_deletions") or {}
        return allow_deletions.get("enabled") is False
    if requirement is ProtectionRequirement.REQUIRE_STATUS_CHECKS:
        return body.get("required_status_checks") is not None
    if requirement is ProtectionRequirement.REQUIRE_APPROVALS:
        reviews = body.get("required_pull_request_reviews") or {}
        count = reviews.get("required_approving_review_count", 0)
        try:
            return int(count) >= minimum
        except (TypeError, ValueError):
            return False
    return False


@dataclass
class _ClassicResult:
    satisfied: bool
    status: int
    error: str


def _query_classic(
    owner: str,
    repo: str,
    branch: str,
    requirement: ProtectionRequirement,
    minimum: int,
) -> _ClassicResult:
    """Query the classic branch-protection endpoint; return (satisfied, status, error)."""
    endpoint = f"/repos/{owner}/{repo}/branches/{branch}/protection"
    body, status, error = gh_api_with_status(endpoint)
    if status == 200 and isinstance(body, dict):
        return _ClassicResult(
            satisfied=_classic_carries_signal(body, requirement, minimum),
            status=200,
            error="",
        )
    return _ClassicResult(satisfied=False, status=status, error=error)


@dataclass
class _RulesetsResult:
    source: VerdictSource
    status: int
    matched: dict[str, Any] | None
    considered: list[dict[str, Any]]
    truncated: int
    error: str


def _query_rulesets(
    owner: str,
    repo: str,
    branch: str,
    default_branch: str | None,
    requirement: ProtectionRequirement,
    minimum: int,
) -> _RulesetsResult:
    """Query the rulesets endpoint and evaluate whether any ruleset satisfies.

    Returns a :class:`_RulesetsResult` whose ``source`` field carries the
    verdict-source enum. ``matched`` is populated on ``RULESET``;
    ``considered`` / ``truncated`` on ``NEITHER_SURFACE_PROVIDED_PROTECTION``.
    """
    list_endpoint = f"/repos/{owner}/{repo}/rulesets"
    body, status, error = gh_api_with_status(list_endpoint, paginate=True)
    if status != 200 or not isinstance(body, list):
        return _RulesetsResult(
            source=VerdictSource.INSUFFICIENT_ACCESS,
            status=status,
            matched=None,
            considered=[],
            truncated=0,
            error=error,
        )

    considered_all: list[dict[str, Any]] = []
    for summary in body:
        if not isinstance(summary, dict):
            continue
        if summary.get("enforcement") != "active":
            continue
        ruleset_id = summary.get("id")
        if ruleset_id is None:
            continue
        detail_endpoint = f"/repos/{owner}/{repo}/rulesets/{ruleset_id}"
        detail, detail_status, detail_error = gh_api_with_status(detail_endpoint)
        if detail_status != 200 or not isinstance(detail, dict):
            return _RulesetsResult(
                source=VerdictSource.PARTIAL_FETCH,
                status=detail_status,
                matched=None,
                considered=[],
                truncated=0,
                error=f"failed to fetch ruleset {ruleset_id} detail: {detail_error or 'HTTP ' + str(detail_status)}",
            )
        if detail.get("enforcement") != "active":
            continue
        conditions = detail.get("conditions") or {}
        ref_name = conditions.get("ref_name") or {}
        if not _ref_name_matches(
            branch, default_branch, ref_name.get("include"), ref_name.get("exclude")
        ):
            considered_all.append(
                {
                    "id": detail.get("id", ruleset_id),
                    "name": detail.get("name", summary.get("name", "?")),
                    "reason": "ref_name conditions do not cover branch "
                    f"{branch!r}",
                }
            )
            continue
        rules = detail.get("rules") or []
        if not rules:
            considered_all.append(
                {
                    "id": detail.get("id", ruleset_id),
                    "name": detail.get("name", summary.get("name", "?")),
                    "reason": "no rules declared",
                }
            )
            continue
        first_reason = ""
        satisfied = False
        for rule in rules:
            ok, reason = _ruleset_satisfies(rule, requirement, minimum)
            if ok:
                satisfied = True
                break
            if not first_reason:
                first_reason = reason
        if satisfied:
            return _RulesetsResult(
                source=VerdictSource.RULESET,
                status=200,
                matched={
                    "id": detail.get("id", ruleset_id),
                    "name": detail.get("name", summary.get("name", "?")),
                },
                considered=[],
                truncated=0,
                error="",
            )
        considered_all.append(
            {
                "id": detail.get("id", ruleset_id),
                "name": detail.get("name", summary.get("name", "?")),
                "reason": first_reason or "no matching rule type",
            }
        )

    truncated = max(0, len(considered_all) - MAX_CONSIDERED_RULESETS)
    return _RulesetsResult(
        source=VerdictSource.NEITHER_SURFACE_PROVIDED_PROTECTION,
        status=200,
        matched=None,
        considered=considered_all[:MAX_CONSIDERED_RULESETS],
        truncated=truncated,
        error="",
    )


# =============================================================================
# Handler entry point
# =============================================================================


_AMBIGUOUS_STATUSES = frozenset({0, 401, 403, 429})


def github_branch_protection_handler(
    config: dict[str, Any], context: HandlerContext
) -> HandlerResult:
    """Sieve handler that reconciles classic branch protection with repository rulesets.

    Config surface documented in
    ``specs/032-ruleset-branch-protection/contracts/github-branch-protection-handler.md``.
    """
    raw_requirement = config.get("requirement")
    if not isinstance(raw_requirement, str) or not raw_requirement:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="handler github_branch_protection requires 'requirement' field",
        )
    try:
        requirement = ProtectionRequirement(raw_requirement)
    except ValueError:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"unknown requirement {raw_requirement!r}",
        )

    minimum_raw = config.get("required_approvals_minimum", 1)
    try:
        minimum = int(minimum_raw)
    except (TypeError, ValueError):
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="required_approvals_minimum must be an integer",
        )
    if not (1 <= minimum <= 10):
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="required_approvals_minimum must be 1..10",
        )

    owner = str(config.get("owner") or context.owner or "").strip()
    repo = str(config.get("repo") or context.repo or "").strip()
    branch = str(config.get("branch") or context.default_branch or "main").strip()
    if not owner or not repo:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="handler github_branch_protection needs owner/repo (from context or config)",
        )

    # Default-branch value used for ~DEFAULT_BRANCH matching is consumed
    # from the audit driver's HandlerContext. This feature does NOT make
    # an extra `GET /repos/{owner}/{repo}` call (SC-004 budget).
    default_branch: str | None = context.default_branch or None

    # Step 1: classic surface
    classic = _query_classic(owner, repo, branch, requirement, minimum)
    if classic.satisfied:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=(
                f"branch {branch!r} protected via classic branch-protection "
                f"({requirement.value})"
            ),
            confidence=1.0,
            evidence={
                "source": VerdictSource.CLASSIC.value,
                "requirement": requirement.value,
                "classic_status": 200,
            },
        )

    # Ambiguous classic response -> INCONCLUSIVE without consulting rulesets.
    # A 401/403/429/5xx/0 from classic tells us nothing about protection, so
    # we cannot conservatively decide FAIL by consulting rulesets alone.
    if (
        classic.status in _AMBIGUOUS_STATUSES
        or classic.status >= 500
    ):
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=_classic_ambiguous_message(classic),
            evidence={
                "source": VerdictSource.INSUFFICIENT_ACCESS.value,
                "requirement": requirement.value,
                "classic_status": classic.status,
            },
        )

    # Classic returned a definitive negative signal (404, or 200 without the
    # specific field this control needs). Consult rulesets.
    rulesets = _query_rulesets(
        owner, repo, branch, default_branch, requirement, minimum
    )

    if rulesets.source is VerdictSource.RULESET:
        matched = rulesets.matched or {}
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=(
                f"branch {branch!r} protected via ruleset "
                f"{matched.get('name', '?')!r} (id={matched.get('id')})"
            ),
            confidence=1.0,
            evidence={
                "source": VerdictSource.RULESET.value,
                "requirement": requirement.value,
                "classic_status": classic.status,
                "rulesets_status": 200,
                "matched_ruleset": matched,
            },
        )

    if rulesets.source is VerdictSource.NEITHER_SURFACE_PROVIDED_PROTECTION:
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=(
                f"neither classic branch protection nor any active ruleset "
                f"provides {requirement.value} on branch {branch!r}"
            ),
            confidence=1.0,
            evidence={
                "source": VerdictSource.NEITHER_SURFACE_PROVIDED_PROTECTION.value,
                "requirement": requirement.value,
                "classic_status": classic.status,
                "rulesets_status": 200,
                "considered_rulesets": rulesets.considered,
                "considered_rulesets_truncated": rulesets.truncated,
            },
        )

    # PARTIAL_FETCH or INSUFFICIENT_ACCESS from rulesets -> WARN
    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message=_rulesets_ambiguous_message(rulesets),
        evidence={
            "source": rulesets.source.value,
            "requirement": requirement.value,
            "classic_status": classic.status,
            "rulesets_status": rulesets.status,
        },
    )


def _classic_ambiguous_message(classic: _ClassicResult) -> str:
    if classic.status == 401 or classic.status == 403:
        return (
            f"insufficient permissions to read classic branch protection "
            f"(HTTP {classic.status})"
        )
    if classic.status == 429:
        return "classic branch-protection endpoint rate-limited (HTTP 429)"
    if classic.status >= 500:
        return f"classic branch-protection endpoint returned HTTP {classic.status}"
    if classic.status == 0:
        return classic.error or "classic branch-protection endpoint unreachable"
    return f"classic branch-protection endpoint returned HTTP {classic.status}"


def _rulesets_ambiguous_message(rulesets: _RulesetsResult) -> str:
    if rulesets.source is VerdictSource.PARTIAL_FETCH:
        return rulesets.error or (
            f"could not fully enumerate rulesets (HTTP {rulesets.status})"
        )
    if rulesets.status in (401, 403):
        return (
            f"insufficient permissions to read repository rulesets "
            f"(HTTP {rulesets.status})"
        )
    if rulesets.status == 429:
        return "rulesets endpoint rate-limited (HTTP 429)"
    if rulesets.status >= 500:
        return f"rulesets endpoint returned HTTP {rulesets.status}"
    if rulesets.status == 0:
        return rulesets.error or "rulesets endpoint unreachable"
    return f"rulesets endpoint returned HTTP {rulesets.status}"


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_CONSIDERED_RULESETS",
    "ProtectionRequirement",
    "SUPPORTED_REF_INCLUDE_LITERALS",
    "VerdictSource",
    "github_branch_protection_handler",
]
