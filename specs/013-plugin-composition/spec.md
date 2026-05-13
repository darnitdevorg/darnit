# Feature Specification: Composition of compliance implementations

**Feature Branch**: `013-plugin-composition`
**Created**: 2026-05-13
**Status**: Draft
**Input**: User description: "Design composition of compliance implementations per #233 — let a plugin assemble its controls from parts of other implementations (e.g., 'include OpenSSF Baseline L1+L2, plus SLSA L3, plus three named OSPS L3 controls, plus my own'), without inheritance."

## Context

Today, every darnit compliance implementation is a self-contained plugin (`darnit-baseline`, `darnit-gittuf`, `darnit-example`, the worked-example `darnit-hello`). Each lives at the same conceptual level: a registered implementation under the `darnit.implementations` entry point, with its own framework name, its own TOML config, and its own controls. A user audits one implementation at a time (`darnit audit --implementation openssf-baseline`).

Real organizations don't think in terms of one implementation. A typical org-policy looks like: "we follow OpenSSF Baseline through level 2, take SLSA up to level 3, AND require three specific level-3 OSPS controls, AND have these six internal controls." Today there is no way to express that without forking and rewriting an entire implementation.

This feature defines **composition** — a way for an implementation to declare which controls it wants from other implementations, in TOML, without writing Python or forking source. The framework resolves the composition at registration time and produces a single flat list of controls that the existing audit pipeline already knows how to handle. No changes to the sieve, the audit tool, or the remediation pipeline are required.

## Clarifications

### Session 2026-05-13

- Q: When two `[[compose]]` blocks contribute a control with the same ID, should the framework fail the registration by default (strict) or silently last-wins by file order? → A: **Strict by default.** Any control-ID conflict between `[[compose]]` blocks fails registration with a clear error naming both sources. The composite author opts out explicitly via `allow_conflicts = true` (which falls back to last-wins by TOML file order) OR resolves the conflict with an explicit `[overrides."ID"]` block (which always wins over any compose-block contribution). Reason: predictability is load-bearing for compliance frameworks; silent precedence is exactly the footgun that breaks under refactoring. Aligns with the Constitution's "Conservative-by-Default" principle (already cited in the spec).
- Q: Should v1 support recursive composition (composites composing other composites), or restrict sources to non-composite "leaf" implementations? → A: **Allow recursive composition in v1.** The resolution algorithm is the same regardless of source type — we're composing fully-resolved control sets, not configuration text. Cycle detection (FR-012) is the load-bearing guardrail; depth limits add complexity without proportional safety. A new FR-018 explicitly admits composite sources; Story 4 gains a positive acceptance scenario covering a non-cyclic 3-level chain.

The design follows two principles from the project constitution:

- **Composition over inheritance** (issue #233's original framing). An implementation enumerates the specific controls it pulls from other sources, not a parent it derives from. This keeps the relationship explicit and surfaces upstream changes as additive choices rather than silently-inherited behavior.
- **TOML-first**. Composition is expressed entirely in the implementation's TOML config. Python is the escape hatch, not the surface.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Organization assembles its own compliance baseline from existing ones (Priority: P1)

A security architect at a software vendor wants to encode their organization's compliance posture as a single darnit implementation that downstream teams can audit against with one command. The posture isn't novel — it's a curated mix: the entire OpenSSF Baseline at levels 1 and 2, the SLSA controls up to level 3, plus three specific OSPS level-3 controls the security team has decided are critical now, plus four internal controls about deploy windows and rotation.

Today, the architect has to either ship a long internal runbook telling teams "run these three darnit commands and intersect the results manually" — which never happens — or fork OpenSSF Baseline, copy controls into the fork, and maintain a divergent codebase.

After this change, the architect creates a single `acme-baseline` implementation. Its TOML config declares the composition: which levels and named controls to pull from each source implementation, plus the four internal controls inline. The implementation registers via the existing `darnit.implementations` entry point and behaves like any built-in implementation to downstream teams: `darnit audit --implementation acme-baseline` produces one flat audit result.

**Why this priority**: This is the core user value. Every other story in this feature is in service of making this scenario work cleanly. An architect who gets this one flow working has already extracted most of the feature's value.

**Independent Test**: Author a minimal composite implementation (`acme-baseline`) that pulls 3 controls from `darnit-baseline` and adds 1 control of its own in TOML. Install it alongside `darnit-baseline`. Running `darnit list-controls --implementation acme-baseline` lists exactly 4 controls (3 from baseline + 1 local). Running `darnit audit --implementation acme-baseline` produces a single audit result covering all 4. No Python composition code is required in the composite's `implementation.py` beyond the standard `ComplianceImplementation` protocol stubs.

**Acceptance Scenarios**:

1. **Given** a composite implementation `acme-baseline` whose TOML declares `compose` blocks pulling controls from `openssf-baseline` and `darnit-gittuf` plus its own inline controls, **When** the framework resolves the composition at registration time, **Then** `acme-baseline.get_all_controls()` returns one flat list containing every requested upstream control and every local control, with each control's pass logic intact and its identifying source recorded as metadata.
2. **Given** the same composite, **When** `darnit audit --implementation acme-baseline` runs against a sample repository, **Then** the audit produces a single result set in the same shape as a non-composite audit. Each result is labelled with its original control ID so reviewers can trace it back to the source.
3. **Given** a composite that pulls `openssf-baseline` levels 1 and 2 (not 3), **When** an audit runs, **Then** only level-1 and level-2 controls from `openssf-baseline` execute. Level-3 OSPS controls do not appear in the result set unless they were explicitly named under a separate `compose` block.
4. **Given** a composite that names specific controls (e.g., `include_controls = ["OSPS-AC-01.01", "OSPS-VM-03.01"]`), **When** the composite resolves, **Then** exactly those controls — and no others from that source — are in scope.

---

### User Story 2 — Override a single inherited control without forking the source (Priority: P2)

The architect from Story 1 reviews `OSPS-AC-01.01` (an access-control check) and realises Acme's internal remediation procedure differs from the upstream remediation darnit-baseline ships. The control's pass logic is fine; the remediation steps need to point at Acme's internal SSO console rather than the upstream "click here in GitHub settings" instructions.

Today there's no way to do this without forking `darnit-baseline`. With this feature, the architect adds an `[overrides."OSPS-AC-01.01"]` block in their composite's TOML that replaces only the remediation, leaving the pass logic and metadata intact.

**Why this priority**: Without overrides, organizations would either accept that some inherited control behaves wrong for their environment, or be forced to fork. The override mechanism is what keeps composition genuinely additive rather than a half-solution.

**Independent Test**: Add an `[overrides."OSPS-AC-01.01"]` block to a composite implementation that replaces the control's `remediation` field. Run an audit and `darnit list-controls --implementation acme-baseline --show OSPS-AC-01.01`. The pass logic must match the upstream `openssf-baseline` version exactly; the remediation must match the override.

**Acceptance Scenarios**:

1. **Given** a composite that inherits `OSPS-AC-01.01` from `openssf-baseline` and overrides its `remediation` field, **When** the composite resolves, **Then** the merged control has the upstream pass logic and the override's remediation. The metadata (description, severity, help URL) defaults to upstream unless explicitly overridden.
2. **Given** the same composite, **When** the upstream `openssf-baseline` releases a new version that changes the pass logic of `OSPS-AC-01.01`, **Then** the composite picks up the new pass logic on next install. The override only governs the fields it explicitly names.
3. **Given** a composite that overrides a field the upstream control doesn't have (e.g., a non-existent `severity_override`), **When** the composite resolves, **Then** the framework reports a clear error at registration time naming the unknown field. (Don't silently store unused overrides.)

---

### User Story 3 — Conflicting controls across composed sources resolve predictably (Priority: P2)

A composite implementation includes both `openssf-baseline` and a vendor framework. Both define a control with ID `OSPS-AC-01.01` but the vendor framework has different pass logic (a deeper check). The architect needs to know which one wins, and the answer needs to be predictable, documented, and not silent.

**Why this priority**: Without a defined conflict-resolution rule, composing two real-world implementations becomes a guessing game. The cost of an unclear rule is silent behavioral drift between dev/prod or between teams.

**Independent Test**: Author a composite that pulls `OSPS-AC-01.01` from two sources with intentionally different pass logic. Resolve the composition. The framework MUST refuse registration with a clear conflict-error by default, naming both sources and the conflicting control ID. Adding `allow_conflicts = true` (or an explicit `[overrides."OSPS-AC-01.01"]` block) MUST make registration succeed.

**Acceptance Scenarios**:

1. **Given** a composite where two `compose` blocks both contribute a control with the same ID, **When** the composite resolves, **Then** the framework refuses registration with a clear error naming both sources, the conflicting control ID, and the two opt-out mechanisms (`allow_conflicts = true` or an explicit `[overrides."ID"]` block).
2. **Given** the same composite, **When** the architect adds `allow_conflicts = true` at the composition root, **Then** registration succeeds: the LATER `[[compose]]` block (in TOML file order) wins, and the framework emits a non-fatal INFO log line naming both sources and the winning one.
3. **Given** a composite with an explicit `[overrides."OSPS-AC-01.01"]` block in addition to the conflicting `compose` sources, **When** the composite resolves, **Then** the override wins regardless of whether `allow_conflicts` is set. Explicit overrides are a per-control acknowledgement of the conflict, so even strict mode treats them as resolved.

---

### User Story 4 — Composition cycles are detected and rejected (Priority: P3)

Composite A composes from composite B which (deliberately or accidentally) composes from A. Today this is impossible because we don't have composition at all. After this feature, cycles become a real failure mode worth handling explicitly.

**Why this priority**: Cycles produce infinite loops at registration time, which would either crash the framework or hang it. A clear error message is significantly better than either. P3 because in practice this only happens with deliberate misuse or unusual cross-org plugin ecosystems; most teams will hit conflicts (Story 3) far more often than cycles.

**Independent Test**: Author two composites that reference each other. Install both. The framework rejects registration of either composite with a clear cycle error naming the chain.

**Acceptance Scenarios**:

1. **Given** composite A includes composite B, and composite B includes composite A, **When** either is loaded via the framework's plugin-discovery mechanism, **Then** the framework refuses to register either implementation and emits a clear error naming the cycle (`A → B → A`).
2. **Given** a longer cycle (A → B → C → A), **When** any of A/B/C is loaded, **Then** the cycle is detected at the first composite to attempt resolution; the error names the full chain.
3. **Given** a self-cycle (A includes A), **When** loaded, **Then** the framework rejects A with a clear "self-reference" error.
4. **Given** a non-cyclic three-level chain (composite A sources from composite B, which sources from non-composite C), **When** A is registered, **Then** registration succeeds and `A.get_all_controls()` returns the resolved set produced by walking the chain end-to-end. Provenance metadata (per FR-015) MUST identify each control's ultimate source — C, not B — so auditors trace results to the originating implementation, not the intermediate composite.

---

### User Story 5 — Version pinning makes composites reproducible (Priority: P3)

The architect ships `acme-baseline 1.0.0` referencing `openssf-baseline`. Six months later, `openssf-baseline 2.0.0` is released with breaking changes to some control IDs. Without version pinning, every audit of `acme-baseline 1.0.0` against the new `openssf-baseline` silently produces different results. With version pinning, the composite either continues to behave as it did or fails loudly with a version-mismatch error.

**Why this priority**: For most users, the default behavior matters more than this knob. Most composites will track HEAD of their sources by default. But for orgs running compliance against regulators (SOC 2, HIPAA, ISO 27001), reproducibility of last quarter's audit results is a real requirement. P3 because the default-floating behavior is fine for v1; explicit pinning is a knob to add for users who need it.

**Independent Test**: Pin a composite to a specific upstream version (`openssf-baseline >= 1.5,<2.0`). Install upstream `openssf-baseline 1.5.0`; composite resolves. Upgrade upstream to `2.0.0`; composite fails to register with a clear version-mismatch error naming the constraint and the installed version.

**Acceptance Scenarios**:

1. **Given** a composite that declares `version_constraint = ">=1.5,<2.0"` against an upstream source, **When** the installed upstream version is 1.5.0, **Then** the composite registers successfully and the resolved controls come from upstream 1.5.0.
2. **Given** the same composite, **When** the installed upstream version is 2.0.0, **Then** the composite refuses to register and emits an error message naming the constraint and the installed version.
3. **Given** a composite without an explicit `version_constraint`, **When** any version of the upstream is installed, **Then** the composite resolves with that version. Default-floating behavior is preserved for the no-pin case.

---

### Edge Cases

- **Empty composition**: a composite that declares no `compose` blocks and no inline controls. Should it register? Probably yes (it's a valid-but-empty implementation), with `get_all_controls()` returning `[]`. Auditing it should produce an empty result set, not error.
- **Composition of a non-composite that doesn't exist on the host**: a composite references `slsa-implementation` which isn't installed. The composite must fail to register with a clear "required source not installed" error, naming the missing source. (Per Constitution Principle II: Conservative-by-Default — never silently skip.)
- **Recursive composition (composites composing composites)**: supported in v1 per FR-018. The resolution algorithm is the same depth-first walk regardless of source type; cycle detection (FR-012) is the load-bearing guardrail. Provenance traces to the originating non-composite source, not the intermediate composite.
- **Override that names a control NOT pulled in by any `compose` block**: e.g., `[overrides."FOO-99.99"]` but no `compose` block includes `FOO-99.99`. Should this error? Yes — silent acceptance of dead overrides is a footgun. The framework rejects at registration time naming the orphan override.
- **Include filter exclusion**: a composite that says `include_levels = [1, 2]` AND `exclude_controls = ["OSPS-AC-02.01"]`. Both constraints apply: the result is "everything at levels 1+2 EXCEPT OSPS-AC-02.01". Composition primitives must support both inclusion and exclusion expressions.
- **Source upstream's own composition**: if a composed source is itself a composite, what does "the source's controls" mean? The fully-resolved set, not the source's own `compose` blocks. (We're composing *effective behavior*, not *configuration text*.)
- **Same control included via two different paths** (A → B includes X; A also directly includes X via C): the resolver must surface this as a single included control (deduplicate), with the resolution order applying the standard last-wins/strict rules from Story 3.
- **MCP tool ownership of inherited controls**: each inherited control's `audit_*` MCP tool — does the composite re-expose it under its own name, or does the upstream's name remain? For v1: the composite's `audit_<composite_name>` tool covers ALL controls in the composite; upstream tools remain exposed at their own names. Two ways to audit; not a conflict.

## Requirements *(mandatory)*

### Functional Requirements

#### TOML composition primitives

- **FR-001**: A composite implementation MUST declare its composition entirely in TOML under a dedicated `[[compose]]` table-array (one entry per source-implementation pulled from). No new Python API is required for the common case; the composite's Python `ComplianceImplementation` class may be the same stub-style class used by the `darnit-hello` example.
- **FR-002**: Each `[[compose]]` block MUST identify its source by the same slug the framework already uses (`name` field of the source implementation, e.g., `"openssf-baseline"`).
- **FR-003**: Each `[[compose]]` block MUST support at least the following inclusion expressions, evaluated as the intersection of all expressions present in that block:
  - `include_all = true` — pull every control from the source.
  - `include_levels = [N, ...]` — pull controls whose level matches one of the named integers.
  - `include_controls = ["ID", ...]` — pull controls by exact ID.
  - `include_tags = { tag = "value", ... }` — pull controls matching the named tag/value pair (uses the existing `ControlSpec.tags` filter).
  - `exclude_controls = ["ID", ...]` — drop these specific IDs from the otherwise-included set.
- **FR-004**: The framework MUST refuse to register a composite that requires a source implementation not installed on the host. The error MUST name the missing source slug.
- **FR-005**: Inline controls (defined directly under `[controls."..."]` in the composite's TOML, the same way non-composite implementations define their controls today) MUST coexist with `[[compose]]` blocks in the same TOML file. The effective control set is the union of all composed sources plus all inline controls.

#### Override primitives

- **FR-006**: A composite MAY declare `[overrides."CONTROL-ID"]` blocks that override specific fields of inherited controls. Override-able fields include at minimum: `remediation`, `security_severity`, `description`, `docs_url`, and metadata keys under `tags`. (Field names match the underlying control-config schema exactly; the framework's TOML-First principle means override authors type the schema's real field names, not user-friendly aliases.) The pass logic (the sieve `passes` array) MAY be overridden in v1 only if the composite replaces the entire `passes` array — partial pass-block edits are out of scope.
- **FR-007**: The framework MUST reject an override that references a control ID NOT present in the composite's resolved set (no orphan overrides). The error MUST name the orphan ID.
- **FR-008**: The framework MUST reject an override that names a field NOT present on the underlying control's data model (no unknown-field overrides). The error MUST name the unknown field.

#### Conflict resolution

- **FR-009**: When two `[[compose]]` blocks contribute a control with the same ID, the framework MUST refuse registration by default. The error MUST name both contributing sources, the conflicting control ID, and the two ways the composite author can resolve the conflict explicitly (add `allow_conflicts = true` at the composition root, OR add an explicit `[overrides."CONTROL-ID"]` block).
- **FR-010**: A composite MAY declare `allow_conflicts = true` at the composition root to opt out of strict-mode and fall back to last-wins behavior — the LATER `[[compose]]` block (by TOML file order) wins. When this opt-out is active, the framework MUST still emit an INFO-level log line at resolution time naming both contributing sources and the winning one.
- **FR-011**: Explicit `[overrides."..."]` blocks have the highest precedence — they always win over any `[[compose]]`-block contribution, regardless of whether `allow_conflicts` is set. An explicit override is a per-control acknowledgement of the conflict, so even strict mode treats it as resolved. When an override targets a control ID that two or more `[[compose]]` blocks would contribute (in any mode — strict OR `allow_conflicts = true`), the override's fields layer onto the **earliest** compose block's contribution (by TOML file order); later compose blocks for that ID are skipped entirely. If the author needs a later compose block's contribution as the base, they MUST replicate the relevant fields inside the override block.

#### Cycle detection

- **FR-012**: The framework MUST detect composition cycles (composite A composes composite B which composes A, including self-cycles and longer chains) at registration time and refuse to register any implementation in the cycle. The error MUST name the full cycle chain.

#### Version pinning

- **FR-013**: A `[[compose]]` block MAY include `version_constraint = "<PEP 440 specifier>"` (e.g., `">=1.5,<2.0"`). If present, the framework MUST verify the installed source's `version` property satisfies the constraint at registration time. A mismatch MUST refuse registration with a clear error naming the constraint and the installed version.
- **FR-014**: If `version_constraint` is absent, the composite MUST register against whatever version of the source is installed (default-floating).

#### Provenance

- **FR-015**: Each control in the resolved set MUST carry metadata identifying the composite's slug AND the original source (composite slug + source slug + original control ID). Audit results inherit this metadata so reviewers can trace any result back to its source implementation.

#### Audit pipeline compatibility

- **FR-016**: Composite implementations MUST work with the existing audit, remediate, and list-controls MCP tools without modification to those tools' interfaces. The resolved control set is the single contract; nothing downstream of resolution needs to know whether the controls came from composition.
- **FR-017**: The framework's existing `--implementation <slug>` CLI flag MUST work against composite slugs the same way it works against non-composite slugs.

#### Recursive composition

- **FR-018**: A composite MAY source from another composite. When a `[[compose]]` block references a source that is itself a composite, the framework MUST fetch the source's FULLY RESOLVED control set (not its raw `[[compose]]` configuration) and apply the composite's inclusion/exclusion filters against that resolved set. Depth is bounded only by FR-012's cycle detection.

### Key Entities

- **Composite implementation**: A darnit implementation whose controls are at least partially assembled from other implementations. Identified by its own slug; registers via the standard `darnit.implementations` entry point.
- **Compose block**: One `[[compose]]` entry in a composite's TOML config. Names a source implementation and the inclusion/exclusion filters that select controls from it.
- **Override block**: One `[overrides."CONTROL-ID"]` entry. Replaces specific fields of an inherited control without forking it.
- **Resolution**: The framework's process of walking a composite's TOML at registration time, fetching each source's controls, applying inclusion/exclusion filters and overrides, detecting conflicts and cycles, and producing a flat list of controls the rest of the framework consumes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An organization can express their compliance posture (parts of OpenSSF Baseline + parts of SLSA + their own controls) as a single composite implementation, in TOML alone, in under 30 minutes for someone familiar with darnit. (Today: impossible without forking.)
- **SC-002**: A composite implementation that pulls 50 controls from upstream sources and adds 5 of its own resolves in under 200 ms at registration time on a developer laptop. (Performance: composition is upstream of every audit, must not be a noticeable cost.)
- **SC-003**: Every audit result from a composite carries traceable provenance — a reviewer can identify the original source implementation and original control ID for any reported result in 100% of cases.
- **SC-004**: A composite that references a non-installed source fails to register with a clear error in 100% of cases. No silent skip, no half-resolved composite.
- **SC-005**: A composite with a cycle (any length, including self) fails to register with a clear error naming the cycle chain in 100% of cases. No infinite loop, no stack overflow.
- **SC-006**: A composite with conflicting control IDs across sources fails registration in 100% of default-mode cases, and resolves predictably (by TOML file order) in 100% of `allow_conflicts = true` cases. Verified by a test fixture covering both modes plus the `[overrides."..."]` escape hatch.
- **SC-007**: A composite override that names an orphan control ID OR an unknown field fails to register with a clear error in 100% of cases. No silent acceptance.
- **SC-008**: All existing implementations (`darnit-baseline`, `darnit-gittuf`, `darnit-example`, `darnit-hello`) continue to work without modification. The composition feature is purely additive at the framework level; no existing TOML config is invalidated.

## Assumptions

- **Resolution happens at registration time, not at audit time.** The composite's `register()` does the full walk; downstream audit code sees only the resolved flat list. This matches today's pattern where `register()` is called once per process, not per audit.
- **Source slugs are stable identifiers.** A composite that references `"openssf-baseline"` continues to work across versions of the source as long as the source keeps its slug. If a source ever renames itself, the framework reports the mismatch as "source not installed" per FR-004 — that's the desired failure mode (loud, explicit).
- **Composition is intra-host.** A composite can only reference source implementations installed on the same host (via the same `darnit.implementations` entry-point group). Cross-host composition (fetching a source over the network, etc.) is out of scope.
- **Composites are themselves discoverable.** A composite registers via the existing `darnit.implementations` entry point exactly like a non-composite. The framework decides whether to do composition resolution by inspecting the TOML at registration time, not by a separate entry-point group.
- **TOML is the source of truth for composition.** All composition primitives are TOML-expressible. Python override hooks are NOT part of v1 — if a composite needs custom resolution logic, the composite author should subclass `ComplianceImplementation` directly and forget composition altogether, OR file a follow-up to extend the TOML primitives.
- **Conflict-resolution defaults to strict (registration error), not last-wins.** Last-wins is the conventional TOML/dict-merge behavior, but compliance frameworks live or die by predictability — silent precedence is exactly what breaks under refactoring. The composite author opts out explicitly with `allow_conflicts = true` (fall back to last-wins) or with a per-control `[overrides."..."]` block (the override always wins). This aligns with the Constitution's "Conservative-by-Default" principle.
- **Versioning of the composite itself is independent of source versioning.** `acme-baseline 1.0.0` may pin `openssf-baseline >=1.5,<2.0`. Bumping `acme-baseline` to 1.0.1 does not require any change to the upstream pin. This is the standard Python-packaging dependency model.
- **The Constitution's TOML-First principle is not violated.** Composition is a new TOML schema feature; new control sources (composed-in controls) all originate from TOML (the source implementation's TOML). No Python-defined control becomes the source of truth via composition.

## Out of Scope

- **Composition through a non-darnit registry / remote URL / git ref.** Composites pull from locally-installed implementations only. Network composition (fetch from GitHub release, fetch from URL, fetch from a darnit registry) is a follow-up.
- **Composition of pass logic.** The sieve `passes` array can be wholesale-replaced by an override, but partial edits ("override the third pass only", "add a new pass between existing passes") are out of scope for v1. Wholesale replacement is the only override mode supported.
- **Composition of remediation handlers in Python.** Inline remediation steps in TOML can be overridden per FR-006; Python-registered remediation handlers cannot be inherited or overridden through composition in v1. (They are referenced by name in TOML, so as long as the named handler is registered, it works — but composing a handler from one source into another is out of scope.)
- **Cross-implementation tag namespace coordination.** If `darnit-baseline` uses `severity` ranged 1–10 and another source uses `severity` ranged A–E, composition won't reconcile them. Authors of composite implementations must ensure their sources use compatible conventions. The framework reports the values it finds; it doesn't normalize across sources.
- **Hot-reload of composites without restart.** Composition resolution happens once at process registration. Editing a composite's TOML at runtime requires restarting the host process. Live-reload is a separate feature with its own design questions.
- **Composition-aware UI.** Today's MCP tools and CLI list controls by ID. There's no special "composed from <source>" UI affordance in v1. The provenance metadata is exposed in audit-result objects (FR-015), but rendering it in user-facing output is a separate UX task.
- **GUI / wizard for authoring composites.** Composites are authored in TOML files by hand or via simple templates. A guided composition wizard or web UI is not part of this feature.
- **Override of a control's identity (renaming an ID, splitting one control into two).** Overrides modify fields of an existing control identified by its source ID. Renaming, splitting, or merging are out of scope.
- **Cross-composite composition (composite A composes parts of composite B's compose blocks).** A composite imports a source's *effective* controls, not its TOML configuration. If composite B includes some controls and composite A wants the same subset, A composes from B directly (which works per the recursive case in edge cases) — not from B's source list.
