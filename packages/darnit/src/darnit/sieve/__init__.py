"""Progressive verification sieve system for darnit.

The sieve system implements a 4-phase verification pipeline:
1. DETERMINISTIC - File existence, API checks, config lookups
2. PATTERN - Regex matching, content analysis
3. LLM - LLM-assisted analysis (returns PENDING_LLM for consultation)
4. MANUAL - Always returns WARN with verification steps

Usage:
    from darnit.sieve import SieveOrchestrator, get_control_registry, CheckContext

    registry = get_control_registry()
    orchestrator = SieveOrchestrator()

    for spec in registry.get_specs_by_level(1):
        context = CheckContext(owner="org", repo="repo", local_path="/path")
        result = orchestrator.verify(spec, context)
"""

from .models import (
    VerificationPhase,
    PassOutcome,
    PassResult,
    ControlSpec,
    CheckContext,
    SieveResult,
)
from .passes import (
    DeterministicPass,
    ExecPass,
    PatternPass,
    LLMPass,
    ManualPass,
)
from .orchestrator import SieveOrchestrator
from .registry import ControlRegistry, get_control_registry

__all__ = [
    # Models
    "VerificationPhase",
    "PassOutcome",
    "PassResult",
    "ControlSpec",
    "CheckContext",
    "SieveResult",
    # Passes
    "DeterministicPass",
    "ExecPass",
    "PatternPass",
    "LLMPass",
    "ManualPass",
    # Orchestrator
    "SieveOrchestrator",
    # Registry
    "ControlRegistry",
    "get_control_registry",
]
