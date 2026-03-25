# Implementation Plan: Detailed STRIDE Threat Modeling

**Branch**: `006-detailed-stride-threats` | **Date**: 2026-03-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-detailed-stride-threats/spec.md`

## Summary

Enhance the `generate_threat_model` MCP tool to produce richer STRIDE threat reports: exploitation scenarios from predefined templates, data-flow impact descriptions, ranked controls with rationale, Mermaid data-flow diagrams, attack chain detection via predefined STRIDE category combination patterns, and a `detail_level` parameter for summary vs. detailed output. Breaking change: default output is "detailed".

## Technical Context

**Language/Version**: Python >=3.11 (project targets 3.11/3.12)
**Primary Dependencies**: darnit (core framework), darnit-baseline (implementation package) — no new external dependencies
**Storage**: N/A (generates reports from static analysis; no persistence)
**Testing**: pytest (`uv run pytest tests/ -v`)
**Target Platform**: Cross-platform (CLI/MCP tool)
**Project Type**: Library (MCP server with tool endpoints)
**Performance Goals**: Report generation within same order of magnitude as current (~seconds for typical repos)
**Constraints**: No new external dependencies; all new code in `darnit-baseline` package only
**Scale/Scope**: 6 STRIDE categories × ~10 threat sub-types; 5 predefined chain patterns; 2 detail levels

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Plugin Separation | PASS | All changes in `darnit-baseline` (implementation package). No changes to `darnit` core framework. |
| II. Conservative-by-Default | PASS | Feature enhances reporting detail; does not change compliance determination logic. Risk scoring algorithm unchanged. |
| III. TOML-First Architecture | PASS | No new controls defined. Feature modifies threat model generation, not control definitions. |
| IV. Never Guess User Values | PASS | No user-specific values auto-detected. Exploitation scenarios are templates, not guesses. |
| V. Sieve Pipeline Integrity | PASS | Sieve pipeline not modified. Feature is entirely within the threat model subsystem. |

**Post-Phase 1 Re-check**: All gates still PASS. New dataclasses and modules stay within `darnit-baseline`. No framework imports added.

## Project Structure

### Documentation (this feature)

```text
specs/006-detailed-stride-threats/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: research decisions
├── data-model.md        # Phase 1: entity extensions
├── quickstart.md        # Phase 1: development guide
├── contracts/
│   └── mcp-tool-contract.md  # Phase 1: MCP tool interface changes
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
packages/darnit-baseline/src/darnit_baseline/
└── threat_model/
    ├── models.py          # MODIFY: extend Threat, ThreatAnalysis; add RankedControl, AttackChain, DetailLevel
    ├── scenarios.py       # NEW: exploitation scenario templates per threat sub-type
    ├── chains.py          # NEW: attack chain pattern definitions and detection
    ├── stride.py          # MODIFY: populate new Threat fields during analysis
    ├── generators.py      # MODIFY: Mermaid DFD, detail_level, attack chains, empty categories
    ├── __init__.py        # MODIFY: export new types and functions
    └── patterns.py        # UNCHANGED

packages/darnit-baseline/src/darnit_baseline/
└── tools.py               # MODIFY: add detail_level parameter to generate_threat_model()

tests/darnit_baseline/threat_model/
├── test_models.py         # NEW: backward compat, new field defaults
├── test_scenarios.py      # NEW: template coverage, step count validation
├── test_chains.py         # NEW: pattern matching, composite risk, shared-asset tiebreaker
├── test_generators.py     # NEW: detail levels, Mermaid output, empty categories, grouping
└── test_integration.py    # NEW: end-to-end pipeline with sample fixtures
```

**Structure Decision**: Monorepo with separate packages. All source changes in `packages/darnit-baseline/`. Two new modules (`scenarios.py`, `chains.py`) added to the existing `threat_model/` subpackage. Tests mirror the source structure under `tests/darnit_baseline/threat_model/`.

## Complexity Tracking

No constitution violations. No complexity justifications needed.
