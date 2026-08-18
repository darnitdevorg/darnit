# Governance

The darnit Project has been established as Darnit a Series of LF Projects, LLC, and is governed by a Technical Steering Committee (TSC) under the Project's [Technical Charter](./CHARTER.md). The Charter is the binding authority on oversight, voting, and amendments. The current voting members of the TSC are listed in [TECHNICAL-STEERING-COMMITTEE.md](./TECHNICAL-STEERING-COMMITTEE.md).

This document describes the Project's roles, how the TSC's voting membership is determined, and the operational layer below the Charter: how the Project is organized and how routine activities (PR review, releases, recording decisions) are run day to day. Operational practice may be revised by maintainer consensus without a TSC vote. Nothing here overrides the Charter — where this document and the Charter differ, the Charter controls.

## Project Structure

Darnit is organized as a monorepo using `uv` workspace:

| Package           | Purpose                                       | Maintainer |
|-------------------|-----------------------------------------------|------------|
| `darnit`          | Core framework (models, plugin system, sieve) | Core team  |
| `darnit-baseline` | OpenSSF Baseline implementation               | Core team  |

Future plugins can be developed as external packages following the plugin architecture.

## Roles and Responsibilities

The TSC sets policy. The roles below operate under that policy and are responsible for day-to-day execution. TSC members are typically also maintainers, but the two roles are distinct: TSC authority comes from the [Charter](./CHARTER.md); maintainer authority comes from commit access granted by the TSC.

- **Contributor** — anyone in the technical community who contributes code, documentation, or other technical artifacts to the Project. Participation is open to anyone who abides by the terms of the Charter (Charter 2.d).
- **Maintainer** — a Contributor who has earned the ability to commit to the Project's repository. Maintainers review and merge pull requests, manage releases and versioning, respond to security vulnerabilities, enforce the Code of Conduct, and set day-to-day technical direction within the policy set by the TSC. A Contributor becomes a Maintainer by a majority approval of the TSC, and a Maintainer may be removed by a majority approval of the TSC (Charter 2.c.iii).
- **Baseline Implementer** — a specialization of the Contributor role for those who add or modify OSPS controls, implement sieve verification passes, or write remediation functions. The role is descriptive and carries no additional commit rights.

## Technical Steering Committee Membership

Charter 2.b makes the TSC's voting members the Project's Maintainers by default and permits the TSC to adopt an alternative approach. The Project uses the following approach.

TSC voting membership is a standing roster, maintained in [TECHNICAL-STEERING-COMMITTEE.md](./TECHNICAL-STEERING-COMMITTEE.md), and is distinct from commit access: a person may be a Maintainer without being a TSC voting member, and vice versa. Each roster row records the member's name, affiliation, industry-or-academia category, and GitHub handle. Membership is not time-bounded and the TSC has no fixed maximum size — members serve until resignation or removal.

**Adding a member.** A candidate is nominated by an existing TSC voting member, as a pull request that adds a row to the roster. Existing voting members vote by approving or declining that pull request. Because this is an electronic vote taken without a meeting, approval requires a majority of all voting members of the TSC (Charter 3.c). The merge commit is the canonical record of the decision.

**Resignation.** A voting member may resign at any time by opening a pull request that removes their own row from the roster. A resignation does not require a vote; acknowledgment by another TSC member who merges the pull request is sufficient.

**Removal for cause.** Removal for cause — including, but not limited to, inactivity or a serious violation of the Code of Conduct — is initiated by a public GitHub Issue or pull request describing the basis for the proposed removal, and is decided by a vote of the *other* voting members. The member under review does not vote on their own removal and is not counted toward the total; approval requires a majority of the remaining voting members. For this purpose, "inactivity" is not defined by a fixed numeric threshold such as a number of months without contribution; it is a discretionary judgment of the remaining voting members.

## Recording TSC Decisions

The Charter sets the voting thresholds (Section 3). It does not prescribe a recording mechanism; the Project uses the following convention so that any decision can be audited after the fact.

- **Decisions that modify a tracked file** — the roster, the Charter, or any other policy file in the repository — are recorded as GitHub pull request approvals on the affected file. The pull request review state and the resulting merge commit constitute the canonical vote record.
- **Decisions that do not modify a file** — for example, appointing a representative to an external community, or endorsing an external statement on the Project's behalf — are recorded in a GitHub Issue or Discussion thread. Each TSC member casts a vote as an explicit comment of `+1`, `-1`, or `+0` on a single comment line, so that the tally is unambiguous to a casual reader and parseable by tooling. Subsequent artifacts that depend on the decision should link to the recording Issue or Discussion.

Decisions reached outside of meetings are public by virtue of the venue. Any meetings of the TSC are intended to be open to the public and may be held electronically, by teleconference, or in person (Charter 2.b).

## Conflicts of Interest

TSC members are expected to disclose any conflict of interest material to a decision before the TSC, and to recuse themselves from decisions where their impartiality would reasonably be questioned. This is a community norm rather than a Charter requirement; the Charter's transparency obligations (Section 4.e) and the LF Projects policies at <https://lfprojects.org/policies/> — including those governing antitrust compliance — apply in all cases.

## Deadlocks

If the TSC cannot reach quorum or resolve a deadlock through ordinary voting, any voting member may refer the matter to the LF Projects Series Manager for assistance in reaching a resolution (Charter 3.d). Good-faith re-discussion among TSC members is the expected first step, but it is not a precondition for referral.

## Day-to-Day PR Process

The following thresholds apply to routine PR activity. Changes to *governance itself* — this document, the [Charter](./CHARTER.md), or the [TSC roster](./TECHNICAL-STEERING-COMMITTEE.md) — follow the TSC voting rules in the Charter instead.

### Minor Changes

- Standard PR review and approval process
- One maintainer approval required

### Major Changes

- Open a GitHub Issue for discussion first
- Allow community input before implementation
- Document rationale in the PR

### Breaking Changes

- Require RFC (Request for Comments) process
- Minimum 7-day comment period
- Approval by maintainer consensus

## Release Process

1. Update version in `pyproject.toml` files
2. Update CHANGELOG.md with release notes
3. Create GitHub Release with tag
4. Automated PyPI publish via CI (when enabled)

Releases follow [Semantic Versioning](https://semver.org/):

- MAJOR: Breaking changes
- MINOR: New features (backwards compatible)
- PATCH: Bug fixes (backwards compatible)

## Licensing

The Project's license stack is set by the Charter, Section 7, and is summarized for contributors in [CONTRIBUTING.md](./CONTRIBUTING.md#licensing-of-contributions): code under Apache-2.0, documentation under CC-BY-4.0. The Charter does not establish a license for distributed data sets; should the Project ship data, the TSC would need to approve a data license (for example, CDLA-Permissive-2.0) as a license exception under Charter 7.c, by a two-thirds vote of the entire TSC.

## Code of Conduct

All participants are expected to uphold a welcoming, harassment-free environment. Be respectful, constructive, and inclusive in all interactions. The TSC may adopt a Project-specific Code of Conduct, subject to approval by the LF Projects Series Manager; until then the [LF Projects Code of Conduct](https://lfprojects.org/policies) applies to all Collaborators, per the [Charter](./CHARTER.md), Section 4.b.

## Community Assets

- **Source repository**: <https://github.com/kusari-oss/darnit>
- **Issues**: [GitHub Issues](https://github.com/kusari-oss/darnit/issues)
- **Discussions**: [GitHub Discussions](https://github.com/kusari-oss/darnit/discussions)
- **Security**: See [SECURITY.md](SECURITY.md) for vulnerability reporting

The Project develops and owns its GitHub and social media accounts and domain registrations under license from LF Projects. Trade and service marks used by the Project are held by LF Projects (or an associated hosting entity) on the Project's behalf, per Charter Section 5. Additional assets — mailing lists, chat channels, meeting venues — may be added by TSC decision and announced through the Project's existing channels.
