# Data Model: Tiered Control Automation Pipeline

**Date**: 2026-03-08
**Feature**: [spec.md](spec.md)

## Entity: HandlerResult (existing — enhanced)

**Location**: `packages/darnit/src/darnit/core/plugin.py`

Existing fields (no changes):
- `status`: str — PASS, FAIL, WARN, ERROR, INCONCLUSIVE, PENDING_LLM
- `message`: str — Human-readable explanation
- `evidence`: dict — Handler-specific evidence data
- `confidence`: float | None — Handler's confidence in result
- `details`: dict | None — Additional metadata

No new fields needed. The `confidence` field already exists and
handlers can populate it.

## Entity: SieveResult (existing — enhanced)

**Location**: `packages/darnit/src/darnit/sieve/orchestrator.py`

Existing fields (no changes):
- `status`: str — Final control status
- `evidence`: dict — Accumulated evidence from all passes
- `conclusive_phase`: str | None — Which phase was conclusive
- `pass_history`: list[dict] — Per-pass results in cascade order

New fields:
- `resolving_pass_index`: int | None — Index (0-based) of the pass
  in `handler_invocations` that produced the conclusive result.
  None if no pass was conclusive (fell through to WARN).
- `resolving_pass_handler`: str | None — Handler name of the
  resolving pass (e.g., "exec", "pattern", "llm_eval", "manual").
  Derived from the handler invocation at `resolving_pass_index`.

**State transitions**:
```
INCONCLUSIVE → (next pass) → INCONCLUSIVE → ... → PASS|FAIL|ERROR
                                                    ↑ resolving_pass_index set
INCONCLUSIVE → (all passes) → WARN (no resolving pass)
```

## Entity: ContextField (new)

**Location**: `packages/darnit/src/darnit/config/context.py` (new)
or extend existing context handling.

Fields:
- `name`: str — Field identifier (e.g., "maintainers",
  "security_contact", "governance_model")
- `value`: Any — The detected or user-provided value
- `source`: str — One of: "canonical", "heuristic", "user_provided",
  "user_confirmed"
- `confidence`: float — 0.0 to 1.0. Canonical sources default to
  0.9+, heuristic inferences default to 0.3–0.6.
- `detection_method`: str — How the value was obtained (e.g.,
  "CODEOWNERS_parse", "git_history_inference", "github_api",
  "user_input")
- `auto_accepted`: bool — Whether the field was auto-accepted
  (confidence >= threshold) or required user confirmation.

**Lifecycle**:
```
[not collected] → auto_detect → [detected: canonical|heuristic]
                                     │
                      ┌──────────────┴──────────────┐
                      ▼                              ▼
              confidence >= threshold         confidence < threshold
              source = "canonical"            source = "heuristic"
              auto_accepted = true            auto_accepted = false
                                                     │
                                              prompt user
                                                     │
                                    ┌────────────────┴────────────┐
                                    ▼                              ▼
                              user confirms                 user overrides
                              source = "user_confirmed"     source = "user_provided"
                              auto_accepted = false         auto_accepted = false
```

## Entity: ConfidenceConfig (new)

**Location**: Implementation TOML config section.

Fields:
- `auto_accept_confidence`: float — Threshold above which fields
  are auto-accepted. Default: 0.8. Range: 0.0 (accept everything)
  to 1.0 (manual confirmation for all).

Per-field overrides (optional):
- `[config.context.<field_name>].confidence`: float — Override
  default confidence for a specific detection method.
- `[config.context.<field_name>].auto_detect`: bool — Existing
  flag. When false, field is never auto-detected regardless of
  confidence config.

## Relationships

```
Control (TOML)
  └── has many: HandlerInvocation (passes array)
       └── produces: HandlerResult (per pass)
            └── accumulated into: SieveResult
                 └── tagged with: resolving_pass_index/handler

Project Context
  └── has many: ContextField
       └── governed by: ConfidenceConfig (threshold)
            └── determines: auto_accepted flag
```

## Validation Rules

- `confidence` MUST be in range [0.0, 1.0]
- `auto_accept_confidence` MUST be in range [0.0, 1.0]
- `resolving_pass_index` MUST be None when status is WARN
  (no pass was conclusive)
- `resolving_pass_index` MUST be set when status is PASS, FAIL,
  or ERROR
- `source` MUST be "canonical" or "heuristic" for auto-detected
  fields; "user_provided" or "user_confirmed" after user interaction
- Fields with `auto_detect = false` MUST have source = "user_provided"
  (never auto-detected)
