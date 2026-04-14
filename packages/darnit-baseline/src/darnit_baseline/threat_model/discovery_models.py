"""Data model for the tree-sitter based discovery pipeline.

These types power the tree-sitter discovery pipeline. They live in a separate
module from the legacy ``models.py`` types, which are retained only for
backward compatibility of the ``StrideCategory`` enum.

See `specs/010-threat-model-ast/data-model.md` for the authoritative definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .models import StrideCategory  # reuse the existing enum values

# ---------------------------------------------------------------------------
# Location & source context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Location:
    """A source file position range.

    All line and column numbers are 1-indexed. End positions are inclusive.
    """

    file: str
    line: int
    column: int
    end_line: int
    end_column: int

    def __post_init__(self) -> None:
        if self.line < 1:
            raise ValueError(f"Location.line must be >= 1, got {self.line}")
        if self.end_line < self.line:
            raise ValueError(f"Location.end_line ({self.end_line}) must be >= line ({self.line})")


@dataclass(frozen=True)
class CodeSnippet:
    """Source-code context attached to a finding or asset.

    `lines` is the tuple of raw lines (no trailing newlines). `start_line` is
    the 1-indexed line number of `lines[0]`. `marker_line` is the absolute
    (1-indexed) line number that the finding anchors to; it must satisfy
    `start_line <= marker_line < start_line + len(lines)`.
    """

    lines: tuple[str, ...]
    start_line: int
    marker_line: int

    def __post_init__(self) -> None:
        if not self.lines:
            raise ValueError("CodeSnippet must contain at least one line")
        if self.marker_line < self.start_line:
            raise ValueError(f"CodeSnippet.marker_line ({self.marker_line}) must be >= start_line ({self.start_line})")
        if self.marker_line >= self.start_line + len(self.lines):
            raise ValueError(
                f"CodeSnippet.marker_line ({self.marker_line}) is out of range "
                f"(start_line={self.start_line}, len(lines)={len(self.lines)})"
            )


# ---------------------------------------------------------------------------
# Asset kinds
# ---------------------------------------------------------------------------


class EntryPointKind(str, Enum):
    HTTP_ROUTE = "http_route"
    MCP_TOOL = "mcp_tool"
    CLI_COMMAND = "cli_command"
    MESSAGE_HANDLER = "message_handler"


class DataStoreKind(str, Enum):
    RELATIONAL_DB = "relational_db"
    DOCUMENT_DB = "document_db"
    KEY_VALUE = "key_value"
    OBJECT_STORE = "object_store"
    FILE_IO = "file_io"


#: EntryPoint kinds for which `framework` must be set (a handler registered
#: through no identifiable framework is almost always a bug). CLI and message
#: handlers are allowed to leave `framework=None`.
_ENTRY_POINT_KINDS_REQUIRING_FRAMEWORK: frozenset[EntryPointKind] = frozenset(
    {EntryPointKind.HTTP_ROUTE, EntryPointKind.MCP_TOOL}
)


def _asset_id(kind_prefix: str, language: str, location: Location) -> str:
    """Generate a stable, deterministic asset ID.

    IDs are built from the asset kind, language, file path, and line number.
    They are stable across runs on an unchanged repository (matching FR-031's
    statelessness guarantee) and unique enough to disambiguate assets at
    distinct locations.
    """
    return f"{kind_prefix}:{language}:{location.file}:{location.line}"


@dataclass(frozen=True)
class DiscoveredEntryPoint:
    """An attack-surface entry point discovered by a tree-sitter query.

    Named ``Discovered*`` to distinguish from the legacy
    ``threat_model.models.EntryPoint`` type which has a different shape.

    The ``id`` field is derived from ``kind``, ``language``, and ``location``;
    callers must not pass an override unless they know what they're doing.
    """

    kind: EntryPointKind
    name: str
    location: Location
    language: str
    framework: str | None
    route_path: str | None
    http_method: str | None
    has_auth_decorator: bool
    source_query: str
    id: str = ""  # derived in __post_init__

    def __post_init__(self) -> None:
        if not self.id:
            # frozen dataclass — use object.__setattr__ to assign
            object.__setattr__(self, "id", _asset_id("ep", self.language, self.location))
        if self.kind in _ENTRY_POINT_KINDS_REQUIRING_FRAMEWORK and self.framework is None:
            raise ValueError(f"DiscoveredEntryPoint with kind={self.kind} must set framework")


@dataclass(frozen=True)
class DiscoveredDataStore:
    """A data-storage asset discovered by a constructor-call query.

    At least one of ``import_evidence`` or ``dependency_manifest_evidence``
    MUST be set — a data store with no corroborating evidence would be the
    same kind of low-signal finding the regex pipeline used to produce.
    """

    kind: DataStoreKind
    technology: str
    location: Location
    language: str
    import_evidence: str | None
    dependency_manifest_evidence: str | None
    source_query: str
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", _asset_id("ds", self.language, self.location))
        if self.import_evidence is None and self.dependency_manifest_evidence is None:
            raise ValueError(
                "DiscoveredDataStore must have at least one of import_evidence or dependency_manifest_evidence set"
            )


@dataclass(frozen=True)
class CallGraphNode:
    """Intra-module adjacency record for DFD rendering and enclosing-function context."""

    function_name: str
    location: Location
    language: str
    calls: frozenset[str]
    is_exported: bool


# ---------------------------------------------------------------------------
# Candidate findings
# ---------------------------------------------------------------------------


class FindingSource(str, Enum):
    TREE_SITTER_STRUCTURAL = "tree_sitter_structural"
    OPENGREP_PATTERN = "opengrep_pattern"
    OPENGREP_TAINT = "opengrep_taint"


@dataclass(frozen=True)
class DataFlowStep:
    location: Location
    content: str


@dataclass(frozen=True)
class DataFlowTrace:
    """Intra-procedural data-flow trace from Opengrep taint mode.

    All locations (source, sink, and intermediate steps) MUST be in the same
    file — Opengrep 1.6.0 only supports intra-procedural taint, so any
    cross-file claim would be unreliable. Future Opengrep releases with
    ``--taint-intrafile`` may relax this (see research.md §6).
    """

    source: DataFlowStep
    intermediate: tuple[DataFlowStep, ...]
    sink: DataFlowStep

    def __post_init__(self) -> None:
        expected_file = self.source.location.file
        if self.sink.location.file != expected_file:
            raise ValueError(
                "DataFlowTrace.sink must be in the same file as source "
                f"(source={expected_file}, sink={self.sink.location.file})"
            )
        for step in self.intermediate:
            if step.location.file != expected_file:
                raise ValueError(
                    "DataFlowTrace.intermediate step must be in the same file "
                    f"as source (source={expected_file}, step={step.location.file})"
                )


@dataclass(frozen=True)
class CandidateFinding:
    """Pre-verification finding produced by the discovery layer.

    The ranking heuristic uses ``severity * confidence`` as its primary key.

    Invariants enforced in ``__post_init__``:

    - ``severity`` in 1..10 (inclusive)
    - ``confidence`` in 0.0..1.0 (inclusive)
    - ``data_flow`` is set iff ``source == FindingSource.OPENGREP_TAINT``
    - ``code_snippet.marker_line == primary_location.line`` — the embedded
      snippet's ``>>>`` marker must point at the finding's anchor line so
      reviewers see the right line highlighted
    """

    category: StrideCategory
    title: str
    source: FindingSource
    primary_location: Location
    related_assets: tuple[str, ...]
    code_snippet: CodeSnippet
    severity: int
    confidence: float
    rationale: str
    query_id: str
    data_flow: DataFlowTrace | None = None
    enclosing_function: str | None = None
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not (1 <= self.severity <= 10):
            raise ValueError(f"severity must be in 1..10, got {self.severity}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in 0.0..1.0, got {self.confidence}")
        if self.source == FindingSource.OPENGREP_TAINT and self.data_flow is None:
            raise ValueError("CandidateFinding with source=OPENGREP_TAINT must have data_flow set")
        if self.source != FindingSource.OPENGREP_TAINT and self.data_flow is not None:
            raise ValueError("CandidateFinding with data_flow set must have source=OPENGREP_TAINT")
        if self.code_snippet.marker_line != self.primary_location.line:
            raise ValueError(
                "CandidateFinding.code_snippet.marker_line "
                f"({self.code_snippet.marker_line}) must equal "
                f"primary_location.line ({self.primary_location.line})"
            )


# ---------------------------------------------------------------------------
# Scan accounting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileScanStats:
    """Surfaced in HandlerResult.evidence and in the Limitations section.

    Field semantics:

    - ``total_files_seen`` — files the walker visited *after* descending into
      non-excluded directories. Files inside pruned vendor directories are
      never counted here.
    - ``excluded_dir_count`` — number of directories pruned during the walk
      (vendor/build/gitignore-listed). Surfaces in the draft as "we chose not
      to descend into N directories".
    - ``unsupported_file_count`` — files we walked past that had no supported
      language (``README.md``, ``.png``, etc.). Counts toward "seen but not
      parsed".
    - ``in_scope_files`` — files actually parsed by tree-sitter.
    - ``total_files_seen == unsupported_file_count + in_scope_files``.
    """

    total_files_seen: int
    excluded_dir_count: int
    unsupported_file_count: int
    in_scope_files: int
    by_language: dict[str, int]
    shallow_mode: bool
    shallow_threshold: int

    def __post_init__(self) -> None:
        expected = self.unsupported_file_count + self.in_scope_files
        if self.total_files_seen != expected:
            raise ValueError(
                f"FileScanStats.total_files_seen ({self.total_files_seen}) must "
                f"equal unsupported_file_count + in_scope_files ({expected})"
            )


@dataclass(frozen=True)
class TrimmedOverflow:
    """Per-category counts of candidates ranked out of the draft by the finding cap."""

    by_category: dict[StrideCategory, int]
    total: int

    def __post_init__(self) -> None:
        if self.total != sum(self.by_category.values()):
            raise ValueError(
                f"TrimmedOverflow total ({self.total}) must equal sum of "
                f"by_category values ({sum(self.by_category.values())})"
            )


# ---------------------------------------------------------------------------
# Orchestration result
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryResult:
    """Single aggregated result returned by ``discovery.discover_all``."""

    entry_points: list[DiscoveredEntryPoint] = field(default_factory=list)
    data_stores: list[DiscoveredDataStore] = field(default_factory=list)
    call_graph: list[CallGraphNode] = field(default_factory=list)
    findings: list[CandidateFinding] = field(default_factory=list)
    file_scan_stats: FileScanStats | None = None
    opengrep_available: bool = False
    opengrep_degraded_reason: str | None = None


# ---------------------------------------------------------------------------
# Finding group (multi-file output)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FindingGroup:
    """A distinct vulnerability class identified by a tree-sitter query ID.

    Groups all :class:`CandidateFinding` instances that share the same
    ``query_id`` into a single unit for per-class detail file rendering.
    """

    query_id: str
    slug: str
    stride_category: StrideCategory
    class_name: str
    mitigation_hint: str
    findings: tuple[CandidateFinding, ...]
    max_severity_score: float

    def __post_init__(self) -> None:
        if len(self.findings) == 0:
            raise ValueError("FindingGroup must contain at least one finding")
        for f in self.findings:
            if f.query_id != self.query_id:
                raise ValueError(
                    f"All findings in a FindingGroup must share the same query_id "
                    f"(expected {self.query_id!r}, got {f.query_id!r})"
                )
        expected_slug = self.query_id.replace(".", "-")
        if self.slug != expected_slug:
            raise ValueError(
                f"FindingGroup.slug must be query_id.replace('.', '-') (expected {expected_slug!r}, got {self.slug!r})"
            )


# ---------------------------------------------------------------------------
# Mitigation sidecar types
# ---------------------------------------------------------------------------


class MitigationStatus(str, Enum):
    """Status of a reviewer's mitigation decision."""

    MITIGATED = "mitigated"
    ACCEPTED = "accepted"
    FALSE_POSITIVE = "false_positive"
    UNMITIGATED = "unmitigated"


@dataclass(frozen=True)
class MitigationEntry:
    """One reviewer decision about a specific finding instance.

    Stored in ``.project/threatmodel/mitigations.yaml``.
    """

    fingerprint: str
    status: MitigationStatus
    note: str = ""
    reviewer: str = ""
    reviewed_at: str = ""
    query_id: str = ""  # For human readability; not used for matching
    file_hint: str = ""  # Last-known file path; not used for matching
    stale: bool = False


@dataclass
class MitigationSidecar:
    """Container for all mitigation decisions in a project."""

    entries: list[MitigationEntry] = field(default_factory=list)


__all__ = [
    "Location",
    "CodeSnippet",
    "EntryPointKind",
    "DataStoreKind",
    "DiscoveredEntryPoint",
    "DiscoveredDataStore",
    "CallGraphNode",
    "FindingSource",
    "DataFlowStep",
    "DataFlowTrace",
    "CandidateFinding",
    "FileScanStats",
    "TrimmedOverflow",
    "DiscoveryResult",
    "FindingGroup",
    "MitigationStatus",
    "MitigationEntry",
    "MitigationSidecar",
]
