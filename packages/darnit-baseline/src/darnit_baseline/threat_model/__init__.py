"""Threat modeling capabilities using STRIDE methodology.

This module provides automated threat analysis for codebases using
tree-sitter structural parsing and optional Opengrep taint analysis:

- Asset discovery (entry points, auth, data stores)
- STRIDE-based finding categorization
- Severity × confidence ranking with top-N cap
- Report generation (Markdown, SARIF, JSON)

Usage:
    from darnit_baseline.threat_model.ts_discovery import discover_all
    from darnit_baseline.threat_model.ranking import rank_findings, apply_cap
    from darnit_baseline.threat_model.ts_generators import (
        generate_markdown_threat_model,
    )

    result = discover_all(Path("/path/to/repo"))
    ranked = rank_findings(result.findings)
    emitted, overflow = apply_cap(ranked, max_findings=50)
    report = generate_markdown_threat_model(
        repo_path="/path/to/repo",
        result=result,
        capped_findings=emitted,
        overflow=overflow,
    )
"""

# Data models (new pipeline)
from .discovery_models import (
    CallGraphNode,
    CandidateFinding,
    CodeSnippet,
    DataFlowStep,
    DataFlowTrace,
    DataStoreKind,
    DiscoveredDataStore,
    DiscoveredEntryPoint,
    DiscoveryResult,
    EntryPointKind,
    FileScanStats,
    FindingGroup,
    FindingSource,
    Location,
    MitigationEntry,
    MitigationSidecar,
    MitigationStatus,
    TrimmedOverflow,
)

# Legacy data models (kept for backward compatibility of the models module)
from .models import (
    StrideCategory,
)

# Remediation handler
from .remediation import generate_threat_model_handler

__all__ = [
    # Enums
    "StrideCategory",
    "EntryPointKind",
    "DataStoreKind",
    "FindingSource",
    # Data classes
    "Location",
    "CodeSnippet",
    "DiscoveredEntryPoint",
    "DiscoveredDataStore",
    "CallGraphNode",
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
    # Remediation
    "generate_threat_model_handler",
]
