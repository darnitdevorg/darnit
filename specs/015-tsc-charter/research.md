# Phase 0 Research: TSC Charter Patterns

**Feature**: 015-tsc-charter | **Date**: 2026-06-17

This phase consolidates the GUAC and gittuf TSC patterns the spec is modeled on, captures the contested design choices, and records the decision + rationale + rejected alternatives for each one. Per the spec's clarifications session (2026-06-17), all open ambiguities are resolved.

## Source Material

### GUAC

- **Authoritative location**: `guacsec/governance` repo. Documents: `CHARTER.MD` (LF Projects Technical Charter), `GOVERNANCE.md`, `STEERING_COMMITTEE`, `MAINTAINERS.<core-project>`, `CODE_OF_CONDUCT.md`. License: CC BY 4.0.
- **Structure**: Two-tier. A GUAC Steering Committee sits above multiple Core Projects (GUAC, Trustify) which each run their own contributor ladder.
- **TSC composition**: 3 general seats + 1 per core project (latter must be a maintainer on that core project). Affiliation diversity hard rule: at least 2 different employers. Minimum 3 active members. No fixed terms; inactivity >3 months = removal.
- **Add/remove**: Public proposal as governance-repo issue, announced on all community channels, 2-week window, simple majority of SC.
- **Voting**: Consensus-first. Voting fallback: one vote per member, simple majority of attendees with 50% quorum. Charter amendments and license exceptions require 2/3 of the entire TSC.
- **Chair**: Optional. Serves until resignation or replacement; no fixed term.
- **Meetings**: Public; minutes in `meetings/`.

### gittuf

- **Authoritative location**: `gittuf/community` repo. Documents: `CHARTER.md` (LF Projects Technical Charter), `TECHNICAL-STEERING-COMMITTEE.md` (roster with affiliation + industry/academia tag), `CONTRIBUTOR_LADDER.md`, `CODE-OF-CONDUCT.md`. Main code repo carries `MAINTAINERS.txt`.
- **Structure**: Single-tier. One project, one TSC.
- **TSC composition**: Initially = the project's Committers. Roster currently 5 people, each labelled with affiliation + industry/academia tag. No hard quota. No fixed size, no term limits.
- **Add/remove**: "Contributor may become a Committer by a majority approval of the existing Committers." Removal by majority approval of the *other* existing Committers. Promotion criteria (substantial PRs / reviews) live in `CONTRIBUTOR_LADDER.md`.
- **Voting**: Consensus-first. Voting fallback identical to GUAC (one vote, simple majority with 50% quorum, 2/3 of entire TSC for amendments/license exceptions). Deadlocks escalate to LF Projects Series Manager.
- **Chair**: Optional. Same posture as GUAC.
- **Meetings**: Public; 2nd Friday 11:00 ET and 4th Friday 10:00 ET monthly; notes in public Google Docs; mailing list + Slack.

### Shared substrate

Both projects use the **LF Projects Technical Charter** template verbatim (Sections 1-8: Mission, TSC, Voting, Compliance, Community Assets, General Rules, IP Policy, Amendments). License stack is Apache-2.0 code, CC-BY-4.0 docs, CDLA-Permissive-2.0 data, DCO required. CoC fallback to LF Projects CoC if no project-specific CoC exists.

## Decisions

### D1 -- Governance tier structure

- **Decision**: Single-tier (gittuf-shape).
- **Rationale**: darnit is one product/repo today. GUAC's two-tier shape exists because it stewards multiple Core Projects (GUAC, Trustify). Adopting two-tier prematurely would require defining sub-project semantics that don't yet exist.
- **Alternatives considered**: GUAC-style two-tier; rejected because there's no sub-project today. The charter's amendment clause provides a path to two-tier in a future version if darnit grows siblings.

### D2 -- Founding roster size & balance

- **Decision**: Two founding members -- Michael Lieberman (Kusari, industry, @mlieberman85) and Justin Cappos (NYU, academia, @JustinCappos). Industry/academia tag + GitHub handle inline per gittuf precedent.
- **Rationale**: User-supplied. The split signals diversity intent on day one (the same tag convention gittuf uses for its 5-person roster). Recruiting a third member to restore meaningful quorum is recorded as a near-term action in the spec assumptions.
- **Alternatives considered**: Recruit a third member before launching the charter; rejected because the charter is needed now and the transitional two-member posture is explicitly accepted.

### D3 -- Diversity guard mechanism

- **Decision**: Transparency-by-labelling (gittuf-style). The roster columns `affiliation` and `category [industry|academia]` surface concentration risk; no hard ">=N different employers" quota is imposed by the charter.
- **Rationale**: A quota with only two members is either trivial (already satisfied 1:1) or coercive (would force structure on the next hire). Transparency lets the community judge concentration without binding future TSC composition decisions.
- **Alternatives considered**: GUAC's "at least 2 different employers" rule; rejected because it adds rigidity that pays off mainly at GUAC's larger roster size and tier complexity.

### D4 -- Vote recording mechanism *(clarified in spec session 2026-06-17)*

- **Decision**: GitHub PR approvals on the affected file are the canonical vote record for file-bound decisions (roster, charter, policy). For decisions without a file artifact, a GitHub Issue or Discussion with explicit `+1`/`-1`/`+0` comments from TSC members serves the same role.
- **Rationale**: Aligns with gittuf's operating practice, keeps the audit trail in git (immutable, DCO-signed), uses tooling darnit already runs on, and avoids creating a meetings infrastructure dependency on day one. PR review state is also queryable by the GitHub API for future automation.
- **Alternatives considered**:
  - *Public meeting minutes as canonical* (closer to GUAC's `meetings/` directory): rejected because it presumes a meeting cadence darnit hasn't established and a notes-keeping role nobody is yet assigned.
  - *Hybrid (PR for routine, minuted meeting for amendments)*: rejected as a needless dual-track. The charter's 2/3 supermajority for amendments + PR approvals on the charter file already provides the same auditability.

### D5 -- Charter location

- **Decision**: Charter and roster live at the top of the main `kusari-oss/darnit` repository -- `CHARTER.md`, `TECHNICAL-STEERING-COMMITTEE.md`, with a thin `GOVERNANCE.md` discoverability index. No separate `kusari-oss/darnit-community` governance repo at v1.
- **Rationale**: Both reference projects host governance in a separate community repo, but that separation makes sense at their scale (multiple maintained repos, working groups, meetings infrastructure). darnit has one repo. A separate community repo creates discoverability friction with no compensating benefit at v1.
- **Alternatives considered**: Separate community repo from day one (GUAC/gittuf pattern); rejected as premature. The charter's amendment clause lets a future TSC vote in a community-repo split when the project's structure warrants it.

### D6 -- Removal-for-cause threshold *(clarified in spec session 2026-06-17)*

- **Decision**: Majority of the *other* current TSC members; the member under review does not vote on their own removal. Same level as ordinary decisions (not a supermajority).
- **Rationale**: gittuf's exact rule. Self-recusal removes the most obvious conflict; a supermajority on top would create a tractable veto for any 1-of-3 member to block their own removal.
- **Alternatives considered**:
  - *Supermajority (2/3 of other members)*: rejected because at small TSC sizes (2-4) the supermajority and simple majority of others are arithmetically identical or near-identical; complexity without benefit.
  - *Unanimous of other members*: rejected because it gives any single other member veto power over a removal, which inverts the concentration concern the rule is meant to address.
- **Known consequence**: In the founding two-member regime, a majority of "the other members" means a majority of one -- a single member alone can effect a removal. This is recorded as an edge case in the spec and is one driver for the "recruit a third member promptly" near-term action.

### D7 -- Definition of "inactivity" *(clarified in spec session 2026-06-17)*

- **Decision**: No fixed numeric threshold. Inactivity is a discretionary judgment by the remaining TSC members, initiated via a public issue or PR and resolved by the removal-for-cause threshold (D6).
- **Rationale**: gittuf's posture. Numeric thresholds (e.g., GUAC's ">3 months") look objective but are gameable (lurking with one comment per quarter) and brittle (a maintainer with a documented sabbatical isn't actually inactive). A discretionary call with a public paper trail (issue/PR + threshold vote) gives the same auditability without the false precision.
- **Alternatives considered**:
  - *GUAC's ">3 months" rule*: rejected as false precision; encodes a single shape of inactivity (no comments) and misses others.
  - *Time + activity composite (e.g., "no PR review or vote in 6 months")*: rejected as premature optimization for a TSC that hasn't yet hit its first inactive-member case.

### D8 -- Chair election

- **Decision**: Optional. May be elected by simple majority; serves until resignation or replacement. No requirement to have a chair at v1.
- **Rationale**: gittuf precedent. With two founding members, electing a chair adds ceremony without function. Foundation liaison can be designated ad-hoc by simple majority on the rare occasions it's needed.
- **Alternatives considered**: Mandatory chair from day one; rejected as overhead for a two-member TSC.

### D9 -- License of the charter document

- **Decision**: CC-BY-4.0.
- **Rationale**: Matches both reference projects and the LF Projects governance doc convention. Permissive enough that downstream projects can fork the charter as a template.
- **Alternatives considered**: Apache-2.0 (code-style license on a doc -- semantically awkward); CC0 (waives attribution, which is incompatible with the "derived from LF Projects template" provenance).

### D10 -- Code of Conduct posture

- **Decision**: The charter names the project Code of Conduct as the governing CoC if one exists at the time the charter merges; otherwise the LF Projects CoC applies by default. The CoC itself is **out of scope** for this feature.
- **Rationale**: A CoC is a separate document with its own review and adoption cycle (often by the broader community, not just the TSC). Bundling it into this PR would slow the charter without changing the substantive governance.
- **Alternatives considered**: Author a project-specific CoC in the same PR; rejected as scope creep. A follow-on feature can adopt the Contributor Covenant or an LF-aligned CoC.

## Open items deferred to `/speckit-tasks`

None. All ambiguities were resolved in the spec clarification session. The remaining decisions are formatting and ordering choices best made during charter drafting (Phase 2 -- `/speckit-tasks`), not architectural research questions.
