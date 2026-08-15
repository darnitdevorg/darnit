# Feature Specification: Sync `.project/` reader with current CNCF spec

**Feature Branch**: `030-dot-project-spec-sync`

**Created**: 2026-08-14

**Status**: Draft

**Input**: User description: "Resolve issue #372 - CNCF .project/ spec drift detected: reconcile dot_project.py and update tracked hash"

## Clarifications

### Session 2026-08-14

- Q: Scope of new-field exposure → A: Parse-only; expose additions in a follow-up feature.
- Q: Rename-alias compatibility window → A: One-release grace; warn on old name, remove next release.
- Q: `DOT_PROJECT_SPEC_VERSION` bump rule → A: Bump on every upstream drift the reconciliation processes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Restore CI green on new PRs (Priority: P1)

A maintainer opens or updates a pull request. The `Test` job runs to completion without a spurious failure caused by out-of-band evolution of the CNCF `.project/` specification. If the CNCF specification genuinely diverges from what darnit understands, the failure remains loud, but it disappears the moment darnit is reconciled with the current upstream.

**Why this priority**: PRs #370 and #371 already showed this exact failure blocking otherwise clean rebases, and the same failure will appear on every future PR until reconciled. This is the direct blocker cited in issue #372 and the reason the feature exists.

**Independent Test**: Run the darnit test suite against a fresh clone of `main` after the reconciliation lands. The `test_upstream_spec_unchanged` case reports PASS, and the overall `Test` job exits 0.

**Acceptance Scenarios**:

1. **Given** the CNCF upstream `types.go` at the hash captured by this feature, **When** the maintainer runs the darnit test suite, **Then** `test_upstream_spec_unchanged` passes without a `--update-hash` override.
2. **Given** the same CNCF upstream, **When** the maintainer runs a full audit of a real repository whose `.project/project.yaml` contains fields the upstream added, **Then** darnit reads the file without error, uses fields it recognizes, and ignores fields it does not.
3. **Given** a `.project/project.yaml` that omits a field which was renamed upstream, **When** darnit resolves project context, **Then** the read succeeds and every downstream control receives the same values it would have under the pre-drift spec version.

---

### User Story 2 - Loud detection of the next drift (Priority: P2)

The next time CNCF changes their `.project/` specification, a maintainer sees the failure as a *tracked-hash mismatch* against a captured baseline and knows exactly what to do next (review upstream, adjust `dot_project.py`, rerun `--update-hash`). The failure is not silently absorbed by an evergreen "current upstream" reference.

**Why this priority**: The upstream-tracking test only holds its warning value if it fails loudly on drift and is easy to reconcile. Reconciling with today's upstream must not weaken that guarantee. This story delivers value even if User Story 1 alone would have gotten CI green (a naive "just accept whatever upstream says right now" approach would break this property).

**Independent Test**: Modify the tracked hash file to a fabricated value and re-run the upstream-sync test. It fails with a diagnostic that names the mismatched hashes and points at the reconciliation runbook.

**Acceptance Scenarios**:

1. **Given** the tracked hash file after reconciliation, **When** a hypothetical future upstream change alters the CNCF `types.go`, **Then** `test_upstream_spec_unchanged` fails with a message identifying both hashes and instructing the maintainer to run the sync workflow.
2. **Given** the reconciled `dot_project.py`, **When** the maintainer inspects the file, **Then** the version identifier reflects the newly captured upstream state (not stale from before the drift).

---

### User Story 3 - Preserve real-world compatibility (Priority: P3)

Every real-world `.project/project.yaml` that darnit successfully audits *today* continues to be audited without regression after the reconciliation. No field that darnit relied on for control decisions silently disappears; no consumer of the `.project/` reader sees a new required argument.

**Why this priority**: The reconciliation is a maintenance task, not a redesign. Producing a version of `dot_project.py` that reads upstream cleanly but breaks existing repositories is worse than not reconciling at all. This story is P3 because Users 1 and 2 already imply most of the guardrails; it is called out separately so a "just take upstream verbatim" approach is disqualified as an implementation.

**Independent Test**: Run the darnit audit against a corpus of real `.project/project.yaml` files (or synthetic fixtures covering the fields darnit reads) before and after the change. Every field observed pre-change is still observed post-change with the same value; no repository transitions from PASS to FAIL/WARN for a control that depends on `.project/`.

**Acceptance Scenarios**:

1. **Given** a `.project/project.yaml` covering every field darnit reads today, **When** the reader parses it under the reconciled `dot_project.py`, **Then** every field is available to the same downstream consumers with the same semantics.
2. **Given** the same file, **When** the audit runs against a real repository, **Then** no control that consumed a `.project/` field before the reconciliation flips status because of the reconciliation itself (unrelated status flips from other causes are out of scope).

---

### Edge Cases

- **Upstream added a purely additive field**: the reader MUST ignore it (per the 2026-08-14 clarification: parse-only, no exposure); no downstream consumer receives it until a separate feature exposes it. The tracked hash still updates so future drift is loud.
- **Upstream renamed a field the reader consumes**: the reader MUST accept the new name AND, for exactly one release, continue accepting the old name while emitting a deprecation warning naming both the old field and the release in which the alias will be removed. The alias is removed in the release immediately following the one that lands the reconciliation (clarified 2026-08-14).
- **Upstream removed a field the reader consumes**: the reader must survive the file being valid under the new spec (field absent) and the file being valid under the old spec (field present, ignored). Downstream consumers relying on that field either accept absence gracefully or the reconciliation notes explicitly flag the follow-up.
- **Upstream restructured a field's shape (scalar to list, string to object)**: the reader must handle both shapes; the reconciled spec version identifier reflects the newer shape.
- **CI runs offline / cannot fetch the CNCF `types.go`**: the upstream-sync test skips gracefully rather than fails; the tracked hash file remains the source of truth for comparison so the test's *offline* pass condition matches its *online* pass condition when nothing has drifted.
- **Multiple CNCF changes queue up during review**: the feature reconciles against a single point-in-time snapshot; a subsequent CNCF change on the same day produces a second, separate loud failure that a future reconciliation resolves. The feature does not commit to "chase upstream continuously."

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `dot_project.py` MUST parse the CNCF `.project/` specification at the version captured by this feature without raising exceptions for any field the specification declares.
- **FR-002**: The reader MUST tolerate fields present in a real `.project/project.yaml` that are not declared in the captured specification (forward compatibility for the next minor upstream change).
- **FR-003**: The reader MUST expose every field that a darnit control or the harness's answer-source chain reads from `.project/project.yaml` today, with the same field name and semantics as it exposed before the reconciliation.
- **FR-004**: `DOT_PROJECT_SPEC_VERSION` and `DOT_PROJECT_SPEC_URL` (or the equivalents in `dot_project.py`) MUST accurately identify the captured upstream state. The version identifier MUST be bumped by this feature and by every subsequent reconciliation that updates the tracked-hash file, regardless of how large or small the underlying upstream change is (clarified 2026-08-14). One-to-one mapping: every distinct tracked-hash value corresponds to exactly one version identifier.
- **FR-005**: The tracked-hash file MUST contain the hash of the exact upstream `types.go` used to derive the reconciled reader. That file is the sole reference the `test_upstream_spec_unchanged` test compares against.
- **FR-006**: `test_upstream_spec_unchanged` MUST pass on a clean checkout of the feature branch without invoking any `--update-hash` override.
- **FR-007**: When network access to the CNCF repository is unavailable, `test_upstream_spec_unchanged` MUST skip cleanly and MUST NOT report the drift as a hard failure.
- **FR-008**: The reconciliation MUST NOT introduce a new required argument on any public function or class in `dot_project.py` that existing internal callers pass without modification.
- **FR-009**: The reconciliation MUST document, in a maintenance note carried alongside the source, (a) the diff summary between the pre-reconciliation and post-reconciliation upstream states, and (b) any field the reader still ignores (with the rationale for ignoring it).
- **FR-010**: If a field the reader consumes today is renamed or removed upstream, the reader MUST continue accepting the old-name form for the release that lands this reconciliation AND emit a deprecation warning each time the old name is encountered. The warning MUST name the old field, the new field (or "removed with no replacement"), and the release in which the alias will be removed. The alias MUST be removed in the release immediately following the one that lands this reconciliation; no historical rename accumulates more than one release of compat baggage.

### Key Entities *(include if feature involves data)*

- **CNCF `.project/` specification (`types.go`)**: the upstream Go source-of-truth that defines the shape of `.project/project.yaml`. Not code darnit executes; darnit reads its structure and mirrors the field set.
- **`dot_project.py` reader**: the darnit-side module that parses `.project/project.yaml` into typed dataclasses. Every control that consumes project context reaches values through this reader.
- **Tracked-hash file** (`.github/dot-project-spec-hash.txt`): a one-line file storing the SHA-256 of the exact upstream `types.go` blob the reader was reconciled against. The upstream-sync test compares this against the currently fetched upstream.
- **Version identifier** (`DOT_PROJECT_SPEC_VERSION`): a semantic-version-style label that a maintainer can grep to answer "which upstream state does darnit think it is on?" without decoding hashes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a clean checkout of the reconciled branch, the workspace test suite exits 0 in a single run (no `--update-hash`, no marker overrides, no manual retries).
- **SC-002**: Every darnit control that reads a `.project/`-sourced field pre-reconciliation still receives the same value post-reconciliation for a fixture covering every field the reader exposes (verified in a new fixture test if one does not already exist).
- **SC-003**: The reconciliation lands as a single self-contained pull request; downstream branches do not need to consume it selectively.
- **SC-004**: The next unrelated PR opened after this one merges shows `test_upstream_spec_unchanged` as PASS (not skipped, not xfail) without any per-PR intervention.
- **SC-005**: If a maintainer, six months later, needs to reconcile the next drift, the on-disk reconciliation notes plus the runbook the test's failure message points at are sufficient to complete the work without re-deriving the process from scratch.

## Assumptions

- The CNCF `types.go` at the drift-detection date (2026-08-13) represents a real, stable upstream state and not an in-progress work-in-progress commit that will be reverted. The reconciliation captures whatever is on `main` at reconciliation time; if that changes again immediately, that is a new drift for a future feature.
- Every darnit control that reads `.project/project.yaml` today does so through `dot_project.py`; there is no parallel reader that could bypass the reconciliation.
- The upstream-sync test remains the sole automated drift detector. Adding a nightly cron or repo-owner notification is out of scope; the test's on-PR failure is the intended signal.
- Reconciliation is strictly parse-only for newly added upstream fields (clarified 2026-08-14). The reader accepts every field the current upstream declares so parsing does not fail, but does NOT extend the dataclass surface to expose new fields to controls, the harness, or any other downstream consumer. Wiring a specific new field through to a control is a separate feature scoped and tracked on its own.
- No existing consumer of `dot_project.py` reads private attributes (dataclass internals) directly; reshaping a dataclass to match a renamed upstream field is safe as long as the public field name stays or a documented alias covers the old name.
- The maintenance note (FR-009) lives inside `dot_project.py` (module docstring or an adjacent NOTES markdown) rather than a dedicated external document. Long-term docs consolidation is out of scope for this feature.
