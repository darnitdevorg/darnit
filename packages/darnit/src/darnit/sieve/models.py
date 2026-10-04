"""Core data models for the Progressive Verification (Sieve) system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Optional, TypedDict

if TYPE_CHECKING:
    from darnit.config.framework_schema import LocatorConfig
    from darnit.core.models import ExecutionContext
    from darnit.locate import UnifiedLocator


class VerificationPhase(Enum):
    """The four phases of verification in the sieve."""

    DETERMINISTIC = "deterministic"  # Pass 1: File existence, API booleans, config
    PATTERN = "pattern"  # Pass 2: Regex matching, content analysis
    LLM = "llm"  # Pass 3: Ask calling LLM via consultation
    MANUAL = "manual"  # Pass 4: Always WARN with verification steps


class PassOutcome(Enum):
    """Outcome of a single verification pass."""

    PASS = "pass"  # Control satisfied
    FAIL = "fail"  # Control NOT satisfied
    WARN = "warn"  # Determined incomplete -- evidence read, found insufficient
    INCONCLUSIVE = "inconclusive"  # Cannot determine, continue to next pass
    ERROR = "error"  # Pass failed to execute


@dataclass
class CheckContext:
    """Context passed to each verification pass."""

    owner: str
    repo: str
    local_path: str
    default_branch: str
    control_id: str
    control_metadata: dict[str, Any] = field(default_factory=dict)
    # Accumulated data from previous passes
    gathered_evidence: dict[str, Any] = field(default_factory=dict)

    # Locator integration
    # UnifiedLocator instance for .project/-aware file resolution
    locator: Optional["UnifiedLocator"] = None
    # LocatorConfig for this specific control (from TOML)
    locator_config: Optional["LocatorConfig"] = None

    # .project/ context (from DotProjectMapper)
    # Contains flattened project metadata like project.security.policy_path, project.maintainers
    project_context: dict[str, Any] = field(default_factory=dict)

    # The usable context values only (confirmed or concluded, feature 042):
    # what a step expression's ``project`` binds to (framework-design 3.7).
    # ``project_context`` above is the when-clause context, which also holds
    # detections and unconfirmed .project/ mapper values.
    usable_project: dict[str, Any] = field(default_factory=dict)

    # Shared execution state across all controls
    execution_context: Optional["ExecutionContext"] = None


@dataclass
class PassResult:
    """Result from a single verification pass."""

    phase: VerificationPhase
    outcome: PassOutcome
    message: str
    evidence: dict[str, Any] | None = None
    confidence: float | None = None  # 0.0-1.0, primarily for LLM pass
    details: dict[str, Any] | None = None


@dataclass
class PassAttempt:
    """Record of what a pass attempted (for transparency)."""

    phase: VerificationPhase
    checks_performed: list[str]  # Human-readable list of what was checked
    result: PassResult
    duration_ms: int | None = None


@dataclass
class LLMConsultationResponse:
    """Parsed response from LLM consultation."""

    status: PassOutcome  # PASS, FAIL, INCONCLUSIVE, or ERROR (the model service failed)
    confidence: float
    reasoning: str
    evidence_cited: list[str] = field(default_factory=list)
    model: str = ""
    model_version: str = ""
    # With status ERROR: ``unavailable`` or ``evaluation`` (feature 041).
    error_class: str | None = None


# The six string labels used across the sieve orchestrator, tools/audit.py, and
# the JSON/MCP/SARIF wire formats. "N/A" (with slash) is the excluded-control
# label emitted by tools/audit.py:495. Feature 041: PENDING replaces
# PENDING_LLM and always carries ``pending.kind``.
CheckStatus = Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING"]

CHECK_STATUSES: frozenset[str] = frozenset(("PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING"))

# What a PENDING result is waiting for: a model judgment, or an operator
# confirmation of a PASS candidate.
PendingKind = Literal["llm_judgment", "confirmation"]
PENDING_KINDS: frozenset[str] = frozenset(("llm_judgment", "confirmation"))


class PassHistoryResult(TypedDict):
    """Nested `result` field inside a PassHistoryEntry.

    Mirrors the dict shape emitted by SieveResult.to_legacy_dict() at models.py:137-141.
    """

    outcome: str
    message: str
    confidence: float | None


class PassHistoryEntry(TypedDict):
    """One phase attempt inside a CheckResult's pass_history list.

    Mirrors the dict shape emitted by SieveResult.to_legacy_dict() at models.py:133-145.
    """

    phase: str
    checks_performed: list[str]
    result: PassHistoryResult
    duration_ms: int | None


class CheckResult(TypedDict):
    """The wire shape of one entry in AuditState.audit_results.

    Producers:
        - SieveResult.to_legacy_dict() at models.py:111 (primary path).
        - The excluded-control fallback at tools/audit.py:492 (sparse: only the
          four required keys).
        - Post-hoc mutation at tools/audit.py:530 attaches the optional `when`
          key; grandfathered by feature 022.

    Consumers include AuditState.audit_results (agent/state.py:61) and any
    downstream driver step that iterates check results.
    """

    # Required (present in every producer path).
    id: str
    status: CheckStatus
    details: str
    level: int

    # Optional (present when the corresponding SieveResult field was set).
    sieve_phase: NotRequired[str]
    confidence: NotRequired[float]
    verification_steps: NotRequired[list[str]]
    evidence: NotRequired[dict[str, Any]]
    resolving_pass_index: NotRequired[int]
    resolving_pass_handler: NotRequired[str]
    pass_history: NotRequired[list[PassHistoryEntry]]

    # RFC-0001 Stage 1 (feature 025 T010). Authority of the step that
    # concluded the control. `NotRequired` for back-compat with pre-Stage-1
    # serialized results, but per FR-001 the runner MUST treat any
    # authority-less result as suggestive (cannot conclude PASS/FAIL).
    authority: NotRequired[str]  # values in {"dispositive", "suggestive", "asserted"}

    # Feature 036. Environmental failure class, present only when the
    # resolving pass could not run to completion (network / auth / timeout /
    # rate_limit / not_found / crashed). `NotRequired` for the same reason
    # authority is: additive, and absent on results serialized before this
    # feature. Typed `str` rather than `ErrorClass` because this TypedDict is
    # the deserialization boundary -- a result from a future darnit version
    # may carry a value this version's Literal does not know.
    error_class: NotRequired[str]

    # Feature 041. What concluded the result (a step handler name,
    # "llm_judgment", "confirmation", "inferred_from", or "none"); the ERROR
    # cause; what a PENDING result awaits; the PASS candidate awaiting
    # confirmation; and the confirmation behind an asserted PASS.
    concluded_by: NotRequired[str]
    error: NotRequired[dict[str, str]]
    pending: NotRequired[dict[str, str]]
    candidate: NotRequired[dict[str, Any]]
    confirmation: NotRequired[dict[str, Any]]

    # Attached post-hoc at tools/audit.py:530.
    when: NotRequired[str]


@dataclass
class SieveResult:
    """Complete result from sieve verification."""

    control_id: str
    status: CheckStatus  # PASS, FAIL, WARN, N/A, ERROR, PENDING
    message: str
    level: int

    # Sieve-specific transparency fields
    conclusive_phase: VerificationPhase | None = None
    pass_history: list[PassAttempt] = field(default_factory=list)
    confidence: float | None = None
    evidence: dict[str, Any] | None = None
    verification_steps: list[str] | None = None  # For MANUAL phase
    source: str = "sieve"

    # Resolving pass metadata (which pass produced the conclusive result)
    resolving_pass_index: int | None = None
    resolving_pass_handler: str | None = None

    # RFC-0001 Stage 1 (feature 025 T010). Authority of the step that
    # concluded the control (dispositive / suggestive / asserted). None
    # means "unknown / not migrated"; the runner treats absence as
    # suggestive-equivalent for disposition purposes.
    authority: str | None = None

    # Feature 036. Environmental failure class of the RESOLVING pass only
    # (FR-009a) -- earlier non-resolving passes' values are discarded, not
    # aggregated, since a later pass that concluded on real evidence
    # supersedes an earlier environmental failure. The per-pass trail
    # already lives in `pass_history`.
    error_class: str | None = None

    # Feature 041 (data-model.md "Result").
    concluded_by: str | None = None
    error: dict[str, str] | None = None
    pending: dict[str, str] | None = None
    candidate: dict[str, Any] | None = None
    confirmation: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Enforce the feature 041 result invariants.

        ERROR always carries ``error {class, cause}`` (derived from
        ``error_class`` and the message when not given). PENDING always
        carries a known ``pending.kind``, and a PASS candidate awaiting
        confirmation always carries its ``candidate`` block.
        """
        if self.status not in CHECK_STATUSES:
            raise ValueError(f"status={self.status!r} is not one of {sorted(CHECK_STATUSES)}")
        if self.status == "ERROR":
            if self.error is None:
                self.error = {"class": self.error_class or "evaluation", "cause": self.message}
            elif not self.error.get("class") or not self.error.get("cause"):
                raise ValueError("an ERROR result's error block needs both 'class' and 'cause'")
        if self.status == "PENDING":
            kind = (self.pending or {}).get("kind")
            if kind not in PENDING_KINDS:
                raise ValueError(f"a PENDING result needs pending.kind in {sorted(PENDING_KINDS)}, got {kind!r}")
            if kind == "confirmation" and not self.candidate:
                raise ValueError("a PENDING result awaiting confirmation needs its candidate block")

    def to_legacy_dict(self) -> CheckResult:
        """Convert to legacy result format for backward compatibility.

        Returns a CheckResult TypedDict; runtime shape is a plain dict, so
        existing consumers that expect a bare dict are unaffected. See
        specs/022-type-audit-results/contracts/check-result.md.
        """
        result: CheckResult = {
            "id": self.control_id,
            "status": self.status,
            "details": self.message,
            "level": self.level,
        }
        # Add optional extended info if present
        if self.conclusive_phase:
            result["sieve_phase"] = self.conclusive_phase.value
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.verification_steps:
            result["verification_steps"] = self.verification_steps
        if self.evidence:
            result["evidence"] = self.evidence
        if self.resolving_pass_index is not None:
            result["resolving_pass_index"] = self.resolving_pass_index
        if self.resolving_pass_handler is not None:
            result["resolving_pass_handler"] = self.resolving_pass_handler
        if self.authority is not None:
            result["authority"] = self.authority
        if self.error_class is not None:
            result["error_class"] = self.error_class
        if self.concluded_by is not None:
            result["concluded_by"] = self.concluded_by
        if self.error is not None:
            result["error"] = dict(self.error)
        if self.pending is not None:
            result["pending"] = dict(self.pending)
        if self.candidate is not None:
            result["candidate"] = dict(self.candidate)
        if self.confirmation is not None:
            result["confirmation"] = dict(self.confirmation)
        if self.pass_history:
            result["pass_history"] = [
                {
                    "phase": attempt.phase.value,
                    "checks_performed": attempt.checks_performed,
                    "result": {
                        "outcome": attempt.result.outcome.value,
                        "message": attempt.result.message,
                        "confidence": attempt.result.confidence,
                    },
                    "duration_ms": attempt.duration_ms,
                }
                for attempt in self.pass_history
            ]
        return result


@dataclass
class ControlSpec:
    """Complete specification for a control with sieve verification.

    Level and domain are regular fields for backward compatibility, but are
    also copied into the tags dict for uniform filtering. This allows frameworks
    to filter on any tag key (including level and domain) uniformly.

    The tags dict can hold additional key-value pairs beyond level/domain,
    enabling flexible filtering like --tags severity>=7.0 or --tags category=auth.
    """

    control_id: str
    level: int | None  # Maturity level (1, 2, 3) - None if framework doesn't use levels
    domain: str | None  # Domain code (e.g., "AC", "VM") - None if not applicable
    name: str
    description: str
    tags: dict[str, Any] = field(default_factory=dict)  # Additional tags for filtering
    metadata: dict[str, Any] = field(default_factory=dict)
    # Locator configuration for this control (from TOML)
    locator_config: Optional["LocatorConfig"] = None

    def __post_init__(self):
        """Copy level/domain to tags for uniform filtering."""
        if self.level is not None:
            self.tags["level"] = self.level
        if self.domain is not None:
            self.tags["domain"] = self.domain
