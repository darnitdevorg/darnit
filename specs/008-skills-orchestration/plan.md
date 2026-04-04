# Implementation Plan: Skills-Based Orchestration Layer with Audit Profiles

**Branch**: `008-skills-orchestration` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/008-skills-orchestration/spec.md`

## Summary

Add a skills-based orchestration layer that provides structured compliance workflows (`/audit`, `/context`, `/comply`, `/remediate`) as Claude Code skill definitions. Skills invoke darnit's MCP tools as building blocks, with Claude's reasoning as fallback for partial results. Additionally, add first-class audit profile support (issue #140) allowing implementation modules to define named subsets of controls in TOML, filterable across audit, context, and remediation layers.

## Technical Context

**Language/Version**: Python >=3.11 (project targets 3.11/3.12)
**Primary Dependencies**: darnit (core framework), darnit-baseline (implementation), FastMCP, Pydantic >=2.0, PyYAML, cel-python
**Storage**: `.project/project.yaml` (YAML), `.baseline.toml` (TOML), framework TOML configs
**Testing**: pytest with `@pytest.mark.unit` markers
**Target Platform**: Claude Code (skills), CLI (darnit commands), MCP server
**Project Type**: CLI tool + MCP server + Claude Code skills (prompt templates)
**Performance Goals**: Skills should complete within the same wall-clock time as the equivalent manual MCP tool sequence
**Constraints**: Skills are prompt templates (`.md` files), not Python runtime code. Audit profiles are TOML-defined, no Python needed from implementation authors.
**Scale/Scope**: 4 skills, 1 TOML schema extension, ~5 Python files modified for profile support

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Plugin Separation | PASS | Skills call MCP tools which go through the protocol. `get_audit_profiles()` uses `hasattr()` guard. Framework never imports implementations. |
| II. Conservative-by-Default | PASS | Skills preserve WARN-as-FAIL semantics. No auto-pass logic added. PENDING_LLM resolved by Claude with full evidence visibility. |
| III. TOML-First Architecture | PASS | Audit profiles defined in TOML `[audit_profiles]` section. No Python code needed for profile definition. |
| IV. Never Guess User Values | PASS | `/context` skill presents auto-detected values for confirmation, never silently applies. Skippable questions. |
| V. Sieve Pipeline Integrity | PASS | Skills call `audit_openssf_baseline` MCP tool which delegates to `run_sieve_audit()`. No bypass of the 4-phase pipeline. |

All gates pass. Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/008-skills-orchestration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (via /speckit.tasks)
```

### Source Code (repository root)

```text
# Skills (new files — prompt templates)
packages/darnit-baseline/skills/
├── audit.md             # /audit skill definition
├── context.md           # /context skill definition
├── comply.md            # /comply skill definition
└── remediate.md         # /remediate skill definition

# Audit profiles — Python changes (framework)
packages/darnit/src/darnit/
├── config/
│   ├── framework_schema.py   # Add AuditProfileConfig to schema
│   └── profile_resolver.py   # New: profile name resolution and control ID filtering
├── core/
│   └── plugin.py              # Document get_audit_profiles() optional method
├── tools/
│   └── audit.py               # Add profile filtering to run_sieve_audit()
├── sieve/
│   └── orchestrator.py        # No changes (profile filtering happens before sieve)
└── cli.py                     # Add --profile flag to audit/plan/remediate commands

# Audit profiles — TOML changes (implementation)
packages/darnit-baseline/
└── openssf-baseline.toml      # Add [audit_profiles] section with example profiles

# Audit profiles — MCP tool changes
packages/darnit-baseline/src/darnit_baseline/
├── tools.py                   # Add profile parameter to audit/remediate tools
└── implementation.py          # Add get_audit_profiles() method

# Tests
tests/darnit/
├── config/
│   └── test_audit_profiles.py  # Profile schema parsing, filtering
├── tools/
│   └── test_audit_profile_filter.py  # Profile filtering in run_sieve_audit
└── test_cli.py                 # --profile flag parsing
tests/darnit_baseline/
└── test_profiles.py            # Baseline-specific profile tests
```

**Structure Decision**: Skills are `.md` files in the implementation package (since they reference implementation-specific MCP tools). Profile support touches the framework schema, CLI, and audit pipeline for filtering, plus the implementation for TOML definitions and protocol method.

## Constitution Re-Check (Post Phase 1)

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Plugin Separation | PASS | `AuditProfileConfig` in framework schema; `get_audit_profiles()` optional via `hasattr()`. Profile resolution in framework, profile definitions in implementation TOML. |
| II. Conservative-by-Default | PASS | Profile filtering only narrows the control set — never adds unverified controls. WARN semantics unchanged. |
| III. TOML-First Architecture | PASS | Profiles defined entirely in TOML. `AuditProfileConfig` is a Pydantic model for parsing, not a source of truth. |
| IV. Never Guess User Values | PASS | Skills present auto-detected context for confirmation. No new auto-apply paths. |
| V. Sieve Pipeline Integrity | PASS | Profile filtering happens before sieve entry. `run_sieve_audit(controls=...)` pre-filters; sieve sees a normal control list. |

All gates pass post-design. No complexity violations.
