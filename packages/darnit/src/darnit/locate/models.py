"""Data models for the unified evidence location system.

This module defines the core data structures for:
- FoundEvidence: What was located and where
- LocateResult: Result of a location operation
- CheckOutput: Standardized output from any check adapter

These models form the tool output contract that all check adapters
(builtin, command, script, http) must return.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

# =============================================================================
# Found Evidence Models
# =============================================================================


@dataclass
class FoundEvidence:
    """What the check located.

    Represents evidence found for a control - could be a file, URL, API endpoint,
    or configuration. This is used to:
    1. Report what was found during checks
    2. Sync back to .project/ configuration

    Attributes:
        path: File path relative to repository root
        url: External URL (e.g., docs.example.com/security)
        api_endpoint: API endpoint that was checked (e.g., GitHub API)
        kind: Type of evidence (file, url, api, config)
    """
    path: str | None = None
    url: str | None = None
    api_endpoint: str | None = None
    kind: Literal["file", "url", "api", "config"] = "file"

    def __post_init__(self):
        """Validate that at least one location is provided."""
        if not any([self.path, self.url, self.api_endpoint]):
            # Allow empty for cases where nothing was found but we want to record the attempt
            pass

    @property
    def location(self) -> str | None:
        """Return the primary location identifier."""
        if self.path:
            return self.path
        if self.url:
            return self.url
        if self.api_endpoint:
            return self.api_endpoint
        return None


@dataclass
class LocateResult:
    """Result of a location operation.

    Represents the outcome of trying to locate evidence for a control,
    including where it was found and how (config reference vs discovery).

    Attributes:
        found: The evidence that was found, or None if not found
        source: How the evidence was located
        searched_locations: List of locations that were checked
        sync_recommended: Whether the found evidence should be synced to .project/
    """
    found: FoundEvidence | None = None
    source: Literal["config", "discovered", "llm", "none"] = "none"
    searched_locations: list[str] = field(default_factory=list)
    sync_recommended: bool = False

    @property
    def success(self) -> bool:
        """Whether evidence was successfully located."""
        return self.found is not None

    @property
    def needs_sync(self) -> bool:
        """Whether the evidence should be synced to .project/.

        Returns True when evidence was discovered but not via config reference,
        indicating the config should be updated.
        """
        return self.sync_recommended and self.source in ("discovered", "llm")


# =============================================================================
# Check Output Models
# =============================================================================


@dataclass
class CheckOutput:
    """Standardized output from any check adapter.

    This is the tool output contract that all check adapters must return.
    It provides a unified interface for:
    - Pass/fail status
    - Confidence level
    - What was found (for .project/ sync)
    - Details for remediation context

    Attributes:
        status: Check result status
        message: Human-readable explanation
        confidence: Confidence level (0.0 to 1.0)
        found: Evidence that was located
        evidence: Additional evidence details (adapter-specific)
        issues: List of issues found
        suggestions: Remediation suggestions
    """
    # Core result
    status: Literal["pass", "fail", "error", "inconclusive"]
    message: str
    confidence: float = 1.0

    # What was found (for .project/ sync)
    found: FoundEvidence | None = None

    # Validation details (adapter-specific)
    evidence: dict[str, Any] = field(default_factory=dict)

    # For remediation context
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate confidence is in valid range."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")

    @property
    def passed(self) -> bool:
        """Whether the check passed."""
        return self.status == "pass"

    @property
    def failed(self) -> bool:
        """Whether the check failed."""
        return self.status == "fail"

    @property
    def has_evidence(self) -> bool:
        """Whether evidence was found."""
        return self.found is not None


# =============================================================================
# Factory Functions
# =============================================================================


def create_pass_output(
    message: str,
    found: FoundEvidence | None = None,
    confidence: float = 1.0,
    **evidence: Any,
) -> CheckOutput:
    """Create a passing check output.

    Args:
        message: Success message
        found: Evidence that was found
        confidence: Confidence level
        **evidence: Additional evidence details

    Returns:
        CheckOutput with status="pass"
    """
    return CheckOutput(
        status="pass",
        message=message,
        confidence=confidence,
        found=found,
        evidence=evidence,
    )


def create_fail_output(
    message: str,
    issues: list[str] | None = None,
    suggestions: list[str] | None = None,
    confidence: float = 1.0,
    **evidence: Any,
) -> CheckOutput:
    """Create a failing check output.

    Args:
        message: Failure message
        issues: List of specific issues found
        suggestions: Remediation suggestions
        confidence: Confidence level
        **evidence: Additional evidence details

    Returns:
        CheckOutput with status="fail"
    """
    return CheckOutput(
        status="fail",
        message=message,
        confidence=confidence,
        issues=issues or [],
        suggestions=suggestions or [],
        evidence=evidence,
    )


def create_error_output(
    message: str,
    exception: Exception | None = None,
) -> CheckOutput:
    """Create an error check output.

    Args:
        message: Error message
        exception: The exception that occurred

    Returns:
        CheckOutput with status="error"
    """
    evidence = {}
    if exception:
        evidence["exception_type"] = type(exception).__name__
        evidence["exception_message"] = str(exception)

    return CheckOutput(
        status="error",
        message=message,
        confidence=0.0,
        evidence=evidence,
    )


def create_inconclusive_output(
    message: str,
    confidence: float = 0.5,
    suggestions: list[str] | None = None,
    **evidence: Any,
) -> CheckOutput:
    """Create an inconclusive check output.

    Args:
        message: Explanation of why inconclusive
        confidence: Confidence level (typically low)
        suggestions: Suggestions for manual verification
        **evidence: Additional evidence details

    Returns:
        CheckOutput with status="inconclusive"
    """
    return CheckOutput(
        status="inconclusive",
        message=message,
        confidence=confidence,
        suggestions=suggestions or [],
        evidence=evidence,
    )


__all__ = [
    # Models
    "FoundEvidence",
    "LocateResult",
    "CheckOutput",
    # Factory functions
    "create_pass_output",
    "create_fail_output",
    "create_error_output",
    "create_inconclusive_output",
]
