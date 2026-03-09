# Implementation Plan: Tiered Control Automation Pipeline

**Branch**: `001-tiered-control-automation` | **Date**: 2026-03-08 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-tiered-control-automation/spec.md`

## Summary

Increase the percentage of OpenSSF Baseline controls that produce
conclusive audit results (PASS/FAIL) without user interaction by
adding new TOML-defined passes to currently-manual controls. The
approach adds deterministic passes (exec, file_must_exist, pattern)
where possible, LLM evaluation passes as a middle tier for content
quality assessment, and configurable confidence-based context
auto-acceptance. No new pipeline phases — leverages the existing
cascading pass model in TOML declaration order.

## Technical Context

**Language/Version**: Python >=3.11 (project targets 3.11/3.12)
**Primary Dependencies**: darnit (core framework), darnit-baseline
(OpenSSF implementation), celpy (CEL expressions), pydantic (models)
**Storage**: TOML config files, `.project/` YAML context, local filesystem
**Testing**: pytest (unit + integration, `tests/` directory)
**Target Platform**: Cross-platform CLI + MCP server
**Project Type**: Library + CLI + MCP server (plugin architecture)
**Performance Goals**: <30s per deterministic remediation, full audit
completes without timeout for repos with <1000 files
**Constraints**: Must not break existing audit results; TOML-first;
conservative-by-default (no false positives)
**Scale/Scope**: 62 controls across 3 levels; ~94 manual passes to
evaluate for automation; ~15 context fields for auto-detection

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Plugin Separation | PASS | All changes to controls go in `darnit-baseline` TOML. Framework changes (if any) go through protocol. No cross-package imports. |
| II. Conservative-by-Default | PASS | New passes return INCONCLUSIVE on uncertainty, never PASS. FR-011 enforces this. |
| III. TOML-First Architecture | PASS | All new passes defined in TOML. No new Python control definitions. FR-012 enforces this. |
| IV. Never Guess User Values | PASS | Context auto-acceptance configurable per-implementation. `auto_detect = false` respected. FR-010 enforces this. |
| V. Sieve Pipeline Integrity | PASS | Uses existing cascade model. CEL post-handler evaluation unchanged. FR-001 enforces declaration-order execution. |

No violations. No complexity tracking needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-tiered-control-automation/
├── plan.md              # This file
├── research.md          # Phase 0: control analysis & automation opportunities
├── data-model.md        # Phase 1: entity models for confidence & evidence
├── quickstart.md        # Phase 1: how to add automated passes to a control
├── contracts/           # Phase 1: TOML schema extensions, protocol additions
└── tasks.md             # Phase 2: implementation tasks (/speckit.tasks)
```

### Source Code (repository root)

```text
packages/
├── darnit/
│   └── src/darnit/
│       ├── sieve/
│       │   └── orchestrator.py      # Evidence accumulation, tier tagging
│       ├── core/
│       │   └── plugin.py            # ControlSpec, HandlerResult updates
│       └── config/
│           └── context.py           # Confidence model for context fields
│
├── darnit-baseline/
│   └── src/darnit_baseline/
│       ├── openssf-baseline.toml    # PRIMARY: new passes for manual controls
│       ├── config/
│       │   ├── context.py           # Context auto-detection enhancements
│       │   └── mappings.py          # New file discovery patterns
│       └── remediation/
│           └── templates/           # New/enhanced remediation templates
│
└── tests/
    ├── darnit/
    │   └── sieve/
    │       └── test_orchestrator.py  # Tier tagging, evidence cascade tests
    └── darnit_baseline/
        ├── test_new_passes.py        # Verify new TOML passes work
        └── test_context_confidence.py # Confidence threshold tests
```

**Structure Decision**: Existing monorepo package structure. Changes
span both `darnit` (framework: confidence model, tier tagging) and
`darnit-baseline` (implementation: new TOML passes, context detection).
Framework changes are minimal and go through the protocol.

## Complexity Tracking

No constitution violations to justify.
