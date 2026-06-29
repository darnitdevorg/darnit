# Phase 0 Research: openspec Removal

**Feature**: 016-openspec-migration | **Date**: 2026-06-21

This phase records the design decisions that were either deferred from the spec ("planning-phase decision but does not change spec scope" -- FR-004) or surfaced during the constitution-check reconnaissance. Each decision is captured as: decision, rationale, alternatives considered.

## D1 -- Constitution version bump level

- **Decision**: `MINOR` bump, 1.1.0 -> 1.2.0.
- **Rationale**: The change modifies guidance (Development Workflow gate list, authoritative spec path) but does not remove or incompatibly redefine any of the five Core Principles. The constitution's own versioning rules say `MAJOR` is reserved for "Principle removal or incompatible redefinition" and `MINOR` for "New principle or materially expanded guidance" -- this is materially changed guidance within the existing scope. `PATCH` would be too small: removing a Workflow gate is more than a wording refinement.
- **Alternatives considered**:
  - `PATCH` (1.1.1): rejected -- dropping a Workflow gate is a substantive change, not a wording polish.
  - `MAJOR` (2.0.0): rejected -- the five Core Principles are unchanged; readers familiar with v1.1.0 don't need to re-learn the framework, only the gate list.

## D2 -- Rehoming naming convention for architectural specs

- **Decision**: Flatten `openspec/specs/<topic>/spec.md` -> `docs/architecture/<topic>.md`. Drop the per-topic subdirectory; rename the file from `spec.md` to `<topic>.md`.
- **Rationale**: The per-topic-directory pattern was an openspec-specific convention -- each topic-dir could hold the spec plus auxiliary openspec metadata. In the rehome, there's no auxiliary metadata; the topic-dir would be a single-file directory, which is wasteful. Flat `<topic>.md` files are also easier to skim with `ls` and easier to cross-link with normal Markdown references. The original directory shape is recoverable from `git log` if anyone needs it.
- **Alternatives considered**:
  - Preserve `docs/architecture/<topic>/spec.md` shape: rejected -- needless nesting, no second file expected in any topic.
  - `docs/architecture/<topic>/README.md`: rejected -- "README" implies an overview of a code package; these are reference docs, not package READMEs.
- **Renaming exception**: For framework-design specifically, the rehomed file is `docs/architecture/framework-design.md` (matching the directory name from the original). All references in the constitution, PR template, scripts, and downstream docs use this canonical path.

## D3 -- Source of truth for `validate_pass_types_sync` post-rehome

- **Decision**: After rehoming, `validate_sync.py`'s `validate_pass_types_sync` function reads from `docs/architecture/framework-design.md` instead of `openspec/specs/framework-design/spec.md`. The check itself (compare handler names declared in the spec's Markdown tables against handler names registered in `darnit.core.handlers` / `darnit.sieve.handler_registry`) is unchanged in semantics.
- **Rationale**: The content of `framework-design/spec.md` is preserved at the new path by D2; the check just needs its `SPEC_PATH` constant updated to point there. The check itself catches real bugs (handler names declared in docs but never registered, or vice versa) that are not openspec-specific.
- **Alternatives considered**:
  - Drop the check entirely: rejected -- the check has caught real drift in the past (per the constitution's own commit history). Throwing it out alongside openspec would be opportunistic, not principled.
  - Replace the file-based check with an introspection check (compare handler registry against an enum / hardcoded list): rejected -- requires designing a new contract and is out of scope. Wire the existing check to the new path; if a maintainer later wants a fancier introspection approach, that's a follow-on.
  - Read from a separate manifest file (e.g., `packages/darnit/handler_names.txt`): rejected -- creates a new artifact the doc and code both have to stay in sync with; doesn't reduce drift surface.

## D4 -- Disposition of `docs/generated/`

- **Decision**: Delete `docs/generated/` entirely as part of this feature. Removed from the working tree alongside `generate_docs.py`.
- **Rationale**: `docs/generated/` is the output directory of `generate_docs.py`. With the script removed, the directory becomes a stale snapshot that nothing maintains -- a documentation footgun where readers think the content is current but no process updates it. The constitution's Development Workflow currently has a "Generated docs must stay fresh" rule that is satisfied by deletion (no generated docs means no freshness gate).
- **Pre-check**: confirm directory contents at implementation time. If the directory contains hand-written content mixed in with generated output (unlikely but worth verifying), surface it during `/speckit-tasks` rather than silently dropping.
- **Alternatives considered**:
  - Keep `docs/generated/` as a frozen snapshot: rejected -- a frozen snapshot of historical generated docs has no readership and rot starts immediately.
  - Convert the generated docs to hand-written reference docs under `docs/architecture/`: rejected -- duplicates information that's already in code + the rehomed framework-design.md.

## D5 -- File mapping for the active proposal

- **Decision**: Migrate `openspec/changes/org-wide-audit-pipeline/` to `specs/017-org-wide-audit-pipeline/` with the following file renames:
  - `proposal.md` -> `spec.md`
  - `design.md` -> `plan.md`
  - `tasks.md` -> `tasks.md` (no rename)
  - `.openspec.yaml` -> dropped (openspec-specific metadata; no speckit equivalent)
- **Rationale**: The openspec proposal/design/tasks naming maps cleanly onto speckit's spec/plan/tasks naming. Speckit downstream commands (`/speckit-plan`, `/speckit-tasks`, `/speckit-clarify`) all expect these specific filenames. Renaming at `git mv` time preserves history and makes the feature immediately usable in speckit workflows without further restructuring.
- **Content adjustments at migration time**:
  - Add the speckit spec header (`# Feature Specification: ...`, `**Feature Branch**:`, `**Created**:`, `**Status**: Migrated from openspec`, `**Input**:`) at the top of the new `spec.md`.
  - The body content of `proposal.md` becomes the User Scenarios / Requirements / Success Criteria sections, lightly restructured if needed to fit the speckit spec template's headings.
  - The `design.md` content moves verbatim into `plan.md`'s Technical Context / Project Structure sections, or as a single "Original openspec design" section if restructuring is too invasive for this PR.
  - `tasks.md` content moves verbatim; no header adjustment needed since speckit and openspec both use `tasks.md` as a flat task list.
- **Alternatives considered**:
  - Preserve openspec filenames (`proposal.md`, `design.md`): rejected -- speckit commands wouldn't find them; downstream readers expect the speckit convention.
  - Treat the migration as a "new feature in the speckit format, rewriting from scratch": rejected -- loses the existing proposal/design analysis that's the point of preserving the work.

## D6 -- CHANGELOG creation vs release notes

- **Decision**: Create a new top-level `CHANGELOG.md` file as part of this feature. The migration entry is the first entry. Future releases append entries to the same file.
- **Rationale**: FR-013 allows either "the project's CHANGELOG" or "release notes for the next release." The project does not currently have a CHANGELOG. A standalone CHANGELOG.md (Keep-a-Changelog style) is easier to discover than digging through GitHub Releases, easier to read against `git log`, and is the de-facto open-source convention. Creating it now seeds the convention.
- **Format**: Keep-a-Changelog 1.1.0 conventions (`Unreleased` section at top, dated sections below; categories: Added, Changed, Removed, Deprecated, Fixed, Security).
- **Initial entry**: Single `## [Unreleased]` section with this feature's changes (under Changed: rehome architectural specs; Removed: openspec directory, generate_docs.py, docs/generated/; Added: docs/architecture/, CHANGELOG.md). The downstream-integrator notice (per FR-013) goes inline in the entry as a callout block.
- **Alternatives considered**:
  - Only put the notice in the eventual GitHub Release for the next release: rejected -- the next release may be months out; an integrator browsing main won't find it.
  - Put the notice in a one-shot `MIGRATING_FROM_OPENSPEC.md` file at the root: rejected -- creates a perpetual artifact that's mostly empty after the integration window closes.

## D7 -- Pre-commit hook narrowing vs deletion

- **Decision**: Narrow the validate_sync hook in `.pre-commit-config.yaml` rather than delete it. The hook's `files:` pattern changes from `^(packages/darnit/|openspec/specs/framework-design/)` to `^(packages/darnit/|docs/architecture/framework-design\.md)`. The hook itself continues to run `validate_sync.py --changed-files`.
- **Rationale**: The validate_sync check survives (per FR-006); only its scope narrows. Keeping the pre-commit hook makes CI faster (only re-runs validate_sync when the relevant files change) and keeps the same developer ergonomics. Deleting the hook would force the check to run on every commit.
- **Alternatives considered**:
  - Delete the hook, let CI catch sync failures only on push: rejected -- slower feedback loop.
  - Narrow the `files:` pattern to `^docs/architecture/framework-design\.md` only (drop the `packages/darnit/` half): rejected -- handler-name drift can also be introduced by changes in `packages/darnit/`, so both directories are still relevant.

## D8 -- Order of operations within the single PR

- **Decision**: Within the single PR, perform the changes in this order so that intermediate commits each leave the tree in a buildable state (defensive against partial-merge / bisect scenarios):
  1. Rehome content (`git mv openspec/specs/<topic>/spec.md docs/architecture/<topic>.md`) -- preserves history, intermediate state has both old and new paths until step 3.
  2. Migrate active proposal (`git mv openspec/changes/org-wide-audit-pipeline/proposal.md specs/017-org-wide-audit-pipeline/spec.md`, etc.).
  3. Delete the openspec/ directory + `generate_docs.py` + `docs/generated/`.
  4. Rewire `validate_sync.py` (update `SPEC_PATH`; delete `validate_spec_exists` and `validate_docs_freshness` functions and their call sites).
  5. Update reference files (CLAUDE.md, ARCHITECTURE.md, docs/, pre-commit-config, PR template, scanner.py).
  6. Amend the constitution (path + workflow gates + version bump).
  7. Create CHANGELOG.md.
  8. Run all Workflow gates locally; fix any breakage.
- **Rationale**: Performing the renames first (steps 1-2) means git records them as renames, preserving `git log <new path>` history. Doing them after deletion would cost the history.
- **Alternatives considered**:
  - Delete openspec/ first, then create the new docs from scratch: rejected -- loses git history on every rehomed file.
  - Squash everything into a single commit before merge: acceptable on merge (the project uses squash-merge), but the staging commits during development should respect the order above.

## Open items deferred to `/speckit-tasks`

None. All planning-phase decisions are resolved. The /speckit-tasks phase handles the per-file work breakdown.
