# Feature Specification: Conservative-by-default verdict correctness

**Feature Branch**: `019-verdict-correctness`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "342 and 343" (Fix issues #342 and #343: OSPS-LE-01.01 miscategorized as Level 1, and branch-protection 404 returning WARN instead of FAIL)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Level 1 audit does not over-scope (Priority: P1)

An operator running `darnit audit --level 1` against their repository expects to be evaluated only against the controls the OSPS Baseline defines as Level 1. Today the audit includes `OSPS-LE-01.01` (DCO / commit sign-off), which OSPS Baseline v2025.10.10 places at Level 2. Fixing this restores parity with the upstream spec and with darnit's own documentation.

**Why this priority**: The framework's compliance verdict must match the specification it claims to implement. Over-scoping a Level 1 audit produces false negatives (a repo shown as non-compliant with L1 for a control the spec does not require at that level). Users cannot trust the level filter until this is corrected.

**Independent Test**: Run `darnit audit --level 1` (or programmatically enumerate the L1 control set) against any repository, then compare the resulting control identifiers to the OSPS Baseline v2025.10.10 applicability filter. The counts must be L1=24, L2=18, L3=20 and `OSPS-LE-01.01` must NOT appear at Level 1.

**Acceptance Scenarios**:

1. **Given** the framework config is loaded with OSPS Baseline v2025.10.10, **When** the user requests the Level 1 control set, **Then** the set contains exactly 24 controls and does not include `OSPS-LE-01.01`.
2. **Given** OSPS Baseline v2025.10.10 assigns `OSPS-LE-01.01` to `[maturity-2, maturity-3]`, **When** the user requests the Level 2 control set, **Then** `OSPS-LE-01.01` is present.
3. **Given** the maintainer is verifying the framework's fidelity to upstream, **When** a spec-sync regression test runs, **Then** per-level counts must match the OSPS Baseline for the pinned spec version, and any drift fails CI with a diff of the mismatched controls.

---

### User Story 2 - Definitive "not protected" is reported as failing (Priority: P1)

An operator running a live audit against a repository whose default branch has no branch protection expects the branch-protection controls to be reported as FAIL. Today they are reported as WARN ("could not automatically verify"), which under the framework's conservative-by-default rules still counts against compliance but obscures the fact that darnit has a definitive answer.

**Why this priority**: WARN semantically means "the framework does not know." Emitting WARN when the framework does know (the GitHub API returned a definitive "Branch not protected" response) trains users to distrust WARN, blurs the compliance report, and hides an actionable finding. This is a straight verdict-correctness bug against the constitution's "err on the side of caution" principle: when we have a definitive negative, we must state it.

**Independent Test**: Point a live audit at a repository whose default branch has no branch protection (or configure a test repo with no protection) with authenticated GitHub access, then observe the verdicts for `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`. All four must be FAIL, not WARN.

**Acceptance Scenarios**:

1. **Given** a repository whose default branch has no branch protection and the framework has authenticated access to the GitHub API, **When** any branch-protection control runs, **Then** the control resolves as FAIL with a reason stating the branch is not protected.
2. **Given** the same repository but the framework cannot reach the GitHub API (network error, rate-limit exhaustion, or unauthenticated request), **When** any branch-protection control runs, **Then** the control resolves as WARN (unchanged from today) because the answer is genuinely unknown.
3. **Given** a repository whose default branch IS protected but with weak settings, **When** a branch-protection control runs, **Then** the control's normal per-setting evaluation applies (unchanged; this spec does not change how a 200 response is graded).

---

### Edge Cases

- What happens when the upstream OSPS Baseline is updated to a new spec version (e.g., v2026.x) that reclassifies `OSPS-LE-01.01` again? The regression test must be keyed to the pinned spec version (`spec_version` in the framework config), not to hard-coded counts. A future spec bump is a separate task that updates both the pin and the expected counts together.
- What happens when the branch-protection API returns a 4xx that is NOT the specific "Branch not protected" 404 (e.g., 403 permission denied, 401 unauthenticated, 404 with a different body such as "Not Found")? The response is not definitive; the control remains WARN. This spec only changes the specific 404 + "Branch not protected" body signal.
- What happens when a branch other than the default is queried and returns "Branch not protected"? Same rule applies: the response is definitive for that branch and resolves FAIL.
- What happens for controls outside the branch-protection family that today return WARN on a definitive negative? Out of scope for this spec. The pattern may apply elsewhere and can be lifted into a follow-up if identified, but this spec is bounded to the four branch-protection controls named in issue #343.
- What happens when a user has customized `openssf-baseline.toml` locally? The framework does not distinguish local customization from ship-default; the level assignment is read as-is. Users who override intentionally will not be affected by the shipped regression test unless they run it against their own config.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The framework MUST classify `OSPS-LE-01.01` at Level 2 (matching OSPS Baseline v2025.10.10's `applicability: [maturity-2, maturity-3]`), so that it is excluded from Level 1 audits and included in Level 2 audits.
- **FR-002**: For OSPS Baseline v2025.10.10, the framework's per-level control counts MUST equal Level 1 = 24, Level 2 = 18, Level 3 = 20 (the values documented in `docs/USAGE_GUIDE.md`).
- **FR-003**: The framework MUST include an automated regression check that fails when per-level control counts diverge from the upstream OSPS Baseline for the pinned `spec_version`. The check must identify which controls are misclassified so the diff is actionable.
- **FR-004**: When a branch-protection control receives a definitive "not protected" response from the GitHub API (HTTP 404 with body indicating the branch is not protected), the control MUST resolve to FAIL, not WARN, with a reason that states the branch is unprotected.
- **FR-005**: FAIL and WARN verdict semantics MUST be preserved: a WARN result must continue to mean "the framework could not determine compliance" (network failure, missing authentication, ambiguous API response). This spec strengthens FAIL by removing one class of false WARN; it does not weaken WARN by folding in ambiguous cases.
- **FR-006**: The change in FR-004 MUST apply to at minimum the four branch-protection controls named in issue #343: `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`. Any control that queries `/repos/{owner}/{repo}/branches/{branch}/protection` and interprets the response should benefit from the same signal, but the acceptance bar is these four.
- **FR-007**: Documentation is not required to change: `docs/USAGE_GUIDE.md` already states the correct 24/18/20 split, so the TOML fix restores consistency. For User Story 2, no new user-facing docs are required; the verdict change is observable in existing audit output.

### Key Entities

- **OSPS Control**: a unit of compliance verification identified by an OSPS identifier (e.g., `OSPS-LE-01.01`). Carries a level assignment and applicability that must match the upstream OSPS Baseline for the pinned spec version.
- **Control verdict**: the four-valued outcome of running a control: PASS (verified compliant), FAIL (verified non-compliant), WARN (could not determine), ERROR (framework or handler failure). This spec sharpens the boundary between FAIL and WARN for one class of API response.
- **Upstream OSPS Baseline**: the authoritative external specification (currently v2025.10.10 as pinned in the framework config) whose control-to-level mapping the framework's TOML must mirror.
- **GitHub branch-protection API response**: the input signal used by branch-protection controls. This spec treats one specific response (HTTP 404 + "Branch not protected" body) as a definitive negative rather than an ambiguous one.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For OSPS Baseline v2025.10.10, per-level control counts equal 24 / 18 / 20, matching the upstream spec and darnit's existing user documentation.
- **SC-002**: A live audit against a repository whose default branch has no branch protection reports FAIL (not WARN) for all four named branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`).
- **SC-003**: The audit regression test suite includes a check that fails CI when the framework's per-level counts drift from the upstream OSPS Baseline for the pinned spec version, and the check's failure output identifies the misclassified control identifiers.
- **SC-004**: No previously-passing control regresses. For branch-protection controls specifically: any API response other than the "definitive not protected" signal continues to produce the same verdict it produces today (no ambiguous or 200-response case flips from WARN or PASS to FAIL).
- **SC-005**: A user reading an audit report can distinguish "we know this fails" from "we could not verify" without consulting external documentation; WARN means "unknown" and FAIL means "known non-compliant."

## Assumptions

- The framework's pinned OSPS spec version stays at `OSPS v2025.10.10` (`openssf-baseline.toml:12`) for this work. If the upstream spec bumps during implementation, that is a separate spec-sync task that updates both the pin and the expected per-level counts together.
- The regression test consults the upstream OSPS Baseline as its source of truth. The mechanism (fetched at test time, vendored fixture, or existing CNCF drift check hooks) is an implementation decision left to planning; the requirement is that the check is automated and CI-blocking.
- The "definitive not protected" signal is the specific combination of HTTP status 404 and a response body indicating the branch is not protected. Other 4xx responses (401, 403) and other 404 bodies remain ambiguous and continue to produce WARN.
- The change to branch-protection controls does not alter their behavior when the branch IS protected. Existing per-setting evaluation for a 200 response is unchanged.
- Issues #342 and #343 are bundled in this spec because they share the same theme (conservative-by-default verdict correctness) but they are independent implementation targets and are expected to ship as separate PRs. The bundling is spec-level only; either can be implemented and merged without the other.
- Constitution reference: this work strengthens Principle II (Conservative-by-default). WARN counts the same as FAIL for compliance math today; this spec does not change that math, only the reported label.
