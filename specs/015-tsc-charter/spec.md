# Feature Specification: Technical Steering Committee Charter

**Feature Branch**: `015-tsc-charter`

**Created**: 2026-06-17

**Status**: Draft

**Input**: User description: "I want to draft up real quick a technical steering committee charter and list of people in it. It should follow a similar pattern the technical steering committee that GUAC has and gittuf has. The people who belong to that steering committee first should be Michael Lieberman (Kusari, industry, @mlieberman85) and Justin Cappos (New York University, academia, @JustinCappos)."

## Clarifications

### Session 2026-06-17

- Q: How are TSC votes mechanically recorded and made auditable? -> A: GitHub PR approvals on the affected file (roster, charter, policy) are the canonical vote record; for decisions without a file artifact, a GitHub Issue/Discussion with explicit "+1/-1" approval comments from TSC members serves the same role. Mirrors gittuf's pattern.
- Q: What is the threshold for removal-for-cause, and how is "inactivity" defined? -> A: Apply gittuf's defaults for both. Removal-for-cause requires majority approval of the *other* TSC members (the member under review does not vote on their own removal), at the same level as ordinary decisions rather than a supermajority. Inactivity is NOT defined by a fixed numeric threshold; it is a discretionary judgment by the remaining TSC members, initiated via a public issue or PR and resolved by the removal-for-cause threshold above.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Published charter establishes governance authority (Priority: P1)

A new contributor, downstream consumer, or OpenSSF/LF representative needs to know who is empowered to make binding technical decisions for the darnit project, how they got there, and how they can be removed. They open the charter in the repo and find a clear, self-contained document modeled on the LF Projects Technical Charter pattern used by GUAC and gittuf.

**Why this priority**: Without a published charter, the project has no documented authority structure. This is the minimum viable artifact -- even with no other governance scaffolding (working groups, sub-projects, meeting cadence), a charter + roster lets the project make binding decisions, accept upstream/foundation engagement, and demonstrate that maintenance is not a single person.

**Independent Test**: A reader unfamiliar with the project can answer, from the charter alone, the following questions: Who is on the TSC today? What is the TSC's scope? How are decisions made? How are members added and removed? What is the escalation path?

**Acceptance Scenarios**:

1. **Given** the charter is published at a discoverable path in the repository, **When** a reader opens it, **Then** they find the TSC's purpose, current roster with affiliations, voting rules, and amendment process without needing to consult external documents.
2. **Given** a reader is comparing darnit's governance to GUAC's and gittuf's, **When** they read the charter, **Then** they recognize the same LF-template structure (Mission, TSC, Voting, Compliance, Community Assets, General Rules, IP Policy, Amendments) so foundation reviewers and adopters can map it onto familiar precedent.

---

### User Story 2 - Initial roster reflects industry + academia balance (Priority: P1)

The community and foundation reviewers need to see that the TSC is not single-vendor controlled. The initial roster lists Michael Lieberman (Kusari, industry) and Justin Cappos (New York University, academia), each tagged with affiliation and GitHub handle in the same machine-readable style gittuf uses.

**Why this priority**: The two founding members and their industry/academia split are the explicit ask. Mirroring gittuf's roster format (affiliation + industry/academia tag) signals diversity intent on day one even though the charter does not impose a hard quota.

**Independent Test**: The roster file or roster section can be parsed by a human or trivial script to extract `(name, affiliation, category, github_handle)` for every member.

**Acceptance Scenarios**:

1. **Given** the roster is published, **When** a reader inspects it, **Then** they see Michael Lieberman tagged as Kusari/industry/@mlieberman85 and Justin Cappos tagged as NYU/academia/@JustinCappos.
2. **Given** a future member needs to be added, **When** a maintainer follows the membership change process from the charter, **Then** the roster format makes it obvious how to insert a new row without restructuring the document.

---

### User Story 3 - Membership changes have a documented, auditable process (Priority: P2)

A maintainer wants to propose adding a new TSC member, or a member wants to step down. The charter spells out the mechanism (who initiates, who votes, what threshold, what notification window) so the change can be made via a PR with a clear approval path rather than ad-hoc decision-making.

**Why this priority**: Without this, the founding roster ossifies and every membership change becomes a one-off debate. It is not P1 because the charter is still useful at v1 with just the addition/removal rules from the LF template -- but documenting it explicitly is what makes the governance actually run.

**Independent Test**: Given the charter, a maintainer can write a PR that adds or removes a TSC member and point to the exact charter clauses that authorize the change.

**Acceptance Scenarios**:

1. **Given** an existing TSC member nominates a candidate, **When** the charter's membership process is followed, **Then** the outcome (approved/rejected) is determined by an explicit voting rule and the change is recorded by editing the roster file.
2. **Given** a TSC member has been inactive, **When** the charter's removal process is invoked, **Then** the criteria for inactivity and the required approval threshold are both unambiguous from the charter text.

---

### Edge Cases

- **Two-member quorum**: With only two founding members, a 50% quorum / majority rule means a single member can carry a vote. The charter should either (a) accept this as a transitional posture until the TSC grows, or (b) require unanimity from the founding members until a third member joins. The default chosen here is (a) with an explicit assumption that the TSC will recruit a third member promptly; see Assumptions.
- **Affiliation drift**: If a member's employer changes such that the industry/academia balance flips, the roster must be updated, but the charter does not force resignation. The roster's affiliation column is the source of truth.
- **Tie votes**: With an even number of members and no chair tiebreaker, a tie on a non-amendment vote means the motion fails. Amendments and license exceptions already require a two-thirds supermajority, which is unaffected.
- **Removal-for-cause in a two-member TSC**: Under FR-006, the member under review does not vote on their own removal, so a majority of the *other* members means a majority of one -- i.e., the remaining member alone can effect a removal. This is a known concentration risk of the gittuf-aligned threshold while the TSC has only two members and is one of several reasons the spec assumes a third member will be recruited promptly. The risk is accepted at v1 as a transitional posture rather than mitigated with a bespoke two-member supermajority rule.
- **Chair vacancy**: The charter permits but does not require a chair. If no chair is elected, the TSC operates without one; foundation liaison falls to any member designated by simple majority on an ad-hoc basis.
- **External escalation**: If the TSC deadlocks or quorum cannot be reached for an extended period, the LF Projects Series Manager / OpenSSF TAC is the escalation path, per the LF template.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST contain a TSC charter document that follows the LF Projects Technical Charter template structure used by GUAC and gittuf, with sections covering Mission/Scope, TSC composition and authority, Voting & decision-making, Compliance/CoC, Community assets, General rules, IP policy, and Amendments.
- **FR-002**: The charter MUST list the initial TSC roster with: full name, affiliation, industry-or-academia tag, and GitHub handle, formatted in the same row-per-member style as gittuf's `TECHNICAL-STEERING-COMMITTEE.md`. The initial roster MUST include Michael Lieberman (Kusari, industry, @mlieberman85) and Justin Cappos (New York University, academia, @JustinCappos).
- **FR-003**: The charter MUST define the TSC's scope of authority, explicitly enumerating: setting technical direction; approving releases and security policy; managing sub-projects/working groups; appointing representatives to upstream foundations; and amending the charter itself.
- **FR-004**: The charter MUST specify the decision-making process as consensus-first with a voting fallback. Voting fallback MUST define: one vote per voting member; 50% quorum; simple majority of attendees with quorum for ordinary decisions; two-thirds of the entire TSC for charter amendments and license exceptions.
- **FR-005**: The charter MUST define the membership change process: how a candidate is nominated, who votes, the approval threshold, and how the change is recorded (i.e., a PR editing the roster file).
- **FR-006**: The charter MUST define a removal process covering both voluntary resignation and removal for cause (including inactivity). For removal-for-cause, the approval threshold MUST be a majority of the *other* current TSC members; the member under review MUST NOT vote on their own removal. Inactivity for the purposes of removal-for-cause MUST NOT be defined by a fixed numeric threshold (e.g., a specific number of months); it is a discretionary judgment by the remaining TSC members, initiated via a public issue or PR and resolved by the removal-for-cause threshold.
- **FR-007**: The charter MUST identify the project Code of Conduct that applies to TSC members and the fallback CoC (the LF Projects CoC) if no project-specific CoC has been adopted.
- **FR-008**: The charter MUST state the licensing posture for code (Apache-2.0), documentation (CC-BY-4.0), and data (CDLA-Permissive-2.0) consistent with GUAC and gittuf, and MUST require DCO sign-off on contributions.
- **FR-009**: The charter MUST be licensed under CC-BY-4.0 and that license MUST be stated in or alongside the document itself.
- **FR-010**: The charter MUST describe how it is amended, with the amendment threshold matching the two-thirds supermajority of the entire TSC defined in FR-004.
- **FR-011**: The roster MUST be structured so that adding or removing a member is a single localized edit (one row added/removed) requiring no restructuring of surrounding prose.
- **FR-012**: The charter MUST be discoverable from the repository root -- either by living at a conventional top-level path (e.g., `CHARTER.md`, `GOVERNANCE.md`) or by being linked from the README and/or a top-level `GOVERNANCE.md` pointer.
- **FR-013**: The charter MUST identify the canonical record of a TSC vote. For decisions that modify a tracked file (the roster, the charter itself, or any other policy file in the repository), the GitHub Pull Request approvals on that file ARE the vote record and MUST satisfy the thresholds in FR-004. For decisions that do not modify a file (e.g., approving a representative, endorsing an external statement), a GitHub Issue or Discussion thread containing explicit `+1` / `-1` / `+0` comments from TSC members serves the same role and MUST be linked from any subsequent artifact that depends on the decision.

### Key Entities

- **Charter**: The governing document. Contains the full LF-template-style text. Single canonical copy in the repository.
- **TSC Roster**: The ordered list of current TSC members. Each entry records: `(name, affiliation, category [industry|academia], github_handle)`. May live inside the charter or as a sibling file (`TECHNICAL-STEERING-COMMITTEE.md`) that the charter references.
- **TSC Member**: A natural person with one vote on TSC matters. Identified by GitHub handle for action attribution (PR approvals, votes recorded in issues).
- **Affiliation**: The organization a TSC member is associated with for the purpose of disclosure. Used to surface concentration risk (e.g., single-employer dominance) even though the v1 charter does not impose a hard quota.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reader unfamiliar with the project can identify the current TSC members and the rule for changing membership in under 2 minutes from landing on the repository root.
- **SC-002**: The charter passes a structural diff against the LF Projects Technical Charter template: all eight canonical sections (Mission, TSC, Voting, Compliance, Community Assets, General Rules, IP Policy, Amendments) are present and ordered as in the template.
- **SC-003**: 100% of TSC members in the roster have all four required fields populated (name, affiliation, category, GitHub handle).
- **SC-004**: A maintainer can execute a hypothetical membership change (add or remove a member) by editing exactly one file in a single PR, with the charter clauses they're invoking citable by section reference.
- **SC-005**: The charter is internally consistent: every voting threshold mentioned in narrative text matches the numeric thresholds defined in the Voting section (no contradictions between, e.g., "majority" in one place and "two-thirds" in another for the same action).

## Assumptions

- **Single-tier governance**: Darnit is presently a single project, so the charter mirrors gittuf's single-tier (TSC over one project) rather than GUAC's two-tier (Steering Committee over multiple Core Projects). Should darnit later grow sibling sub-projects, a future amendment can introduce the two-tier shape.
- **Charter location**: The charter lives in the main `kusari-oss/darnit` repository at a top-level path (e.g., `GOVERNANCE.md` or `CHARTER.md` with the roster either embedded or as a sibling `TECHNICAL-STEERING-COMMITTEE.md`). No separate `community` governance repo is created at v1.
- **Transitional two-member TSC**: With only two founding members, the 50%-quorum / majority-of-attendees rule technically allows a single member to carry a vote. This is accepted as a transitional posture; the TSC is expected to recruit a third member promptly to restore meaningful quorum, and the charter notes this as a near-term action rather than a permanent regime.
- **No fixed terms, no chair required**: Following gittuf's pattern, members serve until resignation or removal; no fixed term lengths. A chair MAY be elected but is not required at v1.
- **Diversity by transparency, not quota**: Following gittuf's pattern of labelling affiliation + industry/academia in the roster, rather than GUAC's hard "at least two different employers" rule. Concentration risk is surfaced rather than enforced.
- **License of the charter itself**: CC-BY-4.0, consistent with both reference projects' governance documents.
- **CoC**: Project will adopt a CoC consistent with OpenSSF/LF norms; if none is present at the time the charter merges, the LF Projects CoC applies by default.
- **Foundation alignment**: The charter is written so that it can be submitted to OpenSSF / LF Projects without structural changes if darnit chooses formal foundation hosting in the future, but the charter does not presume that hosting has happened.
- **Out of scope for this spec**: Drafting the project Code of Conduct, defining a Contributor Ladder, scheduling community meetings, or creating a separate governance repository. Each of these is a logical follow-on once the charter is in place.
