"""Core data models for the baseline MCP server."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class CheckStatus(Enum):
    """Status of a control check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    NA = "na"
    ERROR = "error"


@dataclass
class CheckResult:
    """Result of a single control check."""

    control_id: str
    status: CheckStatus
    message: str
    level: int = 1  # OSPS maturity level (1, 2, or 3)
    details: dict[str, Any] | None = None
    evidence: str | None = None
    source: str = "builtin"  # Which adapter produced this result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format matching existing _result() output."""
        return {
            "id": self.control_id,
            "status": self.status.value.upper(),
            "details": self.message,
            "level": self.level,
            "source": self.source,
        }


@dataclass
class RemediationResult:
    """Result of a remediation action."""

    control_id: str
    success: bool
    message: str
    changes_made: list[str] = field(default_factory=list)
    requires_manual_action: bool = False
    manual_steps: list[str] = field(default_factory=list)
    source: str = "builtin"


@dataclass
class AdapterCapability:
    """Describes what controls an adapter can handle."""

    control_ids: set[str]  # Specific control IDs, or {"*"} for all
    supports_batch: bool = False  # Can handle multiple controls in one call
    batch_command: str | None = None  # Command for batch mode
    cache_key: str | None = None  # Key for caching tool output (e.g., "scorecard")


@dataclass
class ExecutionContext:
    """Shared context for an audit run, enabling result caching across controls.

    This context is thread-safe to support concurrent tool evaluations.

    Example usage:
        context = ExecutionContext(owner="org", repo="repo", local_path="/path")

        # Adapter caches its output
        scorecard_data = context.get_or_run_tool(
            "scorecard",
            lambda: run_scorecard(context.local_path)
        )

        # Extract specific control result
        return extract_branch_protection_result(scorecard_data)
    """

    owner: str
    repo: str
    local_path: str

    # Cached tool outputs (scorecard JSON, trivy results, etc.)
    tool_outputs: dict[str, Any] = field(default_factory=dict)

    # Cached GitHub API responses
    api_responses: dict[str, Any] = field(default_factory=dict)

    # Already-computed check results
    cached_results: dict[str, CheckResult] = field(default_factory=dict)

    # Threading locks
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _tool_locks: dict[str, threading.Lock] = field(default_factory=dict, init=False, repr=False)

    def get_or_run_tool(self, tool_key: str, run_func: Callable[[], Any]) -> Any:
        """Get cached tool output or run the tool and cache result.

        Uses fine-grained locking to prevent redundant concurrent executions
        of the same tool while allowing different tools to run in parallel.
        """
        # Fast path check
        with self._lock:
            if tool_key in self.tool_outputs:
                return self.tool_outputs[tool_key]

            # Get or create a lock specific to this tool
            tool_lock = self._tool_locks.setdefault(tool_key, threading.Lock())

        with tool_lock:
            # Check again while inside the tool lock
            if tool_key in self.tool_outputs:
                return self.tool_outputs[tool_key]

            # Actually run the tool
            result = run_func()

            with self._lock:
                self.tool_outputs[tool_key] = result

        return result

    def get_cached_result(self, control_id: str) -> CheckResult | None:
        """Get a previously cached check result."""
        with self._lock:
            return self.cached_results.get(control_id)

    def cache_result(self, result: CheckResult) -> None:
        """Cache a check result for later retrieval."""
        with self._lock:
            self.cached_results[result.control_id] = result


@dataclass
class AuditResult:
    """Complete result structure for baseline audit."""

    owner: str
    repo: str
    local_path: str
    level: int
    default_branch: str
    all_results: list[dict[str, Any]]
    summary: dict[str, int] | None = None  # Status counts: PASS, FAIL, WARN, N/A, ERROR, total
    level_compliance: dict[int, bool] | None = None  # Level -> compliance status
    timestamp: str | None = None  # ISO format timestamp
    project_config: Any | None = None  # ProjectConfig, but avoid circular import
    config_was_created: bool = False
    config_was_updated: bool = False
    config_changes: list[str] = field(default_factory=list)
    skipped_controls: dict[str, str] = field(default_factory=dict)
    commit: str | None = None
    ref: str | None = None
