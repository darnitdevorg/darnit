# Implementation Plan: Remove openspec, Migrate Work to Speckit

**Branch**: `016-openspec-migration` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/016-openspec-migration/spec.md`

## Summary

Remove the top-level `openspec/` directory and every reference to it elsewhere in the repository. Preserve the value that's worth keeping: the 26 architectural specs rehome to `docs/architecture/` as static reference documentation; the one in-flight proposal (`changes/org-wide-audit-pipeline/`) migrates to a new speckit feature directory; the openspec-independent validation checks in `validate_sync.py` are retained (with their data source rewired to the new location). Everything else -- the 12 archived proposals, `generate_docs.py`, `docs/generated/`, the openspec-tied pre-commit hook, openspec checkboxes in the PR template -- is removed.

The constitution itself is amended (`MINOR` bump 1.1.0 -> 1.2.0) to (a) point at the new authoritative location for the framework-design spec, and (b) update the Development Workflow gate list (drop "generated docs", scope-narrow "spec sync").

Single PR. Large diff but mechanically straightforward: most of the work is `git mv` plus targeted edits to ~13 files outside the openspec tree.

## Technical Context

**Language/Version**: Python 3.11+ (for the `validate_sync.py` trim and the `scanner.py` one-line edit) and Markdown / YAML for everything else. No new languages introduced.

**Primary Dependencies**: None new. The trimmed `validate_sync.py` continues to use stdlib (`tomllib`) plus the existing `darnit.config.framework_schema` import path.

**Storage**: Filesystem only. `git mv` preserves history; deletions are visible in `git log`.

**Testing**: The existing pytest suite (`uv run pytest tests/ --ignore=tests/integration/ -q`) must continue to pass. The trimmed `validate_sync.py` must exit zero on a clean checkout post-rewiring. No new test files are introduced -- this is a refactor of the repository tree, not new functionality.

**Target Platform**: Same as the rest of darnit -- Linux/macOS developer workstations + GitHub Actions CI.

**Project Type**: In-place repository refactor. No new package introduced; no existing package's structure changes.

**Performance Goals**: N/A. One-shot migration.

**Constraints**:
- Single PR delivery (per FR-014 / SC-007). No phased intermediate state.
- No backward-compatibility shim (no `openspec -> docs/architecture` symlink or redirect).
- All Development Workflow gates from the post-removal constitution must exit zero on a clean checkout (per FR-008 / SC-003).
- `git log` history under `openspec/` paths is preserved by performing renames via `git mv` rather than delete-then-create for the rehomed content.

**Scale/Scope**:
- 189 files removed (the entire `openspec/` tree).
- 26 architectural spec files rehomed to `docs/architecture/` (via `git mv` from openspec/specs/).
- 4 active-proposal files migrated to `specs/017-org-wide-audit-pipeline/`.
- ~13 reference files updated outside the openspec tree (ARCHITECTURE.md, CLAUDE.md, 3 docs/getting-started/ files, docs/IMPLEMENTATION_GUIDE.md, packaging/README.md, .pre-commit-config.yaml, .github/pull_request_template.md, scanner.py, validate_sync.py, the constitution itself).
- 1 script deleted (`generate_docs.py`).
- 1 generated-docs directory cleaned up (`docs/generated/`, if present).
- 1 new top-level file created (`CHANGELOG.md`) with the migration entry.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

This feature both **complies with** the existing constitution's principles AND **amends** the constitution itself. Both halves need explicit treatment.

### Principle-level compliance (no violations)

| Principle | Status | Note |
|---|---|---|
| I. Plugin Separation | OK | The `scanner.py` change (removing `"openspec"` from `_PRUNE_DIRS`) is internal to `darnit-baseline` and doesn't introduce or break any cross-package import |
| II. Conservative-by-Default | N/A | No audit semantics change; PASS/FAIL/WARN computation is untouched |
| III. TOML-First Architecture | N/A | No controls or TOML config touched |
| IV. Never Guess User Values | N/A | No auto-detection or context inference changes |
| V. Sieve Pipeline Integrity | N/A | No handler phases, handler results, or CEL expressions touched |

### Constitutional amendment (explicit)

This feature modifies the constitution itself, in three places:

1. **Spec-Implementation Synchronization section**: the authoritative spec path moves from `openspec/specs/framework-design/spec.md` to `docs/architecture/framework-design.md` (per FR-005).
2. **Development Workflow section**: the "Generated docs" gate (item 4) is removed; the "Spec sync" gate (item 3) is retained but its scope is narrowed (per FR-006 / FR-007 / FR-008).
3. **TOML-First Architecture section context**: the closing sentence ("`rules/catalog.py` ... remains for backward compatibility") is unchanged but the surrounding context referring to the spec path is updated.

Per the constitution's Governance section, amendments require: (a) description + rationale, (b) version bump, (c) validation that dependent templates and docs remain consistent.

**Recommended bump**: `MINOR` (1.1.0 -> 1.2.0). Rationale: the change is materially expanded/changed guidance (Workflow gate list and authoritative spec path), not a Core Principle removal or incompatible redefinition. The five Core Principles are unchanged in substance.

**Gate result**: PASS with amendment. The amendment is in-scope for this feature (it's how the feature can be coherent) and follows the documented Governance procedure.

## Project Structure

### Documentation (this feature)

```text
specs/016-openspec-migration/
+-- plan.md              # This file
+-- spec.md              # Feature specification (with 2026-06-20 Clarifications)
+-- research.md          # Phase 0 output (rehoming naming, version bump, etc.)
+-- data-model.md        # Phase 1 output (file-level deliverable schemas)
+-- quickstart.md        # Phase 1 output (step-by-step migration guide)
+-- checklists/
|   +-- requirements.md  # Spec quality checklist
+-- tasks.md             # Phase 2 output (NOT created by /speckit-plan)
```

No `contracts/` directory is created. The feature exposes no APIs, command schemas, or external interfaces -- it's a tree refactor.

### Repository changes

Added:

```text
/  (repository root)
+-- docs/architecture/                          # NEW directory, 26 rehomed specs (incl. framework-design.md)
|   +-- framework-design.md                      # NEW (renamed from openspec/specs/framework-design/spec.md)
|   +-- audit-pipeline.md                        # NEW (renamed)
|   +-- audit-context-collection.md              # NEW (renamed)
|   +-- ...                                      # 23 more, see data-model.md
|   +-- README.md                                # NEW (one-screen index pointing into the 26 files)
+-- specs/017-org-wide-audit-pipeline/          # NEW migrated speckit feature
|   +-- spec.md                                  # renamed from openspec/changes/.../proposal.md
|   +-- plan.md                                  # renamed from openspec/changes/.../design.md
|   +-- tasks.md                                 # renamed from openspec/changes/.../tasks.md
+-- CHANGELOG.md                                 # NEW (entry describing this removal)
```

Modified:

```text
ARCHITECTURE.md                                  # drop openspec/ from tree diagram + table
CLAUDE.md                                        # rewrite 5 references (scripts + spec path)
docs/IMPLEMENTATION_GUIDE.md                     # rewrite 2 references
docs/getting-started/troubleshooting.md          # rewrite 2 references
docs/getting-started/development-workflow.md     # rewrite 1 reference
docs/getting-started/framework-development.md    # rewrite 2 references
packaging/README.md                              # update 2 lines (script paths)
.pre-commit-config.yaml                          # narrow the validate_sync hook's files: pattern
.github/pull_request_template.md                 # update framework-spec checkbox path
packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py
                                                 # remove "openspec" from _PRUNE_DIRS set
scripts/validate_sync.py                         # trim: drop validate_spec_exists and validate_docs_freshness;
                                                 # rewire validate_pass_types_sync to read docs/architecture/framework-design.md
.specify/memory/constitution.md                  # amend: version 1.1.0 -> 1.2.0, update Workflow gates,
                                                 # update authoritative spec path
```

Removed:

```text
openspec/                                        # entire directory: config.yaml, specs/, changes/
scripts/generate_docs.py                         # full delete
docs/generated/                                  # full delete (if present; orphaned output of generate_docs.py)
```

**Structure Decision**: Rehomed architectural specs land flat under `docs/architecture/` as `<topic>.md` (not preserving the `<topic>/spec.md` directory shape). Rationale in research.md (D2). The migrated active proposal lands at `specs/017-org-wide-audit-pipeline/` using speckit's `spec.md` / `plan.md` / `tasks.md` filenames (not openspec's `proposal.md` / `design.md` / `tasks.md`); content is preserved 1:1 with the file rename applied at `git mv` time.

## Complexity Tracking

The constitutional amendment is the only "structural" deviation. It's not a violation of any Principle -- it's the constitution's own documented amendment procedure being invoked, exactly as the Governance section anticipates. No complexity-tracking table entry is required.
