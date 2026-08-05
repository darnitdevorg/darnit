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

    status: PassOutcome  # PASS, FAIL, or INCONCLUSIVE
    confidence: float
    reasoning: str
    evidence_cited: list[str] = field(default_factory=list)


# The six string labels used across the sieve orchestrator, tools/audit.py, and
# the JSON/MCP/SARIF wire formats. "N/A" (with slash) is the excluded-control
# label emitted by tools/audit.py:495.
CheckStatus = Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM"]


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

    # Attached post-hoc at tools/audit.py:530.
    when: NotRequired[str]


@dataclass
class SieveResult:
    """Complete result from sieve verification."""

    control_id: str
    status: CheckStatus  # PASS, FAIL, WARN, N/A, ERROR, PENDING_LLM
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
