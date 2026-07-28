<!--
Sync Impact Report
==================
Version change: 1.2.0 -> 1.3.0
Modified principles:
  - IV. Never Guess User Values: narrowed from a prohibition on
    detection to a prohibition on concluding. Detection MAY now run
    for a user-judgment key for the sole purpose of producing a
    candidate to show a person; the candidate MUST NOT be consumed
    as the key's value by control verification results, compliance
    calculations, remediation action inputs, generated attestations,
    or persisted project context. Human confirmation remains the only
    transition that makes a value usable.
Rationale for MINOR rather than MAJOR:
  The core requirement -- the framework MUST NOT silently apply
  values requiring user judgment -- is unchanged. Only the permitted
  mechanism widens: producing a value and using a value were
  previously conflated in a single sentence, and this amendment
  separates them. This matches the justification recorded at
  1.0.0 -> 1.1.0, where this same principle was widened to permit
  confidence-based auto-acceptance and was classified MINOR on the
  grounds that the core requirement stayed intact. Per the Governance
  section, MAJOR is reserved for principle removal or incompatible
  redefinition; no existing guarantee is withdrawn here.
Reconciliation, not authorization:
  The propose-only mechanism already ships. `allow_sieve_hints` and
  `hint_sources` exist in the framework schema, and the OpenSSF
  Baseline configuration enables them for `maintainers` and
  `security_contact`. The previous wording therefore misdescribed the
  system. This amendment corrects the document, not the behavior; no
  code, configuration, or test changes accompany it.
Added guidance:
  - The flag pair is now stated explicitly: `auto_detect` governs
    concluding, `allow_sieve_hints` governs proposing. The safety
    property is enforced by the pair rather than by a ban on
    detection.
  - The confidence-threshold provision is now scoped to keys that do
    NOT require user judgment. It previously read as unscoped, which
    left it applicable to user-judgment keys by omission.
  - A confirmation must record when it was made, by whom, and which
    candidate it was based on, and may expire after a configurable
    period. The period is deliberately not fixed here.
Added sections: none
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md -- no changes needed
  - .specify/templates/spec-template.md -- no changes needed
  - .specify/templates/tasks-template.md -- no changes needed
Dependent documents updated in the same change:
  - CLAUDE.md (Conservative-by-Default section)
  - ARCHITECTURE.md (normative restatement and the auto_detect note)
  - docs/design/CONTEXT_PROMPTS.md, docs/IMPLEMENTATION_GUIDE.md
  - docs/rfcs/0001-core-rearchitecture.md (Stage 0 row)
Deliberately not updated:
  - packages/ code, configuration, and their comments. Changing them
    would change behavior, which this amendment does not do. They are
    enumerated in specs/018-auto-detect-propose-only/research.md.
Amendment track:
  - Merged under this document's own Governance section: description,
    version bump, consistency validation. No Charter vote.
    GOVERNANCE.md:51 omits the constitution from the artifacts
    requiring a TSC vote deliberately. The TSC is an oversight body
    and does not take a day-to-day role, so routine amendments that
    preserve a principle's core requirement do not go to it.
==================

Sync Impact Report
==================
Version change: 1.1.0 -> 1.2.0
Modified sections:
  - Development Workflow: item 3 (Spec sync) reworded to match the
    narrower scope of the trimmed validate_sync.py (TOML schema,
    handler-name registry, SARIF source); item 4 (Generated docs)
    removed entirely (scripts/generate_docs.py and docs/generated/
    were deleted in feature 016-openspec-migration); item 5
    (Upstream rebase) renumbered to item 4. Closing sentence
    "regenerate docs" clause removed.
Modified principles: none (the five Core Principles I-V are
  unchanged in substance).
Added sections: none
Removed sections: none
Authoritative spec relocation: framework-design spec moved from
  openspec/specs/framework-design/spec.md to
  docs/architecture/framework-design.md. The constitution did not
  cite the openspec path by name in narrative text; the implicit
  reference in Workflow item 3 ("framework-design spec") now resolves
  to the new path automatically.
Templates requiring updates:
  - .specify/templates/plan-template.md -- no changes needed
  - .specify/templates/spec-template.md -- no changes needed
  - .specify/templates/tasks-template.md -- no changes needed
Follow-up TODOs: none
==================

Sync Impact Report
==================
Version change: 1.0.0 -> 1.1.0
Modified principles:
  - IV. Never Guess User Values: expanded to explicitly permit
    confidence-based auto-acceptance when configured in TOML.
    Core requirement unchanged (never silently apply values),
    but now acknowledges configurable thresholds as a valid
    verification mechanism.
Added sections: none
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md -- no changes needed
  - .specify/templates/spec-template.md -- no changes needed
  - .specify/templates/tasks-template.md -- no changes needed
  - specs/001-tiered-control-automation/ -- FR-004 already aligned
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

A key marked `auto_detect = false` is a user-judgment key: its
correct value requires a person's decision rather than observation.
For such a key the framework MAY propose a candidate, but MUST NOT
conclude the value on its own.

- Detection MAY run for a user-judgment key for the sole purpose of
  producing a candidate to show a person. Producing a candidate is
  not applying it.
- A candidate MUST NOT be consumed as the key's value by any of:
  control verification results, compliance calculations, remediation
  action inputs, generated attestations, or persisted project
  context. Until it is confirmed, a user-judgment key is unverified,
  and unverified counts as FAIL (Principle II).
- A candidate shown to a person MUST be labelled as unconfirmed and
  MUST carry its origin -- how it was produced. Origin is not
  confidence: a high-confidence guess is still a guess.
- Human confirmation is the only transition that makes a value
  usable. Persisting a candidate does not confirm it, and a stored
  candidate MUST remain distinguishable from a confirmed value on
  every later read.
- A confirmation MUST record when it was made, by whom, and which
  candidate it was based on. A confirmation MAY expire after a
  configurable period, after which the key reverts to a candidate
  and MUST be confirmed again. This constitution does not fix that
  period.
- "Context Confirmation Required" is a hard stop — the tool MUST
  ask the user rather than filling values from heuristics.
- Two flags govern two separate axes: `auto_detect` governs whether
  a value may be concluded without a person, and `allow_sieve_hints`
  governs whether a detected value may be proposed as a candidate.
  Both default to false. The safety property is enforced by the pair,
  not by a prohibition on detection.
- For keys that do NOT require user judgment, auto-acceptance of
  detected values MAY use a confidence-based threshold (e.g.,
  `auto_accept_confidence = 0.8`), but this MUST be explicitly
  configured per-implementation in TOML, never implicit or
  hard-coded. Implementations MUST be able to force manual
  confirmation for all such fields by setting the threshold to 1.0.
  No threshold, at any value, authorizes concluding a user-judgment
  key.
- LLM-facing prompts MUST NOT contain guessed values or unconfirmed
  candidates in executable code snippets.

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
   -- validates TOML schema, handler-name registry consistency
   against `docs/architecture/framework-design.md`, and that the
   SARIF formatter reads from TOML (not from a deprecated catalog).
4. **Upstream rebase**: `git fetch upstream && git rebase upstream/main`
   before pushing (fork-based workflow).

Spec changes MUST update `docs/architecture/framework-design.md`
first, then validate sync.

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

**Version**: 1.3.0 | **Ratified**: 2026-03-08 | **Last Amended**: 2026-07-28
