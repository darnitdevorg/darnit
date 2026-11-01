"""Core data models for the baseline MCP server."""

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
class ExecutionContext:
    """Shared context for an audit run, passed to every handler as ``execution_context``."""

    owner: str
    repo: str
    local_path: str

    # Feature 031: allowlist of external MCP servers (merged framework +
    # operator configuration, per-name replacement) available to the built-in
    # ``mcp`` sieve handler. Values are ``McpServerConfig`` instances but
    # typed as ``Any`` here to avoid a config->core import cycle. Empty
    # dict is the pre-feature default -- audits that never consult an
    # MCP server pay zero cost.
    mcp_servers: dict[str, Any] = field(default_factory=dict)

    # Feature 033: pluggable-stores bundle (four backends: project state,
    # attestation, report, audit cache). Typed as Any to avoid an
    # import cycle with darnit.stores. Populated by run_sieve_audit
    # after resolving the effective stores config; None on paths that
    # bypass the audit driver (legacy or unit-test constructions).
    stores: Any = None


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
    trust: dict[str, Any] | None = None  # Feature 040: trust decision report block
