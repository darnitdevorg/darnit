# Research: Tiered Control Automation Pipeline

**Date**: 2026-03-08
**Feature**: [spec.md](spec.md)

## Decision 1: Automation Strategy for Manual Controls

**Decision**: Three-wave approach — TOML-only quick wins first, then
investigation fixes, then LLM expansion.

**Rationale**: 59 of 62 controls have manual passes. Of those, 44 are
hybrid (already have automated passes alongside manual fallback) and
15 are manual-only. The hybrid controls are the fastest to improve
because the automation infrastructure already exists — we just need
to verify it works and remove redundant manual blocks. Manual-only
controls need new TOML passes added.

**Alternatives considered**:
- All-at-once: Higher risk, harder to validate incremental progress.
- LLM-first: Would skip easy deterministic wins; LLM passes are
  harder to test and validate.

## Decision 2: Control Categorization

**Decision**: Controls fall into 5 automation categories based on
current analysis of `openssf-baseline.toml`.

### Category A: File Existence (7 controls) — Add deterministic passes

These manual-only controls check for files that already have
discovery patterns and remediation templates defined. Adding
`file_must_exist` + `pattern` passes is pure TOML work.

| Control | Level | What to add |
|---------|-------|-------------|
| OSPS-DO-01.01 | L1 | file_must_exist for README variants |
| OSPS-GV-03.01 | L1 | file_must_exist for CONTRIBUTING variants |
| OSPS-LE-01.01 | L1 | file_must_exist for LICENSE variants |
| OSPS-LE-03.01 | L1 | file_must_exist + pattern for license text |
| OSPS-QA-02.01 | L1 | file_must_exist for dependency manifests |
| OSPS-VM-02.01 | L1 | file_must_exist for SECURITY.md |
| OSPS-GV-01.01 | L2 | file_must_exist for GOVERNANCE variants |

### Category B: Redundant Manual Cleanup (17 controls) — Remove manual fallback

These hybrid controls already have fully deterministic `exec` passes
with CEL expressions that produce conclusive results. The manual pass
is dead code — the exec pass resolves before reaching it.

Controls: OSPS-AC-01.01, AC-02.01, AC-03.01, AC-03.02, BR-01.02,
BR-02.01, BR-02.02, BR-03.01, GV-02.01, LE-02.01, LE-02.02,
LE-03.02, QA-01.01, QA-01.02, QA-03.01, QA-07.01, VM-04.01

**Note**: Before removing manual passes, verify that the remaining
automated passes fully cover the control's checking requirements.
Manual passes MAY be removed when automated coverage is sufficient
(FR-013). If an exec pass depends on `gh` auth that may be
unavailable, keeping the manual fallback is prudent. The goal is
every control ends up with equal or better coverage.

### Category C: Heuristic Enhancement (3 controls) — Add pattern passes

These manual-only controls can be partially automated with keyword
pattern matching before falling back to manual.

| Control | Level | Pattern strategy |
|---------|-------|-----------------|
| OSPS-DO-06.01 | L2 | Pattern for dependency management keywords |
| OSPS-VM-01.01 | L2 | Pattern for disclosure process keywords |
| OSPS-SA-02.01 | L2 | file_must_exist for API docs + pattern |

### Category D: LLM Evaluation (4 controls) — Add llm_eval passes

These controls require assessing content quality — whether a document
adequately covers a topic. Pattern matching catches presence but not
adequacy. LLM evaluation fills this gap.

| Control | Level | LLM prompt strategy |
|---------|-------|-------------------|
| OSPS-SA-01.01 | L2 | "Does this document explain the system architecture and design decisions?" |
| OSPS-DO-03.02 | L3 | "Does this document explain how to verify release author identity?" |
| OSPS-DO-04.01 | L3 | "Does this document define the scope and duration of support?" |
| OSPS-DO-05.01 | L3 | "Does this document describe the end-of-support policy?" |

### Category E: Investigation Required (3 controls)

These hybrid controls have automated passes that may not be working
correctly. Need diagnosis before deciding automation path.

| Control | Level | Issue |
|---------|-------|-------|
| OSPS-VM-03.01 | L2 | Has exec for private reporting API but still reaches manual |
| OSPS-VM-05.03 | L3 | Named "Automated" scanning but manual-only |
| OSPS-BR-04.01 | L2 | Has exec for releases but manual for changelog content |

## Decision 3: Confidence Model for Context Fields

**Decision**: Two-level confidence with configurable threshold.

- **High confidence (0.9+)**: Canonical source match — value extracted
  from its authoritative file (e.g., maintainers from CODEOWNERS,
  license from LICENSE file SPDX header).
- **Low confidence (0.3–0.6)**: Heuristic inference — value inferred
  from indirect signals (e.g., governance model guessed from repo
  structure, security contact inferred from git history).

Default auto-accept threshold: 0.8. Configurable per-implementation
in TOML via `auto_accept_confidence`. Setting to 1.0 forces manual
confirmation for all fields.

**Rationale**: Numeric scores allow implementers fine-grained control.
The two-level default (canonical=high, heuristic=low) matches the
spec clarification while enabling `> 0.8 auto-accepted` expressions.

**Alternatives considered**:
- Boolean only (auto-accept yes/no): Too coarse. Doesn't allow
  threshold tuning.
- Three-level (high/medium/low): Adds complexity without clear
  benefit over a continuous score with a threshold.

## Decision 4: Evidence and Tier Tagging

**Decision**: Extend existing `SieveResult` to include pass-level
evidence trail and resolving pass metadata.

The existing `pass_history` field on `SieveResult` already captures
per-pass results. The enhancement adds:
- `resolving_pass_index`: Which pass in the cascade produced the
  conclusive result.
- `resolving_pass_handler`: The handler type that resolved it
  (e.g., "exec", "pattern", "llm_eval").
- Per-pass evidence is already captured in the cascade loop.

**Rationale**: Minimal framework change. The orchestrator already
accumulates evidence per pass — we just need to tag which pass
was conclusive and surface that in the result.

**Alternatives considered**:
- New TierResult wrapper: Over-engineered for what is essentially
  one additional field on the existing model.
- Tier enum (DETERMINISTIC/HEURISTIC/LLM/MANUAL): The handler name
  already implies the tier. Adding a separate enum would require
  maintaining a handler→tier mapping that could drift.

## Decision 5: TOML Schema for Confidence Configuration

**Decision**: Add optional `auto_accept_confidence` to implementation
TOML config section and optional `confidence` field per context
field definition.

```toml
# In implementation config section
[config]
auto_accept_confidence = 0.8  # Default threshold

# Per context field (in .project/ mapper or TOML)
[config.context.maintainers]
auto_detect = true
confidence = 0.9  # Canonical source (CODEOWNERS)

[config.context.governance_model]
auto_detect = true
confidence = 0.4  # Heuristic inference
```

**Rationale**: Follows TOML-first principle. Implementers configure
thresholds declaratively. Framework reads threshold and compares
against field confidence to decide auto-accept vs prompt.

**Alternatives considered**:
- Python-only configuration: Violates TOML-first principle.
- Per-control confidence: Too granular. Confidence is a property of
  the context field detection method, not the control.

## Projected Impact

### Level 1 (25 controls)
- Current conclusive: ~16 (64%)
- Category A adds: 5 deterministic (DO-01.01, GV-03.01, LE-01.01,
  LE-03.01, QA-02.01, VM-02.01 — 6 are L1)
- Projected conclusive: ~22 (88%) — exceeds SC-001 target of 80%

### Level 2 (17 controls)
- Current conclusive: ~9 (53%)
- Category A adds: 1 (GV-01.01)
- Category C adds: 3 (DO-06.01, VM-01.01, SA-02.01)
- Category D adds: 1 (SA-01.01)
- Projected conclusive: ~14 (82%) — exceeds SC-002 target of 70%

### Level 3 (20 controls)
- Category D adds: 3 (DO-03.02, DO-04.01, DO-05.01)
- Category E investigation may add: 1-3
- Improvement proportional but not targeted by success criteria
