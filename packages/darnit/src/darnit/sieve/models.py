"""Core data models for the Progressive Verification (Sieve) system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from darnit.locate import UnifiedLocator
    from darnit.config.framework_schema import LocatorConfig


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
    control_metadata: Dict[str, Any] = field(default_factory=dict)
    # Accumulated data from previous passes
    gathered_evidence: Dict[str, Any] = field(default_factory=dict)

    # Locator integration (Phase 6)
    # UnifiedLocator instance for .project/-aware file resolution
    locator: Optional["UnifiedLocator"] = None
    # LocatorConfig for this specific control (from TOML)
    locator_config: Optional["LocatorConfig"] = None


@dataclass
class PassResult:
    """Result from a single verification pass."""

    phase: VerificationPhase
    outcome: PassOutcome
    message: str
    evidence: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None  # 0.0-1.0, primarily for LLM pass
    details: Optional[Dict[str, Any]] = None


@dataclass
class PassAttempt:
    """Record of what a pass attempted (for transparency)."""

    phase: VerificationPhase
    checks_performed: List[str]  # Human-readable list of what was checked
    result: PassResult
    duration_ms: Optional[int] = None


@dataclass
class LLMConsultationRequest:
    """Request for LLM analysis when Pass 3 needs help."""

    control_id: str
    control_name: str
    control_description: str
    prompt: str
    context: Dict[str, Any]
    analysis_hints: List[str]
    expected_response: str  # JSON schema or format description


@dataclass
class LLMConsultationResponse:
    """Parsed response from LLM consultation."""

    status: PassOutcome  # PASS, FAIL, or INCONCLUSIVE
    confidence: float
    reasoning: str
    evidence_cited: List[str] = field(default_factory=list)


@dataclass
class SieveResult:
    """Complete result from sieve verification."""

    control_id: str
    status: str  # PASS, FAIL, WARN, NA, ERROR, PENDING_LLM
    message: str
    level: int

    # Sieve-specific transparency fields
    conclusive_phase: Optional[VerificationPhase] = None
    pass_history: List[PassAttempt] = field(default_factory=list)
    confidence: Optional[float] = None
    evidence: Optional[Dict[str, Any]] = None
    verification_steps: Optional[List[str]] = None  # For MANUAL phase
    source: str = "sieve"

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Convert to legacy result format for backward compatibility."""
        result = {
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
        return result


@runtime_checkable
class VerificationPassProtocol(Protocol):
    """Protocol that all verification passes must implement."""

    phase: VerificationPhase

    def execute(self, context: CheckContext) -> PassResult:
        """Execute this verification pass."""
        ...

    def describe(self) -> str:
        """Human-readable description of what this pass checks."""
        ...


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
    level: Optional[int]  # Maturity level (1, 2, 3) - None if framework doesn't use levels
    domain: Optional[str]  # Domain code (e.g., "AC", "VM") - None if not applicable
    name: str
    description: str
    passes: List[Any]  # List of pass implementations (VerificationPassProtocol)
    tags: Dict[str, Any] = field(default_factory=dict)  # Additional tags for filtering
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Locator configuration for this control (from TOML)
    locator_config: Optional["LocatorConfig"] = None

    def __post_init__(self):
        """Copy level/domain to tags and validate passes order."""
        # Copy level and domain to tags for uniform filtering
        if self.level is not None:
            self.tags["level"] = self.level
        if self.domain is not None:
            self.tags["domain"] = self.domain

        # Validate that passes are ordered correctly
        if not self.passes:
            return

        # Recommended order: DETERMINISTIC -> PATTERN -> LLM -> MANUAL
        phase_order = {
            VerificationPhase.DETERMINISTIC: 0,
            VerificationPhase.PATTERN: 1,
            VerificationPhase.LLM: 2,
            VerificationPhase.MANUAL: 3,
        }

        prev_order = -1
        for p in self.passes:
            current_order = phase_order.get(p.phase, 99)
            if current_order < prev_order:
                import warnings

                warnings.warn(
                    f"Control {self.control_id}: passes are not in recommended order "
                    f"(DETERMINISTIC -> PATTERN -> LLM -> MANUAL)"
                )
                break
            prev_order = current_order
