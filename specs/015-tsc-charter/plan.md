# Implementation Plan: Technical Steering Committee Charter

**Branch**: `015-tsc-charter` | **Date**: 2026-06-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/015-tsc-charter/spec.md`

## Summary

Author a Technical Steering Committee (TSC) charter and roster for the darnit project, modeled on gittuf's single-tier governance pattern (and adopting the LF Projects Technical Charter section structure shared by both gittuf and GUAC). The deliverable is **documentation only** -- Markdown files at the repository root. No runtime code is added.

The work product is three files: `CHARTER.md` (the governance document), `TECHNICAL-STEERING-COMMITTEE.md` (the machine-friendly roster), and a small `GOVERNANCE.md` index linking both from a single discoverable entry point. The initial roster lists Michael Lieberman (Kusari, industry, @mlieberman85) and Justin Cappos (New York University, academia, @JustinCappos).

Vote recording follows gittuf's pattern (clarified in spec session 2026-06-17): GitHub PR approvals on the affected file are the canonical record for file-bound decisions; GitHub Issue/Discussion threads with explicit `+1`/`-1`/`+0` comments cover decisions without a file artifact. Removal-for-cause uses majority of *other* TSC members; inactivity is discretionary (no fixed numeric threshold).

## Technical Context

**Language/Version**: Markdown (CommonMark, GitHub-flavored). No source code.

**Primary Dependencies**: None at build/runtime. Authoring relies only on text editors and the GitHub web UI for PR review.

**Storage**: Git repository (`kusari-oss/darnit` main repo). No database, no external store. Roster history is recoverable from `git log`.

**Testing**: Manual review against the spec's checklist (`specs/015-tsc-charter/checklists/requirements.md`). No automated test framework is required for v1, though a future task may add a CI lint that validates the roster file's parseable structure.

**Target Platform**: GitHub-hosted Markdown rendering (web + raw). Files are also expected to render acceptably in any LF Projects / OpenSSF reviewer's Markdown viewer.

**Project Type**: Project governance documentation (not a code feature). Single deliverable bundle of Markdown files.

**Performance Goals**: N/A. The artifact is a static text document.

**Constraints**:
- Charter document content licensed under CC-BY-4.0 (per FR-009).
- Charter MUST be discoverable from the repository root (per FR-012) -- a top-level `GOVERNANCE.md` index is the chosen entry point.
- Roster format MUST be parseable as a single edit per member change (per FR-011).
- No bespoke two-member quorum rule (per spec Assumptions); the transitional two-member posture was accepted at initial draft time and rendered moot on 2026-06-18 when the founding TSC was expanded to four members before adoption.

**Scale/Scope**:
- Four founding members (Lieberman, Cappos, Augustus, Garcia Veytia) as of 2026-06-18. Initial draft posited two founding members; the founding roster was expanded before adoption.
- One charter document, one roster file, one governance index.
- ~600-1200 lines of Markdown total expected.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The darnit constitution (v1.1.0, 2026-03-08) defines five principles, all of which govern runtime behavior of the audit framework code. This feature ships **no code** -- only Markdown governance documents. Each principle is therefore inapplicable rather than violated:

| Principle | Applicability | Note |
|---|---|---|
| I. Plugin Separation | N/A | No Python packages added; no imports. |
| II. Conservative-by-Default | N/A | No control checks; no PASS/FAIL/WARN computation. |
| III. TOML-First Architecture | N/A | No controls defined; no TOML touched. |
| IV. Never Guess User Values | N/A -- and aligned in spirit | The charter codifies *human* decision authority for governance decisions, which is consistent with the principle's stance against silent automation. The founding-member identities and affiliations were supplied explicitly by the user, not auto-detected. |
| V. Sieve Pipeline Integrity | N/A | No sieve handlers added; pipeline untouched. |

The Development Workflow section of the constitution (lint / tests / spec sync / generated docs / upstream rebase) still applies operationally: the PR that introduces these files MUST pass `ruff check` (no-op on Markdown), `pytest` (unchanged), and `validate_sync.py` (unchanged -- this feature does not modify the framework-design spec).

**Gate result**: PASS. No constitutional violations; no complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/015-tsc-charter/
+-- plan.md                 # This file (/speckit-plan command output)
+-- spec.md                 # Feature specification (/speckit-specify output)
+-- research.md             # Phase 0 output (GUAC + gittuf pattern analysis)
+-- data-model.md           # Phase 1 output (roster schema + charter outline)
+-- quickstart.md           # Phase 1 output (governance operating instructions)
+-- checklists/
|   +-- requirements.md     # Spec quality checklist (from /speckit-specify)
+-- tasks.md                # Phase 2 output (/speckit-tasks -- NOT created here)
```

No `contracts/` directory is created: this feature exposes no APIs, command schemas, network endpoints, or parser grammars. The roster's row schema (documented in `data-model.md`) is the closest equivalent to an external contract and is captured there.

### Repository Root (deliverable artifacts)

The plan delivers exactly three new top-level files in the main repository, and one CLAUDE.md pointer update:

```text
/  (repository root)
+-- GOVERNANCE.md                       # NEW -- discoverability index (FR-012)
+-- CHARTER.md                          # NEW -- the LF-template-shaped charter (FR-001, FR-003..FR-010, FR-013)
+-- TECHNICAL-STEERING-COMMITTEE.md     # NEW -- the parseable roster (FR-002, FR-011)
```

Optionally, a README.md edit may add a one-line link to `GOVERNANCE.md` to satisfy "linked from the README" alternative in FR-012; this is decided in the `/speckit-tasks` phase.

**Structure Decision**: Three top-level Markdown files plus an index. The split (`CHARTER.md` <-> `TECHNICAL-STEERING-COMMITTEE.md`) mirrors gittuf's structure exactly so that future readers familiar with gittuf can navigate without retraining. `GOVERNANCE.md` is a lightweight index because the LF template document itself (`CHARTER.md`) is long and a one-screen entry point improves discoverability (SC-001 -- "under 2 minutes" to find current TSC + change rule).

## Complexity Tracking

No constitution violations. Table omitted.
