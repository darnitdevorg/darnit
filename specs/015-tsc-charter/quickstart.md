# Quickstart: Operating Under the TSC Charter

**Feature**: 015-tsc-charter | **Date**: 2026-06-17

A practical guide for the four most common governance actions once the charter and roster files are in place. Each action references the relevant FR(s) from `spec.md` and lines up directly with the validation rules in `data-model.md`.

## Adding a TSC member

1. **Open a PR** that adds one row to `TECHNICAL-STEERING-COMMITTEE.md` with all four required columns (`Name`, `Affiliation`, `Category`, `GitHub`) populated.
2. **Tag the PR** with `governance/tsc-membership` (or whatever label convention the repo adopts) and link to the PR in a GitHub Issue titled `TSC: add <Name>` for community visibility.
3. **Solicit votes**: existing TSC members approve or comment on the PR. Per FR-013, PR review approvals are the canonical vote record.
4. **Merge condition**: majority of existing TSC members approve (FR-004 + FR-005).
5. **Record**: the merge commit is the audit trail. No separate minutes entry required.

## Removing a TSC member (voluntary resignation)

1. The departing member opens a PR removing their row from `TECHNICAL-STEERING-COMMITTEE.md`.
2. A non-departing TSC member approves the PR (acknowledgment, not a vote -- voluntary resignations need no vote).
3. The departing member or any TSC member merges.

## Removing a TSC member (for cause)

1. Any TSC member opens a public GitHub Issue titled `TSC: remove <Name> for cause` describing the reason (inactivity, conduct, etc.). Per D7, "inactivity" is not a fixed numeric threshold -- it's a discretionary judgment captured in the issue body.
2. The same member (or another) opens a PR removing the affected member's row from `TECHNICAL-STEERING-COMMITTEE.md`, linking the issue.
3. **Approval threshold**: majority of the *other* current TSC members (the member under review does not vote on their own removal), per FR-006.
4. Once the threshold is met, merge. The merge commit + the linked issue form the audit trail.

**Note on the two-member regime**: while the TSC has only two members, "majority of the other members" means a majority of one. The remaining member alone can effect a removal. This is a known transitional posture (see spec edge case "Removal-for-cause in a two-member TSC") and is one reason to prioritize recruiting a third member.

## Amending the charter

1. Open a PR modifying `CHARTER.md` (or `TECHNICAL-STEERING-COMMITTEE.md` for roster format changes, though those typically don't require an amendment vote).
2. Open a companion GitHub Issue titled `Charter amendment: <one-line summary>` with the rationale and a link to the PR. Announce the proposal on community channels (mailing list, Slack) per the LF template's transparency obligation.
3. **Approval threshold**: two-thirds of the *entire* TSC (not just attendees), per FR-004 and FR-010. Recorded as PR approvals on `CHARTER.md`.
4. After the threshold is met, allow a brief comment window (>= a few days is typical; the LF template does not mandate an exact length) before merging, so the community has time to weigh in.
5. Merge.

## Recording a TSC decision that doesn't modify a file

For decisions like "endorse external statement X" or "appoint <name> as representative to <foundation working group>":

1. Open a GitHub Issue titled `TSC decision: <summary>` with the proposal in the body.
2. TSC members comment with `+1`, `-1`, or `+0` on a single comment line each (so the votes are unambiguous to a casual reader and parseable by tooling). Per FR-013, this is the canonical record.
3. Apply the relevant voting threshold (ordinary majority unless the decision is an amendment or license exception).
4. Once the threshold is met, the issue is closed with a closing comment naming the outcome. The closed issue is the audit trail.

## Sanity check before submitting any governance PR

- [ ] Only one file is being modified (roster change) OR the change is clearly a charter-amendment-class change.
- [ ] The PR description names the relevant charter section/FR governing this change.
- [ ] If the change affects the roster, every row still has all four required columns populated.
- [ ] If the change affects voting thresholds in the charter narrative, the Voting section was updated to match (SC-005).
- [ ] The relevant GitHub Issue (for non-file decisions) is linked in the PR description.
