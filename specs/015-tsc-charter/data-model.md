# Phase 1 Data Model: TSC Charter Artifacts

**Feature**: 015-tsc-charter | **Date**: 2026-06-17

This feature ships no runtime data -- the "data model" here describes the Markdown document shapes the charter and roster files MUST conform to. Each shape is testable against the spec's success criteria.

## Entity 1 -- Charter document (`CHARTER.md`)

The charter follows the LF Projects Technical Charter template structure, mirroring GUAC and gittuf.

### Required sections (in order)

| # | Section heading | Required content |
|---|---|---|
| 1 | Mission and Scope of the Project | One paragraph stating darnit's mission (AI-assisted compliance auditing with a plugin architecture) and the scope the TSC stewards. References the spec's FR-003 enumeration of authority. |
| 2 | Technical Steering Committee | Composition rules (single-tier, members initially = founding committers per D2/D3). Pointer to `TECHNICAL-STEERING-COMMITTEE.md` for the live roster. Membership change process (FR-005), removal process (FR-006), chair (D8). |
| 3 | TSC Voting | Decision-making rules: consensus-first; voting fallback per FR-004 (one vote per member, 50% quorum, simple majority of attendees, 2/3 of entire TSC for amendments and license exceptions). Vote recording mechanism per FR-013. |
| 4 | Compliance with Policies | CoC pointer (D10), DCO requirement (FR-008), trademark notes if applicable, antitrust compliance language from the LF template. |
| 5 | Community Assets | Repositories, mailing lists, communication channels owned by the project. |
| 6 | General Rules and Operations | Transparency obligations, conflict of interest, non-discrimination language from the LF template. |
| 7 | Intellectual Property Policy | License stack per FR-008 (Apache-2.0 code, CC-BY-4.0 docs, CDLA-Permissive-2.0 data). |
| 8 | Amendments | Amendment process and threshold (2/3 of entire TSC, per FR-010 referencing FR-004). |

### Required metadata (in document)

- **License notice**: "This document is licensed under CC-BY-4.0." (FR-009)
- **Adopted date**: ISO-8601 date when the charter is first merged (analogous to gittuf's "Adopted: November 2nd, 2023").
- **Provenance line**: "Adapted from the LF Projects Technical Charter, also used by GUAC and gittuf."

### Validation rules

| Rule | Check |
|---|---|
| All eight sections present in order | Heading count + order matches the table above (SC-002). |
| No `[NEEDS CLARIFICATION]` markers | `grep -n "NEEDS CLARIFICATION" CHARTER.md` returns nothing. |
| Voting thresholds consistent | Every numeric threshold in narrative text matches the Voting section (SC-005). |
| License notice present | Document contains "CC-BY-4.0" verbatim once. |

## Entity 2 -- Roster (`TECHNICAL-STEERING-COMMITTEE.md`)

The roster is a parseable list. Each member is exactly one row in a Markdown table; adding or removing a member is a one-line edit (FR-011).

### Row schema

| Column | Type | Required | Constraints |
|---|---|---|---|
| `Name` | string | yes | Full personal name. |
| `Affiliation` | string | yes | Organization (employer, university, "Independent"). |
| `Category` | enum | yes | One of: `industry`, `academia`, `independent`. |
| `GitHub` | string | yes | GitHub handle prefixed with `@`. Must resolve to an existing GitHub user at insertion time. |
| `Role` | enum | optional | One of: `member`, `chair`. Default: `member`. Only one row may carry `chair` at a time. |

### Required document structure

```markdown
# Technical Steering Committee

<!-- Adopted: YYYY-MM-DD. License: CC-BY-4.0. -->

The current voting members of the darnit Technical Steering Committee are:

| Name | Affiliation | Category | GitHub | Role |
|------|-------------|----------|--------|------|
| Michael Lieberman | Kusari | industry | @mlieberman85 | member |
| Justin Cappos | New York University | academia | @JustinCappos | member |
| Stephen Augustus | Bloomberg | industry | @justaugustus | member |
| Adolfo Garcia Veytia | Carabiner | industry | @puerco | member |

For the rules that govern membership, voting, and amendments, see
[CHARTER.md](./CHARTER.md).
```

### Validation rules

| Rule | Check |
|---|---|
| All four required columns populated for every row | No empty cells in `Name`, `Affiliation`, `Category`, `GitHub` (SC-003). |
| `Category` is one of the enum values | Each row's `Category` matches `industry\|academia\|independent`. |
| `GitHub` handle prefixed with `@` | Regex `^@[A-Za-z0-9-]+$` per row. |
| At most one chair | `grep -c "| chair " TECHNICAL-STEERING-COMMITTEE.md` <= 1. |
| Initial roster matches user input | Four founding rows in joining order: Michael Lieberman / Kusari / industry / @mlieberman85; Justin Cappos / New York University / academia / @JustinCappos; Stephen Augustus / Bloomberg / industry / @justaugustus; Adolfo Garcia Veytia / Carabiner / industry / @puerco. |

### State transitions

```text
              propose                       majority of TSC               edit roster row
[Candidate] ------------> [Pending] ------------------------> [Accepted] -----------------> [Member]
                                            (PR approvals or                    |
                                             issue/discussion                   | resign / removed-for-cause
                                             vote per FR-013)                   | (majority of other TSC members)
                                                                                v
                                                                          [Departed]
```

State transitions are recorded by edits to the roster file plus the corresponding PR/issue thread. No separate state-tracking artifact is required.

## Entity 3 -- Governance index (`GOVERNANCE.md`)

A short discoverability index pointing to the two documents above. Not a substitute for either.

### Required content

- Single H1: "darnit Project Governance".
- One paragraph stating that darnit is governed by a TSC.
- Two links: one to `CHARTER.md`, one to `TECHNICAL-STEERING-COMMITTEE.md`, each with a one-line description.
- Optional pointer to the project Code of Conduct when one is adopted.

### Validation rules

| Rule | Check |
|---|---|
| Both target documents exist | The two links resolve to files in the same directory. |
| File is short | <=30 lines of Markdown (it is an index, not content). |

## Cross-document invariants

| Invariant | Documents involved | Check |
|---|---|---|
| Roster cited in charter matches actual roster file | `CHARTER.md` <-> `TECHNICAL-STEERING-COMMITTEE.md` | The charter's Section 2 names the roster file by path; it does not duplicate member rows. |
| License posture consistent | All three new files | Each contains "CC-BY-4.0" notice in a comment, footer, or stated license line. |
| Vote-recording mechanism cited once | `CHARTER.md` only | FR-013's mechanism is stated in the Voting section of the charter; not duplicated elsewhere. |
| No member's name appears outside the roster | `CHARTER.md` <-> `TECHNICAL-STEERING-COMMITTEE.md` | A search for a member's GitHub handle in `CHARTER.md` returns zero matches (the charter refers to "the TSC", not to individuals -- so a future member change requires editing one file, satisfying FR-011 and SC-004). |
