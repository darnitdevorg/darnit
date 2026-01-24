"""Core data models for the baseline MCP server."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING

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
    details: Optional[Dict[str, Any]] = None
    evidence: Optional[str] = None
    source: str = "builtin"  # Which adapter produced this result

    def to_dict(self) -> Dict[str, Any]:
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
    changes_made: List[str] = field(default_factory=list)
    requires_manual_action: bool = False
    manual_steps: List[str] = field(default_factory=list)
    source: str = "builtin"


@dataclass
class AdapterCapability:
    """Describes what controls an adapter can handle."""
    control_ids: Set[str]  # Specific control IDs, or {"*"} for all
    supports_batch: bool = False  # Can handle multiple controls in one call
    batch_command: Optional[str] = None  # Command for batch mode
    # TODO: Add cache_key for shared execution context
    # cache_key: Optional[str] = None  # Key for caching tool output (e.g., "scorecard")


# TODO: Shared Execution Context (Future Enhancement)
# Add ExecutionContext class for sharing tool outputs across controls.
# This enables tools like OpenSSF Scorecard to run once and provide
# results for multiple controls.
#
# @dataclass
# class ExecutionContext:
#     """Shared context for an audit run, enabling result caching across controls.
#
#     Example usage:
#         context = ExecutionContext(owner="org", repo="repo", local_path="/path")
#
#         # Adapter caches its output
#         scorecard_data = context.get_or_run_tool(
#             "scorecard",
#             lambda: run_scorecard(context.local_path)
#         )
#
#         # Extract specific control result
#         return extract_branch_protection_result(scorecard_data)
#     """
#     owner: str
#     repo: str
#     local_path: str
#
#     # Cached tool outputs (scorecard JSON, trivy results, etc.)
#     tool_outputs: Dict[str, Any] = field(default_factory=dict)
#
#     # Cached GitHub API responses
#     api_responses: Dict[str, Any] = field(default_factory=dict)
#
#     # Already-computed check results
#     cached_results: Dict[str, CheckResult] = field(default_factory=dict)
#
#     def get_or_run_tool(self, tool_key: str, run_func: Callable) -> Any:
#         """Get cached tool output or run the tool and cache result."""
#         if tool_key not in self.tool_outputs:
#             self.tool_outputs[tool_key] = run_func()
#         return self.tool_outputs[tool_key]
#
#     def get_cached_result(self, control_id: str) -> Optional[CheckResult]:
#         """Get a previously cached check result."""
#         return self.cached_results.get(control_id)
#
#     def cache_result(self, result: CheckResult) -> None:
#         """Cache a check result for later retrieval."""
#         self.cached_results[result.control_id] = result


@dataclass
class AuditResult:
    """Complete result structure for baseline audit."""
    owner: str
    repo: str
    local_path: str
    level: int
    default_branch: str
    all_results: List[Dict[str, Any]]
    summary: Optional[Dict[str, int]] = None  # Status counts: PASS, FAIL, WARN, N/A, ERROR, total
    level_compliance: Optional[Dict[int, bool]] = None  # Level -> compliance status
    timestamp: Optional[str] = None  # ISO format timestamp
    project_config: Optional[Any] = None  # ProjectConfig, but avoid circular import
    config_was_created: bool = False
    config_was_updated: bool = False
    config_changes: List[str] = field(default_factory=list)
    skipped_controls: Dict[str, str] = field(default_factory=dict)
    commit: Optional[str] = None
    ref: Optional[str] = None
