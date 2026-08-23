# Feature Specification: Ruleset-aware branch-protection verdict

**Feature Branch**: `032-ruleset-branch-protection`

**Created**: 2026-08-22

**Status**: Draft

**Input**: Consult GitHub Repository Rulesets when the classic branch-protection API returns 404, so branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) do not produce false FAILs for repos protected via rulesets instead of classic branch protection. Follow-up to feature 019 raised by @justaugustus on issue #343.

## Clarifications

### Session 2026-08-22

- Q: When do we consult the rulesets endpoint? -> A: Whenever the classic surface did not itself provide the specific required protection (classic 404 OR classic 200 that lacks the required signal). Enables cross-surface layering (e.g., classic requires PRs, ruleset adds required status checks) without paying the always-parallel API cost.
- Q: How does the handler distinguish HTTP status codes for the WARN-vs-FAIL boundary? -> A: Extend the shared `gh_api` helper (or add a sibling) to surface HTTP status metadata, parsed from `gh`'s stderr on non-zero exit ("HTTP <code>:" prefix). Single transport preserved across the codebase; the helper enhancement is scoped and reusable by other controls that face the same distinction.
- Q: What happens when a repo has more rulesets than fit on GitHub's default page? -> A: Use `gh api --paginate` to fetch all rulesets; if fetching any page fails, verdict is WARN. Removes the truncation risk from v0 rather than deferring it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Repo protected via a repository ruleset is reported as compliant (Priority: P1)

An operator running a live audit against a repository whose default branch is protected exclusively via a GitHub Repository Ruleset (not classic branch protection) expects the four branch-protection controls to reflect the ruleset-based protection. Today all four resolve to FAIL because the classic protection endpoint 404s and the sieve treats that 404 as definitive absence.

**Why this priority**: This is a Constitution II violation in the direction that matters most for a compliance tool. Reporting FAIL on a repo that is genuinely compliant erodes trust in the audit's verdict and, in a fleet setting, creates blocking dashboard alerts that require every maintainer to manually reclassify. The fix restores parity between what the tool reports and what GitHub actually enforces.

**Independent Test**: Point a live audit at a repository whose default branch has (a) no classic branch protection configured and (b) an active repository ruleset targeting the default branch that carries the equivalent protections. Observe the four affected controls resolve PASS.

**Acceptance Scenarios**:

1. **Given** a repository whose default branch is covered by an active repository ruleset that requires pull requests before merging, **When** `OSPS-AC-03.01` runs against it, **Then** the control resolves PASS with a reason that names the ruleset as the source of protection.
2. **Given** a repository whose default branch is covered by an active ruleset that blocks branch deletion, **When** `OSPS-AC-03.02` runs against it, **Then** the control resolves PASS naming the ruleset.
3. **Given** a repository whose default branch is covered by an active ruleset that requires status checks, **When** `OSPS-QA-03.01` runs against it, **Then** the control resolves PASS naming the ruleset.
4. **Given** a repository whose default branch is covered by an active ruleset that requires at least one pull-request approval, **When** `OSPS-QA-07.01` runs against it, **Then** the control resolves PASS naming the ruleset.

---

### User Story 2 - Repo with no protection at either surface still FAILs cleanly (Priority: P1)

An operator running a live audit against a repository whose default branch has no classic branch protection AND no active repository rulesets expects the four branch-protection controls to resolve FAIL. Feature 019 shipped this verdict for the classic-only case, and it must be preserved once the ruleset check is added.

**Why this priority**: The correctness gained by User Story 1 must not weaken the FAIL semantics for genuinely non-compliant repositories. A false PASS is strictly worse than a false FAIL per constitutional principle II.

**Independent Test**: Point a live audit at a repository whose default branch has no classic branch protection AND `GET /repos/{owner}/{repo}/rulesets` returns an empty list. All four controls must resolve FAIL with a reason stating that no protection was found via either surface.

**Acceptance Scenarios**:

1. **Given** a repository with no classic branch protection and an empty rulesets list, **When** any of the four branch-protection controls runs, **Then** the control resolves FAIL with a message identifying both surfaces as checked.
2. **Given** a repository with no classic branch protection and one ruleset whose enforcement mode is not `active` (for example `evaluate` or `disabled`), **When** any of the four controls runs, **Then** the control resolves FAIL because non-active rulesets do not enforce protection.
3. **Given** a repository with no classic branch protection and one active ruleset whose conditions exclude the audited branch, **When** any of the four controls runs, **Then** the control resolves FAIL because no active ruleset covers the branch.

---

### User Story 3 - Ambiguous responses continue to resolve WARN (Priority: P2)

An operator whose audit environment cannot cleanly reach GitHub's API (insufficient token permissions, rate limit exhausted, transient network failure) expects branch-protection controls to resolve WARN, not FAIL. Feature 019 preserved this semantic for the classic endpoint; it must extend to the rulesets endpoint.

**Why this priority**: Constitution II again: "when in doubt, WARN." Confusing "I could not tell" with "definitely fails" reintroduces the exact class of misdiagnosis that motivated the original 019 fix, just at a different code path.

**Independent Test**: Simulate a `403 Forbidden` response to the rulesets endpoint (or an authenticated request without `admin:read` scope). Observe the four controls resolve WARN with a reason identifying which surface produced the ambiguous response.

**Acceptance Scenarios**:

1. **Given** the classic protection endpoint returns 200 with insufficient signal AND the rulesets endpoint returns 403, **When** any of the four controls runs, **Then** it resolves WARN with a reason naming the rulesets access failure.
2. **Given** the classic protection endpoint returns 404 AND the rulesets endpoint times out or returns 5xx, **When** any of the four controls runs, **Then** it resolves WARN with a reason naming the rulesets fetch failure.
3. **Given** the classic protection endpoint returns 404 AND the rulesets endpoint returns 200 with a non-empty list, but fetching an individual ruleset's detail 404s (ruleset was deleted between calls), **When** any of the four controls runs, **Then** it resolves WARN with a reason naming the detail-fetch failure. WARN is chosen over FAIL because the framework could not fully enumerate the protection surface.

---

### Edge Cases

- **Both surfaces confirm protection**: repo has BOTH classic branch protection AND an active ruleset covering the branch, either alone would satisfy the requirement. The control resolves PASS from whichever surface is checked first (classic, per priority order); the evidence record includes a note that both surfaces are configured.
- **Multiple active rulesets, only one matches**: the requirement is satisfied if ANY single active ruleset covering the branch carries the required rule. The evidence records the specific ruleset by name and id.
- **Ruleset targets the branch but with a differently-parameterized rule**: for example a `pull_request` rule with `required_approving_review_count = 0` for `OSPS-QA-07.01` (which needs at least 1). The ruleset targets the branch but does not satisfy the requirement's parameter; the framework treats this as "did not find satisfying protection here" and continues its evaluation (which, if nothing else satisfies, resolves FAIL).
- **Ref-name conditions**: an active ruleset covers the audited branch when its `conditions.ref_name.include` contains one of: `~DEFAULT_BRANCH` (matched only if the audited branch equals the repository's default branch), the exact branch name, or the git-ref form `refs/heads/{branch}`. Wildcard/glob patterns in `include` MAY match but v0 does not evaluate them (they are treated as "does not match" and are reported in the evidence for the user to inspect).
- **`conditions.ref_name.exclude` present**: if a ruleset's `include` matches the branch but `exclude` also matches, the branch is not covered by that ruleset. The framework treats it the same as if the include did not match.
- **Rulesets fetched but empty rules array**: an active ruleset covering the branch exists but declares no rules. It cannot satisfy any requirement; treated as "does not satisfy" for every requirement.
- **Rate limit exhausted mid-check**: if the rulesets list endpoint succeeds but a per-ruleset detail fetch is 429-rate-limited, verdict is WARN, matching the constitution's err-on-caution principle.
- **Repository has more rulesets than the default page size**: v0 uses `gh api --paginate` and enumerates every page. If any page's fetch fails mid-pagination, the verdict is WARN with source `partial-fetch` (per FR-018), not silent truncation.
- **Non-GitHub platforms**: unchanged. The four affected controls already carry `when = { platform = "github" }`, which excludes them from non-GitHub audits.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The framework MUST consult the GitHub Repository Rulesets API surface as a secondary source of branch-protection evidence for the four affected controls: `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`.
- **FR-002**: When the classic branch-protection API returns a positive signal for the specific required protection (200 response whose body carries the exact field/parameter the control tests for), the framework MUST resolve the control PASS from that surface without consulting rulesets (existing behavior; consulted-surface documented in the evidence record).
- **FR-003**: When the classic branch-protection API returns 404 (branch not protected via classic) OR returns 200 without the specific required signal (branch is protected via classic, but not for this control's requirement), the framework MUST consult the rulesets API before concluding a verdict. This preserves cross-surface layering: for example, a repo whose classic protection requires pull requests but leaves required status checks to a ruleset must PASS `OSPS-QA-03.01` via the ruleset, not FAIL because classic alone did not carry the status-checks signal.
- **FR-004**: An active repository ruleset satisfies a requirement iff (a) its `enforcement` field equals `active`, AND (b) its `conditions.ref_name.include` covers the audited branch by one of the matching modes named in Edge Cases, AND (c) its rules list contains at least one rule of the specific type (and parameter, where applicable) required by the control being evaluated.
- **FR-005**: The framework MUST resolve a control FAIL only when BOTH the classic surface AND the rulesets surface respond successfully AND neither provides the required protection.
- **FR-006**: The framework MUST resolve a control WARN when EITHER surface's response is ambiguous or unreachable (network error, authentication error, 5xx, rate-limit, or a partial fetch failure such as list-succeeds-but-detail-fails).
- **FR-007**: The four affected TOML controls MUST be updated to invoke the ruleset-aware verdict logic INSTEAD of the current classic-only exec pass. The manual verification pass at the end of each control's pass list remains unchanged.
- **FR-008**: The evidence record for a control resolved via this feature MUST identify which surface produced the verdict (classic, ruleset, or "neither"), and, when the ruleset surface was consulted, MUST include the name and id of the ruleset that produced the verdict (or, on FAIL, MUST include the summary list of active rulesets that were considered and rejected).
- **FR-009**: The requirement-to-ruleset-rule mapping MUST be:
  - `OSPS-AC-03.01` (PreventDirectCommits, requires pull-request workflow): satisfied by an active ruleset covering the branch with a `pull_request` rule.
  - `OSPS-AC-03.02` (PreventBranchDeletion): satisfied by an active ruleset covering the branch with a `deletion` rule (i.e., a rule that blocks deletion of the branch).
  - `OSPS-QA-03.01` (RequiredStatusChecks): satisfied by an active ruleset covering the branch with a `required_status_checks` rule.
  - `OSPS-QA-07.01` (RequiredApprovals): satisfied by an active ruleset covering the branch with a `pull_request` rule whose parameters include `required_approving_review_count >= 1`.
- **FR-010**: The framework MUST NOT change the verdict semantics of any non-branch-protection control. This feature's scope is bounded to the four named controls; no other TOML control is touched.
- **FR-011**: The feature MUST NOT alter the manual-pass fallback that terminates each of the four controls' pass lists. If the automated verdict cannot conclude (WARN), the manual pass provides the operator-facing steps for human verification, unchanged from today.
- **FR-012**: Only rulesets with `enforcement = "active"` count as protection in v0. Rulesets in `enforcement = "evaluate"` (dry-run mode) or `enforcement = "disabled"` state MUST NOT satisfy any requirement.
- **FR-013**: The feature MUST NOT introduce a new runtime dependency on any external package beyond what darnit already declares. The GitHub REST API is consumed via the shared `gh_api` helper (or a status-code-aware sibling introduced by this feature); a single GitHub transport is preserved across the codebase.
- **FR-017**: The framework MUST distinguish HTTP status classes (`200`, `404`, and "other non-200" grouped as ambiguous) when interpreting responses from either the classic or the rulesets endpoint. The shared helper enhancement introduced by this feature MUST parse `gh`'s stderr for the `HTTP <code>:` prefix on non-zero exit and expose the status code to the caller. Absent a parseable status code, the caller MUST treat the response as ambiguous and resolve WARN (FR-006).
- **FR-018**: The framework MUST enumerate ALL rulesets that target the audited branch, not just the first page of results. Implementation MUST use `gh api --paginate` (or equivalent) for the list call. If ANY page fetch fails (including mid-pagination), the verdict MUST be WARN with an evidence source of `partial-fetch`.
- **FR-014**: An audit that never runs any of the four affected controls MUST NOT pay any additional API cost from this feature (rulesets endpoint is only consulted when at least one affected control is being evaluated, and only when the classic surface did not already produce PASS).
- **FR-015**: The evidence record MUST NOT include personally-identifying data or GitHub tokens; ruleset names and ids are metadata that GitHub already exposes to any authenticated caller with `admin:read` on the repository.
- **FR-016**: The framework MUST produce an evidence record whose "source" field for the verdict is one of a fixed enumerated set (`classic`, `ruleset`, `neither-surface-provided-protection`, `insufficient-access`, `partial-fetch`) so downstream reporting can group and count verdicts by source.

### Key Entities

- **Branch-protection control**: a compliance control whose PASS/FAIL/WARN verdict depends on whether the repository's default branch (or a specifically-audited branch) is protected in one of the ways OSPS Baseline enumerates. In v0 this is the fixed set of four controls named above.
- **Classic branch protection**: the `/repos/{owner}/{repo}/branches/{branch}/protection` API surface. A repository configured through the repository settings' "Branch protection rules" page populates this surface. Historically the only protection mechanism GitHub offered.
- **Repository ruleset**: the newer protection mechanism accessible via `/repos/{owner}/{repo}/rulesets` and `/repos/{owner}/{repo}/rulesets/{id}`. Rulesets have an `enforcement` mode, a `conditions.ref_name` targeting object with `include` and `exclude` lists, and an ordered list of `rules` whose types encode the specific protections (`pull_request`, `deletion`, `required_status_checks`, `non_fast_forward`, `required_signatures`, ...).
- **Protection requirement**: a per-control declaration of what specific protection the control is testing for. Encoded as an enum value (see FR-009) that the ruleset-aware handler consumes to know which rule type/parameter to look for.
- **Verdict source**: the enumerated field in the evidence record naming which surface produced the verdict. Preserves the constitutional principle that a compliance report should say WHY it reached a conclusion, not just what the conclusion was.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A live audit against a repository protected exclusively via an active default-branch ruleset produces PASS for all four affected controls (currently produces FAIL). Verifiable end-to-end by pointing an audit at a real repository configured accordingly, or by a fixture-driven integration test that stubs the two GitHub endpoints.
- **SC-002**: A live audit against a repository with neither classic protection nor rulesets continues to produce FAIL for all four affected controls, matching feature 019's shipped behavior. Verifiable by the same test harness as SC-001 with the rulesets fixture set to empty.
- **SC-003**: When either GitHub API surface is unreachable or returns an ambiguous response, the four affected controls resolve WARN instead of FAIL. Verifiable by fault-injection tests that simulate 403/429/5xx/network-error on each surface.
- **SC-004**: An audit that includes at least one of the four affected controls issues at most `ceil(N/page_size)` `rulesets`-list calls plus at most N per-ruleset-detail calls per audit-run per repository, where N is the total count of rulesets on the repository. `page_size` is the GitHub API default (30 as of writing). Verifiable by counting API calls in a mocked-transport test; the property matters for GitHub's rate-limit budget on large fleets.
- **SC-005**: An audit that excludes all four affected controls (via `--tags` filter, `--level 1` when the control is level 2/3, or `.baseline.toml` disable) issues zero calls to the rulesets endpoint. Verifiable by a spy on the GitHub-API transport during a filtered audit.
- **SC-006**: The evidence record's `source` field carries one of the enumerated values in FR-016 for every verdict produced by this feature. Verifiable by an assertion in the four controls' unit tests.
- **SC-007**: No previously-passing branch-protection control regresses. A repository with classic branch protection but no rulesets continues to produce the exact same verdict as it did on `main` prior to this feature. Verifiable by running the four controls against a golden fixture representing the pre-feature success path.

## Assumptions

- **Authenticated `gh` CLI**: audits with these controls in scope assume the operator has `gh` authenticated with a token holding enough scope to read repository rulesets. `admin:read` (or the fine-grained equivalent `Read access to repository administration`) is the requirement. Insufficient scope produces WARN via FR-006.
- **Rulesets are queryable at the repository scope**: v0 checks only per-repository rulesets. Organization-level rulesets that a repository inherits are NOT enumerated by `/repos/{owner}/{repo}/rulesets`; they are a v0.1 follow-up (org-level API surface: `/orgs/{org}/rulesets` and per-ruleset detail).
- **All-pages enumeration**: v0 uses `gh api --paginate` for the list call so all rulesets are enumerated regardless of repository count. Rate-limit and partial-fetch failures during pagination resolve WARN per FR-018.
- **The four controls are the whole scope**: no other OSPS control's TOML pass changes as part of this feature. If future controls consult the same protection surface, they can adopt the same handler in a follow-up.
- **Manual pass unchanged**: each of the four controls retains its trailing manual-pass step. This feature changes the first (automated) pass only.
- **`when = { platform = "github" }` guard is preserved**: non-GitHub audits skip these controls entirely and this feature is invisible to them.
- **Evidence record shape is additive**: the new `source` field is added; no existing evidence field is removed or renamed. Downstream consumers that ignore unknown fields continue to work.
- **`gh` CLI is the transport**: consistent with the current classic-branch-protection pass. Feature does not introduce direct `httpx` / `requests` calls; the CLI path handles auth, pagination flags, and rate-limit backoff.
