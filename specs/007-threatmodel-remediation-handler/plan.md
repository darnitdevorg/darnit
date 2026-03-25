# Implementation Plan: Threat Model Remediation Handler

**Branch**: `007-threatmodel-remediation-handler` | **Date**: 2026-03-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/007-threatmodel-remediation-handler/spec.md`

## Summary

Wire the existing `generate_threat_model` analysis pipeline as a sieve remediation handler for SA-03.02, replacing the static `file_create` + template approach. The new handler follows the standard `(config, context) -> HandlerResult` pattern, reuses the dynamic STRIDE engine, and falls back to the static template on failure.

## Technical Context

**Language/Version**: Python >=3.11 (project targets 3.11/3.12)
**Primary Dependencies**: darnit (core framework — sieve handler registry), darnit-baseline (threat model engine)
**Storage**: N/A (writes a single file to the repository)
**Testing**: pytest (`uv run pytest tests/ -v`)
**Target Platform**: Cross-platform (CLI/MCP tool)
**Project Type**: Library (MCP server with plugin handlers)
**Performance Goals**: Same as current remediation — completes in seconds
**Constraints**: No new external dependencies; handler must use sieve handler registry, not MCP tool registry
**Scale/Scope**: 1 new handler function, 1 TOML config update, 1 handler registration call

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Plugin Separation | PASS | Handler registered via sieve handler registry from `darnit-baseline`. No changes to `darnit` core. |
| II. Conservative-by-Default | PASS | Fallback to static template ensures remediation never fails. File not overwritten by default. |
| III. TOML-First Architecture | PASS | SA-03.02 remediation config updated in TOML. No new controls. |
| IV. Never Guess User Values | PASS | Threat model is auto-generated from code analysis, not user-specific values. No user judgment required. |
| V. Sieve Pipeline Integrity | PASS | Sieve verification passes unchanged. Only remediation handler affected. |

**Post-Phase 1 Re-check**: All gates still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/007-threatmodel-remediation-handler/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: research decisions
├── quickstart.md        # Phase 1: development guide
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
packages/darnit-baseline/src/darnit_baseline/
├── threat_model/
│   └── remediation.py     # NEW: sieve remediation handler wrapping generate_threat_model
├── implementation.py      # MODIFY: register new handler with sieve handler registry
└── tools.py               # UNCHANGED (existing MCP tool stays as-is)

packages/darnit-baseline/
└── openssf-baseline.toml  # MODIFY: SA-03.02 remediation config uses new handler

tests/darnit_baseline/threat_model/
└── test_remediation.py    # NEW: tests for the remediation handler
```

**Structure Decision**: Monorepo with separate packages. New handler in a single new file (`remediation.py`) within the existing `threat_model/` subpackage. TOML config change in `openssf-baseline.toml`. Handler registration added to `implementation.py`.

## Complexity Tracking

No constitution violations. No complexity justifications needed.
