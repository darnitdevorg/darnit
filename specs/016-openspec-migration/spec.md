# Feature Specification: Remove openspec, Migrate Work to Speckit

**Feature Branch**: `016-openspec-migration`

**Created**: 2026-06-20

**Status**: Draft

**Input**: User description: "I want to migrate any openspec work to speckit or otherwise remove openspec from the repo"

## Clarifications

### Session 2026-06-20

- Q: What happens to `scripts/validate_sync.py` and `scripts/generate_docs.py`? -> A: Hybrid. `generate_docs.py` is removed entirely (it generates human docs from openspec sources; no speckit equivalent needed). `validate_sync.py` is trimmed to drop the two openspec-dependent checks (Spec Exists, Docs Freshness) but retains the three openspec-independent checks that catch real bugs (TOML Schema valid, Pass Types Sync / handler-name registry, SARIF Source). The constitution's "spec sync" Workflow gate stays (with reduced scope); the "generated docs" Workflow gate drops.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One spec system, not two (Priority: P1)

A new contributor opens the repository and wants to understand how specs and proposals are tracked. Today they find two parallel systems: `openspec/` (dormant for new work but referenced by tooling, scripts, CI, and the constitution) and `specs/NNN-feature-name/` (the speckit-driven system used by every recent feature). They have to read both, figure out which is authoritative, and watch out for stale references in CLAUDE.md, ARCHITECTURE.md, and the constitution.

After this feature, only one system remains. The contributor reads about speckit in CLAUDE.md, finds the active features under `specs/`, and never encounters an openspec reference except as a historical note in git log.

**Why this priority**: This is the entire purpose of the feature. Without it nothing else matters.

**Independent Test**: A fresh `grep -rln openspec` against the tracked tree (excluding `.git/`) returns zero matches. A new contributor can navigate the spec system end-to-end without ever opening anything under `openspec/`.

**Acceptance Scenarios**:

1. **Given** a fresh clone of the post-removal tree, **When** a contributor runs `grep -rln openspec` excluding `.git/`, **Then** the result is empty.
2. **Given** the post-removal CLAUDE.md, constitution, ARCHITECTURE.md, and docs/getting-started/, **When** a contributor reads them end-to-end, **Then** the only spec system referenced is speckit.
3. **Given** the post-removal `.pre-commit-config.yaml`, **When** a contributor runs `pre-commit run --all-files`, **Then** no hook fails due to a missing openspec command or directory.

---

### User Story 2 - In-flight proposal preserved (Priority: P1)

The `openspec/changes/org-wide-audit-pipeline/` directory contains proposal/design/tasks documents for a real in-progress change. Removing openspec without preserving this work would lose it. After this feature, the same content is reachable through a normal speckit feature directory and can be picked up by `/speckit-plan` etc.

**Why this priority**: This is the one piece of openspec content that's not dormant -- it represents work the project still intends to do. Losing it would be a regression.

**Independent Test**: The migrated content is present under `specs/` with no information loss relative to the openspec original; a maintainer can resume the proposal using normal speckit commands.

**Acceptance Scenarios**:

1. **Given** the post-removal tree, **When** a maintainer looks for the org-wide audit pipeline proposal, **Then** they find it under `specs/NNN-org-wide-audit-pipeline/` with the proposal, design, and task content preserved.
2. **Given** the migrated feature directory, **When** a maintainer runs `/speckit-plan` against it, **Then** speckit accepts it as a normal feature and produces a plan against the existing spec.

---

### User Story 3 - Constitutional reference still resolves (Priority: P1)

The project constitution (`.specify/memory/constitution.md`) names `openspec/specs/framework-design/spec.md` as "the authoritative specification" the framework design is governed by. The Development Workflow gates explicitly require `uv run python scripts/validate_sync.py --verbose` to pass against that spec. Removing openspec without updating these references would leave the constitution citing a path that doesn't exist.

After this feature, the constitution either points at a new authoritative location for the framework-design content, or explicitly removes the gate -- with no dangling references.

**Why this priority**: The constitution is load-bearing -- code review, the Development Workflow gates, and contributor onboarding all depend on it making sense. A stale path in the constitution is a contradiction, not a typo.

**Independent Test**: Read the post-removal constitution top to bottom; every spec path it names resolves to a real file; every workflow gate it lists can be run successfully.

**Acceptance Scenarios**:

1. **Given** the post-removal constitution, **When** a contributor follows every file path it cites, **Then** each path resolves to a file that exists in the current tree.
2. **Given** the post-removal Development Workflow section, **When** a contributor runs every listed command in order, **Then** each command exits zero on a clean checkout.

---

### User Story 4 - Architectural specs rehomed, not lost (Priority: P2)

Beyond the active proposal, openspec also contains 26 architectural / protocol specs under `openspec/specs/` (handler pipeline, CEL expressions, sieve handler authoring, framework design, etc.). These describe how the system works rather than tracking in-flight change -- they are reference documentation, not change proposals. They should remain findable as reference documentation rather than disappearing into git history.

**Why this priority**: P2 rather than P1 because the content is not load-bearing in the same way as the active proposal or the constitutional reference -- a developer can usually answer the same questions by reading the code. But losing 26 documents of architectural intent is a real cost, and re-homing them is cheap.

**Independent Test**: A contributor looking for architectural reference material finds it in a single discoverable location, with each former openspec topic still present.

**Acceptance Scenarios**:

1. **Given** the post-removal tree, **When** a contributor wants to read about (for example) the sieve handler pipeline or CEL expressions, **Then** they find the relevant document in a dedicated documentation directory (not under `specs/`, since these are not in-flight features).
2. **Given** the rehomed directory, **When** a contributor inventories its contents, **Then** every former openspec `specs/<topic>/spec.md` has a corresponding successor (renamed and possibly lightly edited, but content preserved).

---

### Edge Cases

- **Archived openspec proposals** (`openspec/changes/archive/*`, 12 dated entries from 2026-02-07 through 2026-02-18): these are completed changes; the underlying code work has shipped. The proposals describe *what was done* rather than *what to do*, so their value is purely historical. Default treatment: dropped from the working tree; `git log` is the archive. If any of these proposals contain decision rationale not captured elsewhere, the content can be summarized into the rehomed architectural docs (US4) at migration time.
- **Code reference to openspec** (`packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py`): the scanner has at least one string reference to openspec. This MUST be removed (or rewritten to reference a non-openspec source) as part of the cleanup; runtime code referring to a deleted directory is a bug.
- **`scripts/validate_sync.py`** and **`scripts/generate_docs.py`** are openspec-specific. Either remove entirely (and adjust the constitution's Development Workflow accordingly) or rewrite to operate on speckit / TOML sources. The simpler reading is: remove. Spec drift in speckit features is caught by ordinary tests and code review, not by a dedicated sync script.
- **`.pre-commit-config.yaml`** likely runs an openspec validation hook. That hook is removed alongside everything else; no replacement is added in this feature.
- **`.github/pull_request_template.md`** has openspec-related checkboxes (already visible in community PRs like #137 and #138 with the "Framework Changes Checklist" referring to `openspec/specs/framework-design/spec.md`). These are rewritten to reference the new framework-design location, or removed if the checklist no longer applies.
- **Downstream forks**: any external integrator that references `openspec/specs/...` paths will break. This is acknowledged in the change's CHANGELOG / release notes; no in-repo backward-compatibility shim is provided.
- **Search hits in commit history**: `git log` will continue to reference openspec. That's correct and expected -- history is immutable, only the working tree is being cleaned.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `openspec/` directory (including `config.yaml`, `specs/`, and `changes/`) MUST be removed from the working tree. Final state: no top-level `openspec/` directory exists.
- **FR-002**: All in-tree references to openspec across configuration, source code, documentation, CI workflows, pre-commit hooks, and PR templates MUST be removed or rewritten to reference the new locations introduced by this feature. After completion, `grep -rln "openspec" .` (excluding `.git/`, ignored directories, and CHANGELOG/release-notes entries that explicitly describe this removal) MUST return zero matches.
- **FR-003**: The active in-flight proposal currently at `openspec/changes/org-wide-audit-pipeline/` MUST be migrated to a speckit feature directory at `specs/<NNN>-org-wide-audit-pipeline/`, preserving the proposal, design, and tasks content. The migrated feature MUST be usable by speckit commands (`/speckit-plan`, `/speckit-tasks`, etc.) without further structural change.
- **FR-004**: The 26 architectural specs under `openspec/specs/*` MUST be rehomed to a documentation directory (default: `docs/architecture/`) as static reference documentation. They MUST NOT be placed under `specs/` (which is reserved for in-flight speckit features). For each former openspec spec, a corresponding successor document MUST exist; content can be lightly edited for the new context but must not be lossy.
- **FR-005**: The constitutional reference to `openspec/specs/framework-design/spec.md` in `.specify/memory/constitution.md` MUST be updated to point at the new location (per FR-004) -- the spec content remains the framework-design authority, only the path changes.
- **FR-006**: The `scripts/validate_sync.py` script MUST be retained and trimmed. The two openspec-dependent checks (Spec Exists, Docs Freshness) MUST be removed. The three openspec-independent checks (TOML Schema valid, Pass Types Sync / handler-name registry consistency, SARIF Source from TOML) MUST be retained and continue to exit non-zero on failure. The script's docstring, CLI help, and any references to `openspec/` paths MUST be updated to reflect the narrower scope. The constitution's "spec sync" Workflow gate MUST continue to invoke this script.
- **FR-007**: The `scripts/generate_docs.py` script MUST be removed entirely. The constitution's "generated docs" Workflow gate MUST be dropped. Any references to `docs/generated/` freshness (in CI workflows, CLAUDE.md, pre-commit hooks, etc.) MUST be removed along with the script.
- **FR-008**: After all changes land, the constitution's Development Workflow gates MUST be: lint (`ruff`), tests (`pytest`), spec sync (`validate_sync.py` -- per FR-006, scoped to the 3 surviving checks), and upstream rebase. The "generated docs" gate is removed (per FR-007). Every listed gate MUST be executable on a clean checkout and exit zero.
- **FR-009**: Archived proposals (`openspec/changes/archive/*`) MAY be dropped from the working tree without per-document migration; their historical value is preserved by `git log`. If decision rationale from any archived proposal is not captured in the current code or in the rehomed architectural docs, it MAY be summarized into the appropriate rehomed doc at migration time.
- **FR-010**: The code reference to openspec in `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py` MUST be removed or rewritten so the scanner does not depend on the openspec directory's presence at runtime.
- **FR-011**: Pre-commit hooks in `.pre-commit-config.yaml` that exercise openspec MUST be removed. No replacement speckit-specific hook is required by this feature.
- **FR-012**: The pull-request template (`.github/pull_request_template.md`) MUST be updated to remove openspec-specific checklists, or rewrite them to reference the new locations from FR-003 / FR-004 / FR-005.
- **FR-013**: A short note in the project's CHANGELOG (or release notes for the next release) MUST describe the removal, name the new location for the framework-design spec (per FR-005), and warn downstream integrators that any tooling referencing `openspec/...` paths will need to be updated.
- **FR-014**: The entire change MUST land in a single coherent pull request -- not phased over multiple PRs -- so that the repository is never in an intermediate state where some references point at openspec and others at the new locations. The PR may be large; that is acceptable.

### Key Entities

- **openspec directory**: The current top-level `openspec/` directory containing `config.yaml`, `specs/` (26 subdirs), and `changes/` (1 active + 12 archived). The unit being removed.
- **Active proposal**: `openspec/changes/org-wide-audit-pipeline/` -- the one in-flight change record that must be migrated, not dropped.
- **Architectural spec**: Any of the 26 `openspec/specs/<topic>/spec.md` files. Reference documentation describing how a part of the system works.
- **Framework-design spec**: The specific architectural spec at `openspec/specs/framework-design/spec.md` -- the one that is constitutional. Treated specially because the constitution and the Development Workflow both reference it by path.
- **Sync pipeline**: The pair of scripts (`validate_sync.py`, `generate_docs.py`) plus their pre-commit hook and PR-template checkboxes that enforce or describe openspec-to-implementation alignment.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the change lands, `find . -type d -name openspec -not -path "*/.git/*"` returns no results.
- **SC-002**: After the change lands, `grep -rln "openspec" . --exclude-dir=.git --exclude=CHANGELOG.md --exclude-dir=specs` returns no matches in the working tree (CHANGELOG.md and historical speckit feature dirs may legitimately reference the removal; everything else must be clean).
- **SC-003**: All Development Workflow gates listed in the post-removal constitution exit zero on a clean checkout: `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ -q`, and any sync/docs gates that survive the removal.
- **SC-004**: The migrated `specs/<NNN>-org-wide-audit-pipeline/` directory contains the proposal/design/tasks content from the original `openspec/changes/org-wide-audit-pipeline/`; a maintainer running `/speckit-plan` against it does not error.
- **SC-005**: The rehomed architectural documentation directory contains one document per former openspec spec (26 in total); no former openspec architectural spec has been silently dropped.
- **SC-006**: A new contributor reading CLAUDE.md, the constitution, and ARCHITECTURE.md sees exactly one spec system referenced (speckit), with no leftover instructions, paths, or commands that depend on openspec.
- **SC-007**: The pull request implementing this feature is a single PR; no follow-up PR is required to bring the repository to a consistent post-removal state.

## Assumptions

- **Active proposal scope**: `openspec/changes/org-wide-audit-pipeline/` is the only in-flight proposal worth migrating. All other entries under `openspec/changes/archive/` describe completed work and are dropped from the working tree.
- **Rehoming target**: Architectural specs land at `docs/architecture/` (default name). The exact directory name is a planning-phase decision but does not change spec scope.
- **Constitutional rewrite**: The constitution's "framework design is governed by ..." reference is updated to point at the new path. The substantive content (what the framework design IS) is unchanged; only the location moves.
- **Sync pipeline disposition** (resolved 2026-06-20 Clarifications): hybrid. `generate_docs.py` is removed entirely (no speckit equivalent needed). `validate_sync.py` is trimmed -- the two openspec-dependent checks (Spec Exists, Docs Freshness) are removed; the three openspec-independent checks (TOML Schema, Pass Types Sync, SARIF Source) are retained and continue to gate merges via the constitution's "spec sync" Workflow gate. This preserves the bug-catching value of the openspec-independent checks while removing all coupling to the openspec directory.
- **No backward-compatibility shim**: No symlinks, redirects, or "openspec -> docs/architecture" forwarders are introduced. Downstream tooling that depended on openspec paths is expected to update.
- **Archived proposals**: Dropped from the working tree. Their content is preserved by git history; no per-document migration of archived proposals is performed (FR-009 allows opportunistic summarization into rehomed docs but does not require it).
- **PR template**: Existing PR template checkboxes that mention openspec (e.g., "Updated framework spec (openspec/specs/framework-design/spec.md)") are rewritten to point at the new location, not removed entirely -- the underlying check (does the PR update the framework spec?) is still useful, only the path is stale.
- **Single PR**: The entire removal lands in one PR. There is no phased deprecation because the bifurcation is the problem -- a partial migration would extend the confusion rather than resolve it.
- **Out of scope**:
  - Designing a speckit-native spec-vs-implementation sync check (separate future feature if wanted).
  - Migrating non-darnit consumers of these specs (e.g., external dashboards) -- they are notified via CHANGELOG and update on their own.
  - Adding any new validation tooling. The Development Workflow becomes simpler, not differently complex.
  - Reorganizing the speckit `specs/NNN-feature-name/` tree (e.g., archiving old ones, renaming dirs).
- **Downstream signaling**: A single CHANGELOG entry plus a clear PR title and body are sufficient notification. No deprecation cycle, no transition period, no maintainer announcement beyond the PR is required.
