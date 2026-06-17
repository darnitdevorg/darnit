# darnit Technical Charter

This Technical Charter (the "Charter") sets forth the responsibilities and procedures for technical contribution to, and oversight of, the darnit Project (the "Project").

## 1. Mission and Scope of the Project

The mission of the darnit Project is to provide an extensible, AI-assisted compliance auditing framework that separates a vendor-neutral core from pluggable compliance implementations, so that open source projects can be audited against multiple security and governance baselines (e.g., the OpenSSF Baseline) without re-implementing the auditing engine.

The scope of the Project includes the framework, its first-party compliance implementations maintained in the same repository, and the tooling required to author, validate, and ship those implementations.

## 2. Technical Steering Committee

### 2.1 Composition

The Project is governed by a Technical Steering Committee (the "TSC"). The TSC operates as a single-tier body: there is one TSC for the entire Project, regardless of the number of packages or implementations the Project ships.

The current voting members of the TSC are listed in [TECHNICAL-STEERING-COMMITTEE.md](./TECHNICAL-STEERING-COMMITTEE.md), with affiliation and industry-or-academia category disclosed for each member.

The TSC has no fixed maximum size. Membership is not time-bounded — members serve until resignation or removal under Section 2.5.

### 2.2 Responsibilities

The TSC is responsible for oversight of the Project, including:

- Setting the Project's overall technical direction;
- Approving Project releases and security policy;
- Organizing, creating, and removing sub-projects or working groups;
- Appointing representatives to other communities and foundations on the Project's behalf;
- Establishing community norms, contribution workflows, and review processes;
- Voting on cross-Project technical matters; and
- Amending this Charter under Section 8.

The TSC MAY delegate operational responsibilities — such as day-to-day Pull Request review and release execution — to maintainers under separate community documentation. Such delegation does not transfer the TSC's authority; the TSC remains the source of policy.

### 2.3 Chair

The TSC MAY elect a Chair from among its members. The Chair, if elected, presides over TSC discussions and serves as the Project's primary point of contact for foundation liaisons. The Chair serves until resignation or replacement by a subsequent TSC vote. The Project does not require a Chair to function; in the absence of a Chair, foundation liaison MAY be designated ad hoc by simple majority of the TSC for the matter at hand.

### 2.4 Adding a Member

A candidate for TSC membership is nominated by an existing TSC member. The nomination is recorded as a Pull Request that adds a row to [TECHNICAL-STEERING-COMMITTEE.md](./TECHNICAL-STEERING-COMMITTEE.md) populated with the candidate's name, affiliation, category, and GitHub handle.

Existing TSC members vote on the nomination by approving or declining the Pull Request. The candidate is added to the TSC when a majority of the entire current TSC has approved the Pull Request, in accordance with Section 3 (TSC Voting). The merge commit is the canonical record of the decision.

### 2.5 Removing a Member

A TSC member MAY resign at any time by opening a Pull Request that removes their row from [TECHNICAL-STEERING-COMMITTEE.md](./TECHNICAL-STEERING-COMMITTEE.md). A resignation Pull Request does not require a vote; acknowledgment by another TSC member who merges the Pull Request suffices.

A TSC member MAY be removed for cause — including, but not limited to, inactivity or a serious violation of the Project's Code of Conduct — by a vote of the *other* current TSC members. The member under review MUST NOT vote on their own removal. Removal for cause requires the approval of a majority of the other current TSC members, at the same level as ordinary TSC decisions.

For the purposes of this Section, "inactivity" is not defined by a fixed numeric threshold (such as a specific number of months without contribution). Inactivity is a discretionary judgment by the remaining TSC members, initiated by a public GitHub Issue or Pull Request describing the basis for the proposed removal and resolved by the removal-for-cause threshold above.

### 2.6 Transitional Note on a Two-Member TSC

While the TSC has only two voting members, "a majority of the other current TSC members" arithmetically resolves to a majority of one — meaning that a single remaining member may effect a removal under Section 2.5. The TSC recognizes this as a known concentration risk of the rule in Section 2.5 and intends to recruit a third member promptly to restore meaningful pluralism in removal decisions. This Section is informational; it does not modify the threshold in Section 2.5.

## 3. TSC Voting

The TSC's goal is to operate as a consensus-based community. When a decision cannot be reached by consensus, the TSC MAY decide the matter by a vote conducted in accordance with this Section.

### 3.1 General Voting Rules

- Each TSC member has one vote.
- Quorum for a vote is fifty percent (50%) of the current voting members of the TSC.
- For a meeting or synchronous vote in which a quorum is present, a decision is approved by a simple majority of the members voting in favor versus against; abstentions do not count toward the total. Ties fail.
- For decisions conducted electronically (e.g., on a Pull Request or GitHub Issue rather than in a meeting), a decision is approved when a majority of the entire TSC has voted in favor.
- Amendments to this Charter (Section 8) and exceptions to the Project's stated license policy (Section 7) require the approval of at least two-thirds (2/3) of the entire TSC, not merely of those voting.

### 3.2 Recording Votes

Votes on decisions that modify a tracked file — the roster, this Charter, or any other policy file in the repository — are recorded by GitHub Pull Request approvals on the affected file. The Pull Request review state and the resulting merge commit constitute the canonical vote record.

Votes on decisions that do not modify a file (for example, approving a representative to an external community, or endorsing an external statement on the Project's behalf) are recorded in a GitHub Issue or Discussion thread. Each TSC member casts a vote as an explicit comment of `+1`, `-1`, or `+0` on a single comment line, so that the tally is unambiguous to a casual reader and parseable by tooling. Subsequent artifacts that depend on the decision MUST link to the recording Issue or Discussion.

### 3.3 Deadlocks

If the TSC is unable to reach quorum, or to resolve a deadlock through ordinary voting under Section 3.1, the matter MAY be escalated to the LF Projects Series Manager once the Project is hosted under The Linux Foundation. Until such time as the Project is formally hosted, deadlocks are resolved by good-faith re-discussion among the TSC members.

## 4. Compliance with Policies

### 4.1 Code of Conduct

The TSC and all Project contributors are subject to the Project's Code of Conduct, when adopted. Until the Project adopts a Code of Conduct of its own, the [LF Projects Code of Conduct](https://lfprojects.org/policies/code-of-conduct/) applies by default.

### 4.2 Trademark and Antitrust

The Project's name and any associated trademarks are the property of their respective holders. The TSC operates in compliance with applicable antitrust laws and avoids any discussion or action that would constitute unlawful coordination among competing organizations.

### 4.3 Developer Certificate of Origin

All contributions to the Project, including contributions to this Charter, MUST be signed off under the [Developer Certificate of Origin (DCO) version 1.1](https://developercertificate.org/).

## 5. Community Assets

The Project maintains the following community assets:

- **Source repository**: <https://github.com/kusari-oss/darnit>
- **Issues**: <https://github.com/kusari-oss/darnit/issues>
- **Discussions**: <https://github.com/kusari-oss/darnit/discussions>
- **Security reports**: see [SECURITY.md](./SECURITY.md)

Additional assets — for example, mailing lists, chat channels, or meeting venues — MAY be added by TSC decision and announced through the Project's existing channels.

## 6. General Rules and Operations

The TSC will operate in a transparent, open, collaborative, and ethical manner at all times. The TSC will not seek to exclude any participant on any criteria other than those that are reasonable and applied on a non-discriminatory basis.

All TSC meetings, when held, are open to the public. Decisions reached outside of meetings (for example, on Pull Requests or in Issues per Section 3.2) are public by virtue of the venue.

TSC members are expected to disclose any conflicts of interest material to a decision before the TSC and to recuse themselves from decisions where their impartiality would be reasonably questioned.

## 7. Intellectual Property Policy

The Project ships the following classes of work under the following licenses:

- **Source code** is licensed under the Apache License, version 2.0.
- **Documentation**, including this Charter, is licensed under the Creative Commons Attribution 4.0 International License (CC-BY-4.0).
- **Data** distributed by the Project is licensed under the Community Data License Agreement — Permissive, version 2.0 (CDLA-Permissive-2.0).

Contributions to the Project MUST be made under terms compatible with these licenses. Exceptions to the license stack require a vote of the TSC under Section 3.1 with the two-thirds threshold.

## 8. Amendments

This Charter MAY be amended by a Pull Request modifying this document, approved by at least two-thirds (2/3) of the entire TSC in accordance with Section 3.

A proposed amendment SHOULD be announced through the Project's existing communication channels and allow a reasonable comment window before merge, so that the community has the opportunity to weigh in.

---

**Adopted**: 2026-06-17

**Provenance**: Adapted from the LF Projects Technical Charter, also used by the [GUAC](https://github.com/guacsec/governance) and [gittuf](https://github.com/gittuf/community) projects.

**License**: This document is licensed under the Creative Commons Attribution 4.0 International License (CC-BY-4.0).
