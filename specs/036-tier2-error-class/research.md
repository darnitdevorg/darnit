# Phase 0: Research -- Distinguishable Side-Effect Failures via `error_class`

**Feature**: 036-tier2-error-class | **Date**: 2026-09-07

All items resolved by direct source inspection. Clarify (4 questions) left
no NEEDS CLARIFICATION markers; these are the plan-phase implementation
decisions the spec's checklist notes flagged.

## R-001: Where does the `ErrorClass` type live, and what shape?

**Question**: clarify Q2 chose a strict `Literal`. Where does it go, and
what's the precedent?

**Decision**: New module-level type alias in
`packages/darnit/src/darnit/core/error_class.py`, mirroring
`packages/darnit/src/darnit/core/authority.py:15` exactly:

```python
ErrorClass = Literal["network", "auth", "timeout", "rate_limit", "not_found", "crashed"]
```

**Rationale**: `core/authority.py` is the established precedent for a
small cross-cutting `Literal` that both the sieve layer and the
implementation packages import. It has its own module (not buried in
`handler_registry.py`) precisely so `darnit-baseline`'s attestation code
can import the type without pulling in the sieve registry. `error_class`
has the identical import topology: sieve handlers produce it, the audit
driver propagates it, `darnit-baseline`'s predicate and formatters
consume it.

**Alternatives considered**:
- Define inline in `handler_registry.py` next to `HandlerResult`. Rejected:
  forces `darnit-baseline` to import the sieve registry just to reference
  the type, which is a heavier import than needed and diverges from the
  `authority` precedent.
- A `StrEnum`. Rejected: `authority` uses `Literal` and the two fields
  will sit side by side on the same dataclass; matching shapes keeps the
  code readable. `Literal` also serializes to plain JSON strings with no
  `.value` access.

## R-002: `HandlerResult` and `CheckResult` extension points

**Question**: exactly where do the new fields land?

**Decision**:

`HandlerResult` (`sieve/handler_registry.py:76-81`) is a `@dataclass`
with fields `status`, `message`, `confidence`, `evidence`, `details`,
`authority`. Add `error_class: ErrorClass | None = None` as the last
field (keeps positional-arg compatibility for any caller constructing
positionally, though all in-tree callers use kwargs).

`CheckResult` (`sieve/models.py:119-156`) is a `TypedDict` with a
Required block and a `NotRequired` block. Add
`error_class: NotRequired[str]` to the optional block, adjacent to
`authority: NotRequired[str]` which sits there for exactly the same
reason (additive, back-compat with pre-feature serialized results).

`SieveResult` (`sieve/models.py:158+`, `@dataclass`) is the producer that
`to_legacy_dict()` converts into `CheckResult`. It needs the field too so
the conversion has something to read.

**Rationale**: All three follow the `authority` field's precedent from
feature 025 -- same three objects, same additive placement, same
`NotRequired`/`| None = None` shapes.

**Note on FR-009a (resolving-pass propagation)**: `SieveResult` already
carries `resolving_pass_index` and `resolving_pass_handler`, so the
orchestrator already knows which pass resolved the control. Populating
`SieveResult.error_class` from that pass's `HandlerResult.error_class`
is a one-line assignment at the same place those two fields are set.

## R-003: `_apply_cel_expr` preservation (FR-009)

**Question**: does the CEL post-step drop fields when it constructs a new
`HandlerResult`?

**Decision**: YES, it currently does -- and this is the subtlest part of
the feature.

`orchestrator.py:_apply_cel_expr` (lines 88-180 area) has four exit
paths. In the "agreement" branch (both handler and CEL point the same
way) it constructs a **brand-new** `HandlerResult(...)` rather than
mutating the incoming one. Feature 026 already hit this exact bug with
`authority` and fixed it by explicitly threading
`authority=handler_result.authority` through the constructor (see the
comment at line ~145: "Feature 026 bug fix: carry the incoming
handler_result.authority through so downstream reporting doesn't see
'unknown'").

`error_class` needs the identical treatment at every construction site
inside `_apply_cel_expr`. The transition table from the docstring:

| Handler | CEL true | CEL false |
|---|---|---|
| PASS | PASS | INCONCLUSIVE |
| FAIL | INCONCLUSIVE | FAIL |

Plus two pass-through paths (no `expr` configured; handler returned
ERROR/INCONCLUSIVE) which return the original object unchanged and are
therefore already safe.

**Rationale**: This is a known-shape bug class in this exact function.
SC-005 requires a test parameterized over all four transitions
specifically because the failure mode is silent (a dropped field, not an
exception).

**Alternatives considered**: refactor `_apply_cel_expr` to use
`dataclasses.replace()` instead of constructing new instances, which
would make field-dropping structurally impossible. Attractive but a
larger blast radius than this feature warrants -- noted as a follow-up
candidate.

## R-004: Where do the GitHub stderr-classification patterns live?

**Question**: clarify Q4 scoped classification to GitHub-only for v0.
Framework-level constants, per-handler config, or implementation-level?

**Decision**: Module-level constants in
`packages/darnit/src/darnit/sieve/builtin_handlers.py`, adjacent to the
existing `MCP_DEFAULT_TIMEOUT_SECONDS` / `_FILE_DISCOVERY_PRUNE_DIRS`
constants:

```python
_GH_RATE_LIMIT_PATTERNS = (...)   # "API rate limit exceeded", "secondary rate limit", "abuse detection"
_GH_AUTH_PATTERNS = (...)         # "HTTP 401", "Bad credentials", "requires authentication", ...
```

**Rationale**: The `exec` handler is framework-level (it ships in
`packages/darnit/`), so its classification logic is framework-level too.
Putting the patterns in framework TOML would let an implementation
override them, but no implementation has asked for that, and TOML-First
(Principle III) governs **control metadata**, not framework-internal
heuristics. Keeping them as code constants makes them reproducible
across implementations -- exactly the property clarify Q4's answer
wanted.

**Alternatives considered**:
- Framework TOML config keys. Rejected as premature; no consumer.
- `darnit-baseline`-level. Rejected: violates Principle I -- the `exec`
  handler is core and must not reach into an implementation for its
  heuristics.

## R-005: Attestation predicate schema version

**Question**: does adding `error_class` need a predicate version bump?

**Decision**: NO. Additive within the existing v1 predicate.

`darnit-baseline/attestation/predicate.py:96-101` shows feature 025
adding `authority` to the per-control dict with exactly this pattern:

```python
if r.get("authority") is not None:
    control["authority"] = r["authority"]
```

Field is emitted only when present; absent for results that don't carry
one. Consumers must ignore unknown fields, which the in-toto predicate
contract already requires. `error_class` gets the same conditional-emit
treatment immediately after the `authority` block.

**Rationale**: Direct precedent in the same file, same schema version,
same additive shape. Feature 025's spec explicitly documented this as
"additively within v1".

## R-006: Formatter extension points

**Question**: where exactly do the three formatters need touching?

**Decision**: Three sites, all already carrying analogous optional
fields:

1. **Markdown** -- `tools/audit.py:918-931` already renders
   "Resolved by: `<handler>` (pass #N)" and "Pass history: ..." when the
   optional fields are present. `error_class` slots in as another
   conditional line in the same block. FR-010's rendering can follow
   the existing shape.
2. **JSON** -- `darnit-baseline/tools.py:206-238`. Two shapes exist:
   full JSON (serializes all `CheckResult` fields) and summary JSON
   (strips to `id`/`status`/`level`/`details`). Per FR-011, `error_class`
   goes in **both** -- it's operationally important enough that the
   summary shape should carry it (a summary that hides "we couldn't
   verify" defeats the feature's purpose).
3. **SARIF** -- `darnit-baseline/formatters/sarif.py:383-391` appends
   to `sarif_result["properties"]` with the same
   `if X is not None: properties[camelCaseKey] = X` pattern. `error_class`
   becomes `properties["errorClass"]` (SARIF properties use camelCase in
   this file: `resolvingPassHandler`, `resolvingPassIndex`, `passHistory`).

**Rationale**: All three formatters already have an established pattern
for optional transparency fields. This feature adds one more field to
each, no structural change.

**Note**: FR-011 says "absent when not present (not `null`)". All three
sites use `if X is not None` guards, so this falls out for free.

## R-007: MCP handler exception -> `error_class` mapping

**Question**: FR-006 names three exception types. Are there others in the
MCP pool that should map?

**Decision**: `sieve/mcp_pool.py` defines eight exception types under
`McpPoolError`:

| Exception | `error_class` | Rationale |
|---|---|---|
| `McpToolTimeout` | `timeout` | FR-006, explicit |
| `McpServerHandshakeFailed` | `network` | FR-006, explicit |
| `McpServerBinaryMissing` | `not_found` | FR-006, explicit |
| `McpServerVerificationFailed` | `auth` | Sigstore verification failure is an auth-shaped problem |
| `McpServerUnusable` | `network` | Generic "server won't work" -> network bucket |
| `McpToolError` | `crashed` | Tool ran but errored internally |
| `McpToolResponseNotJson` | `crashed` | Tool ran, produced garbage |
| `McpPoolError` (base) | `crashed` | Catch-all fallback |

**Rationale**: FR-006 names three; the other five exist in the same
module and the handler's `except` clauses will catch them. Leaving them
unclassified would produce the exact ambiguity this feature exists to
remove. The mapping above is documented in the contract so the choices
are reviewable rather than implicit.

**Note**: This slightly widens FR-006's letter (three named) while
honoring its spirit (MCP failures are classified). Recorded here rather
than silently expanding scope; if the reviewer disagrees, the extra five
can collapse to `crashed` with no other change.

## Summary

| ID | Item | Resolution |
|----|------|-----------|
| R-001 | `ErrorClass` type location | New `core/error_class.py`, mirrors `core/authority.py:15` |
| R-002 | Field placement | `HandlerResult` (dataclass), `SieveResult` (dataclass), `CheckResult` (TypedDict `NotRequired`) -- all following `authority`'s precedent |
| R-003 | CEL post-step preservation | Confirmed bug: `_apply_cel_expr` constructs new `HandlerResult`s; must thread `error_class` at each of 4 construction sites (feature 026 hit the same bug with `authority`) |
| R-004 | stderr pattern location | Module constants in `sieve/builtin_handlers.py` |
| R-005 | Predicate version | No bump; additive within v1, same pattern as feature 025's `authority` |
| R-006 | Formatter sites | markdown `tools/audit.py:918-931`, JSON `darnit-baseline/tools.py:206-238` (both full + summary), SARIF `formatters/sarif.py:383-391` as `properties["errorClass"]` |
| R-007 | MCP exception mapping | 8 exception types mapped; 3 from FR-006 plus 5 documented extensions |

No unknowns block Phase 1.
