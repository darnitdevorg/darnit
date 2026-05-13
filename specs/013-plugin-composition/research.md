# Phase 0 Research: Composition of compliance implementations

**Feature**: 013-plugin-composition · **Date**: 2026-05-13

The clarify session resolved the two highest-impact ambiguities (strict-by-default conflicts; recursive composition is allowed). This document captures the remaining design-shaped questions surfaced during planning, the chosen answer, and the alternatives considered. No `NEEDS CLARIFICATION` markers remain in the plan after this phase.

## R-001 — Where does composition resolution run?

- **Decision**: Inside `load_framework_config(path)` in `packages/darnit/src/darnit/config/merger.py`. When the parsed `FrameworkConfig` has a non-empty `compose` list, the loader delegates to `darnit.core.composition.resolve_composition(...)` BEFORE returning.
- **Rationale**: Resolution must happen exactly once per `FrameworkConfig` load and must produce a config object indistinguishable from a non-composite's. The loader is the only chokepoint every call site already passes through (CLI, audit tools, registry validation). Putting resolution behind a separate "composite loader" would force every call site to branch.
- **Alternatives considered**:
  - **At plugin-discovery time (in `core/discovery.py`)**: rejected — discovery returns `ComplianceImplementation` instances, not `FrameworkConfig` objects. The TOML hasn't been parsed yet.
  - **Lazy / on first `get_all_controls()` call**: rejected — performance is fine at load time (SC-002), and lazy resolution moves cycle errors from "registration time" to "first audit", which violates FR-012's "at registration time" requirement.
  - **In a separate wrapper `load_composite_framework_config(...)`**: rejected — forces callers to know whether a framework is composite. The spec is explicit (Assumption: "Composites are themselves discoverable") that composites must look like non-composites to consumers.

## R-002 — How are source frameworks fetched during resolution?

- **Decision**: The composition resolver is the **single recursive entrypoint** for composition resolution. Its `source_loader` parameter returns a **parsed-but-not-resolved** `FrameworkConfig` for any given source slug. A new internal helper `_parse_framework_only(path: Path) -> FrameworkConfig` in `darnit.config.merger` does the pydantic parse + template-path validation but **does NOT invoke `resolve_composition`**. The default `source_loader` does slug → path lookup via the existing `PluginRegistry` and then calls `_parse_framework_only` on the path. `resolve_composition` is the only function that drives composition recursion, and it owns the only `_resolution_stack`. Recursive composition (FR-018) is handled by `resolve_composition` calling itself on the parsed-but-not-resolved source with the **same** stack.
- **Rationale**: This is the load-bearing decision for cycle detection. If the source loader itself invoked `resolve_composition` (transitively through `load_framework_config`), each recursive load would start a **fresh** `_resolution_stack` and cycles would infinite-loop instead of raising. By making the source loader resolution-free and putting all recursion under one stack, FR-012 / FR-018 / SC-005 hold in code, not just in design intent. The existing `load_framework_config` becomes a thin wrapper: parse + template-validate via `_parse_framework_only`, then conditionally call `resolve_composition` exactly once at the top level (idempotence per I3.3 makes this safe).
- **Alternatives considered**:
  - **Original draft: `source_loader` = `load_framework_by_name`**: rejected (this was the F-1 defect from the analyze pass) — `load_framework_by_name` calls `load_framework_config`, which re-enters `resolve_composition` with an empty stack. Cycles silently infinite-loop. The fix is precisely to break this cycle of call-chains.
  - **Thread-local resolution stack**: rejected — would make resolution non-reentrant in surprising ways (e.g., test parallelism, future async loaders). Explicit per-call stack threading is simpler.
  - **Read the source's TOML file directly without pydantic validation**: rejected — would bypass template-path validation and schema-evolution checks. `_parse_framework_only` reuses the existing parse + template-validate pipeline; the ONLY thing it skips is the composition step.
  - **Walk `darnit.core.discovery.discover_implementations()` and call `impl.get_all_controls()`**: rejected — that returns `ControlSpec` objects (a presentation type), not `ControlConfig` (the schema type with full pass/remediation data needed to merge into the composite's framework config).

## R-003 — Diamond resolution & memoization

- **Decision**: `resolve_composition` accepts an optional `_source_cache: dict[str, FrameworkConfig]` and an `_resolution_stack: list[str]`. Each `[[compose]]` source is loaded at most once per top-level resolution; the cache key is the source slug. If the same slug appears in two different paths through the graph (e.g., composite A includes B and C; both B and C include leaf X), X is loaded once.
- **Rationale**: Without memoization, the diamond case re-parses TOML files unnecessarily. SC-002 (≤200 ms for 50 + 5 controls) is achievable either way, but memoization makes the resolver linear in the unique-source count instead of polynomial in graph paths.
- **Alternatives considered**:
  - **Global module-level cache**: rejected — would persist across resolutions and require explicit invalidation in tests. The discovery cache is already module-level; adding another would compound the test-cleanup burden.
  - **No memoization**: acceptable for v1's scale but not future-proof. Single-loop memoization is ~10 lines of code; the cost/benefit doesn't favor skipping it.

## R-004 — Cycle detection algorithm

- **Decision**: Use a per-resolution `_resolution_stack: list[str]` (ordered, allows reproducing the cycle chain in the error message). Before resolving a source, check `source_slug in _resolution_stack` — if so, raise `CompositionCycleError(chain=_resolution_stack + [source_slug])`. Push before recursing, pop after. Self-cycle (A includes A) is handled by the same check.
- **Rationale**: Depth-first walk with an explicit stack is the textbook approach. Using a `list` rather than a `set` lets the error message render `"A → B → C → A"` (the chain order matters for debuggability).
- **Alternatives considered**:
  - **Bounded depth limit (e.g., max depth 5)**: rejected per the clarify session's Q2 answer — depth limits add cognitive overhead without proportional safety. Cycle detection is sufficient.
  - **Topological sort up front**: rejected — requires materializing the full graph before any resolution, which complicates the loader's single-pass model. Depth-first detection is strictly cheaper.

## R-005 — Version-constraint enforcement

- **Decision**: Use `packaging.specifiers.SpecifierSet` (stdlib-adjacent — already a transitive dep through setuptools/build tooling). When a `[[compose]]` block carries `version_constraint = "<spec>"`, parse it into a `SpecifierSet` and check the loaded source's `FrameworkConfig.metadata.version` field against it via `Version(version_str) in specifier_set`. On mismatch, raise `CompositionVersionMismatchError` naming the constraint, the source slug, and the actual installed version.
- **Rationale**: PEP 440 is the Python ecosystem standard. Re-using `packaging` keeps semantics identical to pip/uv constraint checks the composite author already understands. No new comparator code to test.
- **Alternatives considered**:
  - **Hand-rolled comparator**: rejected — re-implementing PEP 440 is a footgun (pre-release handling, local versions, etc.).
  - **SemVer-only**: rejected — Python frameworks don't always follow SemVer, and OpenSSF Baseline's `spec_version` is calendar-based ("OSPS v2025.10.10"). PEP 440 absorbs both conventions cleanly.

## R-006 — Provenance stamping

- **Decision**: During resolution, every control pulled in via a `[[compose]]` block has two keys stamped into its `tags` dict before being inserted into the composite's `FrameworkConfig.controls`:
  - `tags["_composed_from"] = "<source-slug>"` — the immediate source the composite named in its `[[compose]]` block.
  - `tags["_original_control_id"] = "<id>"` — the control's ID as defined upstream (identical to its key in v1, but recorded explicitly so future rename support doesn't break provenance).
  - For recursive composition: if the source is itself a composite, the resolver overwrites these tags with the *ultimate non-composite* source's slug and original ID (i.e., what the source's already-resolved control already carries). This satisfies FR-018's "provenance traces to the ultimate source — C, not B" requirement.
- **Rationale**: `ControlConfig.tags` and `ControlSpec.tags` already exist as the standard sidecar-metadata channel and already propagate through `__post_init__` in `ControlSpec`. Audit results already serialize tags. Reusing this channel means zero schema changes downstream.
- **Alternatives considered**:
  - **New top-level `provenance: Provenance` field on `ControlConfig`**: rejected — would require schema migration and a corresponding `ControlSpec` field, plus changes to every serializer and audit-result formatter. Tags route is non-invasive.
  - **Compose the source-of-record into the control ID itself (e.g., `openssf-baseline::OSPS-AC-01.01`)**: rejected — would break every existing audit consumer that filters by control ID.

The underscore prefix on `_composed_from` / `_original_control_id` follows Python's "internal" convention and signals to UI code that these are framework-stamped rather than author-defined tags.

## R-007 — Override merge mechanics

- **Decision**: Overrides are applied AFTER all `[[compose]]` blocks have contributed their controls AND after strict-conflict detection has run. For each `[overrides."ID"]` block:
  1. If `ID` is not present in the resolved set → raise `CompositionOrphanOverrideError(orphan_id=ID)` (FR-007).
  2. For each field named under the override, validate against the underlying `ControlConfig`'s schema. Unknown fields → raise `CompositionUnknownFieldError(field=...)` (FR-008).
  3. The override fields shallow-replace the corresponding fields on the resolved control. Specifically: the `passes` list is replaced wholesale if present (consistent with FR-006's "wholesale replacement only"); scalar fields (`remediation`, `security_severity`, `description`, `docs_url`) replace directly; `tags` dict-merges (override keys win; framework-stamped provenance keys are NOT erased even if the override redefines `tags` — provenance is non-overridable). Override field names match the real `ControlConfig` schema exactly; aliases like `severity` / `help_url` are NOT supported.
- **Rationale**: Two-pass resolution (compose → conflict-detect → override) keeps the override semantics simple to reason about: "an override always wins over whatever the compose phase produced." Out-of-order application would force complex precedence chains. Provenance non-overridability prevents an override from disguising the origin of an inherited control.
- **Alternatives considered**:
  - **Deep-merge inside `passes`**: rejected per FR-006 — "partial pass-block edits are out of scope for v1."
  - **Validate override field names against pydantic introspection of `ControlConfig` rather than a hand-maintained allowlist**: chosen — pydantic's `model_fields` is the authoritative schema; an allowlist would drift. Implementation uses `ControlConfig.model_fields.keys()` (Pydantic v2 API).

## R-008 — Strict-conflict detection mechanics

- **Decision**: Track each control ID's provenance as compose blocks are applied in order. When a `[[compose]]` block tries to write to an ID that's already been written by a prior compose block (in the same composite, after filters), check:
  - Is `allow_conflicts = true` on the composite? → emit INFO log, last-wins (later compose block's contribution overwrites). FR-010.
  - Is there an `[overrides."ID"]` block targeting this ID? → no error; the override phase will resolve it. FR-011.
  - Otherwise → raise `CompositionConflictError(control_id=ID, sources=[earlier_source, later_source])` with both source slugs and the conflicting ID.
- **Rationale**: Checking against the overrides table during compose-block iteration is what makes the override-resolves-conflict pathway work without false positives in strict mode. The INFO log under `allow_conflicts` provides the audit-trail breadcrumb required by SC-006 and FR-010.
- **Alternatives considered**:
  - **Detect conflicts only after all compose blocks have been applied (one final pass)**: rejected — would lose the "earlier source" identity needed for the error message. Per-block tracking is one extra dict.
  - **Treat overrides as making conflicts always-allowed globally**: rejected — overrides are per-control; an override for `ID-A` should not silently permit a separate conflict on `ID-B`.

## R-009 — Inclusion-filter semantics

- **Decision**: Per FR-003, multiple inclusion expressions within a single `[[compose]]` block are evaluated as an **intersection**:
  - If `include_all = true`, start with the source's full control set.
  - Else if `include_levels` is present, start with controls whose level ∈ `include_levels`.
  - Then if `include_controls` is present, intersect: only keep controls whose ID ∈ `include_controls`.
  - Then if `include_tags` is present, intersect: only keep controls whose tags satisfy ALL named tag-value pairs.
  - Finally, `exclude_controls` removes its named IDs from whatever set is left.
- **Rationale**: Intersection-semantics for inclusion is the principle of least surprise — adding a second selector narrows the result, never broadens it. "Union of selectors" would create surprising behavior (e.g., `include_levels = [1]` + `include_controls = ["L3-CTRL"]` would silently pull a level-3 control, which the level filter implied was excluded).
- **Alternatives considered**:
  - **Union of selectors**: rejected for the reason above; documented here as an explicit "this is NOT how it works."
  - **First-match wins**: rejected — order-dependent semantics for what is conceptually a set operation.
- **Empty-result behavior**: if filters narrow to zero controls, the `[[compose]]` block contributes nothing. This is NOT an error (a composite might legitimately layer optional sources). Emit a DEBUG log noting the empty contribution.

## R-010 — Test-fixture strategy

- **Decision**: Use minimal hand-authored TOML fixtures under `tests/darnit/fixtures/composite/` rather than dynamically constructing `FrameworkConfig` objects in code. Each scenario gets one fixture. The resolver's unit tests load each fixture through `load_framework_config(...)` (the real production loader) and assert on the resolved `FrameworkConfig.controls` dict (or on the raised exception).
- **Rationale**:
  - Tests through the loader (not the resolver in isolation) catch schema-binding bugs as well as resolution bugs.
  - Hand-authored TOML matches the actual composite-author experience and acts as documentation for the contract.
  - Fixtures double as concrete examples in `quickstart.md`.
- **Alternatives considered**:
  - **Programmatic `FrameworkConfig` construction in test code**: rejected — bypasses the schema layer, which is half the surface area being tested.
  - **Single mega-fixture with toggles**: rejected — couples scenarios that should fail independently.

## R-011 — Error class taxonomy

- **Decision**: Define one base exception `CompositionError(Exception)` in `darnit.core.composition`, with concrete subclasses:
  - `CompositionMissingSourceError` (FR-004)
  - `CompositionConflictError` (FR-009)
  - `CompositionOrphanOverrideError` (FR-007)
  - `CompositionUnknownFieldError` (FR-008)
  - `CompositionCycleError` (FR-012)
  - `CompositionVersionMismatchError` (FR-013)
- **Rationale**: Distinct subclasses let `merger.load_framework_config` callers catch composition errors discriminantly, and let CLI / MCP-tool surfaces translate each into a specific exit code or user-facing message. Single base class lets generic error-handling catch all composition issues uniformly.
- **Alternatives considered**:
  - **Single `CompositionError` with a `kind` field**: rejected — Python exception hierarchies are the idiomatic discriminator; the `isinstance` check is what consumers will write.
  - **Reuse existing `ValueError`**: rejected — composition errors are recoverable in callers' view (e.g., a CLI can suggest the specific fix from the error type); homogenizing into `ValueError` loses that signal.

---

## Summary of unresolved items going into Phase 1

None. All Technical Context fields have concrete values; no `NEEDS CLARIFICATION` markers remain. Phase 1 (data-model.md, contracts/, quickstart.md) can proceed.
