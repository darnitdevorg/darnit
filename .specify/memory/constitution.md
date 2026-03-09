<!--
Sync Impact Report
==================
Version change: 1.0.0 → 1.1.0
Modified principles:
  - IV. Never Guess User Values: expanded to explicitly permit
    confidence-based auto-acceptance when configured in TOML.
    Core requirement unchanged (never silently apply values),
    but now acknowledges configurable thresholds as a valid
    verification mechanism.
Added sections: none
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ no changes needed
  - .specify/templates/spec-template.md ✅ no changes needed
  - .specify/templates/tasks-template.md ✅ no changes needed
  - specs/001-tiered-control-automation/ ✅ FR-004 already aligned
Follow-up TODOs: none
==================
-->

# Darnit Constitution

## Core Principles

### I. Plugin Separation

The `darnit` core framework MUST NOT import implementation packages.
All framework-to-implementation communication MUST go through the
`ComplianceImplementation` protocol and Python entry points.
Implementation packages MAY import the framework freely.

- Framework package (`packages/darnit/`) MUST have zero import-time
  dependencies on any implementation package.
- New protocol methods MUST be guarded with `hasattr()` for backward
  compatibility.
- Missing implementations MUST degrade gracefully (empty results,
  log warning), never crash.

### II. Conservative-by-Default

This is a compliance auditing tool. Incorrect results are worse than
incomplete results. Every design decision MUST follow this hierarchy:

- A control that has not been explicitly verified as passing is NOT
  compliant. Period.
- WARN ("needs verification") MUST be treated the same as FAIL for
  compliance calculations.
- False negatives (reporting failure when passing) are always
  preferable to false positives (reporting pass when failing).
- No level may be reported as "Compliant" if any control at that
  level is unverified, errored, or pending.

### III. TOML-First Architecture

All controls MUST be defined in the implementation's TOML configuration
file. Python code MUST NOT be the source of truth for control metadata.

- New controls MUST be defined entirely in TOML with passes, metadata,
  severity, and help URLs.
- The `rules/catalog.py` fallback exists for backward compatibility
  only and MUST NOT receive new entries.
- CEL expressions in TOML MUST follow documented escaping rules
  (single-quoted literal strings, `\.` not `\\.` for regex dots).
- TOML controls MUST overwrite Python-registered controls
  (`overwrite=True`).

### IV. Never Guess User Values

The framework MUST NOT silently apply values that require user
judgment. All auto-detected values MUST go through an explicit,
configurable verification mechanism.

- When `auto_detect = false` in TOML, the sieve MUST NOT run for
  that key. No exceptions.
- "Context Confirmation Required" is a hard stop — the tool MUST
  ask the user rather than filling values from heuristics.
- Sieve auto-detection is acceptable ONLY for keys where
  `auto_detect = true` in the TOML definition.
- Auto-acceptance of detected values MAY use a confidence-based
  threshold (e.g., `auto_accept_confidence = 0.8`), but this
  MUST be explicitly configured per-implementation in TOML —
  never implicit or hard-coded. Implementations MUST be able to
  force manual confirmation for all fields by setting the
  threshold to 1.0.
- LLM-facing prompts MUST NOT contain guessed values in executable
  code snippets.

### V. Sieve Pipeline Integrity

The 4-phase verification pipeline (`file_must_exist → exec/regex →
llm_eval → manual`) MUST be respected. The orchestrator stops at
the first conclusive result.

- Each pass type MUST have well-defined PASS / FAIL / INCONCLUSIVE
  semantics.
- CEL `expr` fields are evaluated as a universal post-handler step
  in the orchestrator, not inside individual handlers.
- A handler returning INCONCLUSIVE MUST cause the pipeline to
  continue to the next phase, never short-circuit to PASS.

## Architecture Constraints

The project follows a three-layer architecture:

- **Layer 1 — Checking (sieve passes):** Built-in handlers
  (`file_must_exist`, `exec`, `pattern`, `manual`) plus plugin
  Python functions. Determines control status.
- **Layer 2 — Remediation:** Built-in actions (`file_create`, `exec`,
  `api_call`, `project_update`) plus plugin Python functions.
  Fixes compliance gaps.
- **Layer 3 — MCP Tools:** Built-in tools (`audit`, `remediate`,
  `list_controls`) plus custom plugin handlers registered via
  `register_handlers()`. Exposes functionality to AI assistants.

"Built-in" means different things at each layer. Implementations
MUST NOT conflate them.

Package structure:

- `packages/darnit/` — Core framework
- `packages/darnit-baseline/` — OpenSSF Baseline implementation
- `packages/darnit-testchecks/` — Test implementation

## Development Workflow

All changes MUST pass the following before merge:

1. **Lint**: `uv run ruff check .` — zero errors.
2. **Tests**: `uv run pytest tests/ --ignore=tests/integration/ -q`
   — all pass.
3. **Spec sync**: `uv run python scripts/validate_sync.py --verbose`
   — framework-design spec matches implementation.
4. **Generated docs**: `uv run python scripts/generate_docs.py` then
   check `git diff docs/generated/` — commit any changes.
5. **Upstream rebase**: `git fetch upstream && git rebase upstream/main`
   before pushing (fork-based workflow).

Spec changes MUST update the spec first, then validate sync, then
regenerate docs.

## Governance

This constitution supersedes ad-hoc practices. Amendments require:

1. A description of the change and its rationale.
2. Update to this document with version bump.
3. Validation that dependent templates and docs remain consistent.

Version follows semantic versioning:
- MAJOR: Principle removal or incompatible redefinition.
- MINOR: New principle or materially expanded guidance.
- PATCH: Clarifications, wording, non-semantic refinements.

Compliance with these principles MUST be verified during code review.
The CLAUDE.md project instructions serve as the runtime development
guidance and MUST remain consistent with this constitution.

**Version**: 1.1.0 | **Ratified**: 2026-03-08 | **Last Amended**: 2026-03-08
