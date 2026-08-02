# Feature Specification: Preserve handler-conclusive FAIL through the CEL post-step

**Feature Branch**: `020-definitive-fail-verdict`

**Created**: 2026-08-01

**Status**: Draft

**Input**: User description: "us2" (implement US2 from feature 019: fix branch-protection controls returning WARN on a definitive HTTP 404 "Branch not protected" response instead of FAIL)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Definitive "not protected" is reported as failing (Priority: P1)

An operator running a live audit against a repository whose default branch has no branch protection expects the branch-protection controls to be reported as FAIL. Today they are reported as WARN ("could not automatically verify"), which under the conservative-by-default rules still counts against compliance but obscures the fact that darnit has a definitive answer.

**Why this priority**: WARN semantically means "the framework does not know." Emitting WARN when the framework does know (the GitHub API returned a definitive "Branch not protected" response, exit code 1, JSON body with `message == "Branch not protected"`) trains users to distrust WARN, blurs the compliance report, and hides an actionable finding. Framework-level fix; benefits 12 downstream controls that combine `fail_exit_codes` with `expr` (research.md R5 from feature 019). Constitutional principle II (Conservative-by-default) and V (Sieve Pipeline Integrity) both call for this correction.

**Independent Test**: Point a live audit at a repository whose default branch has no branch protection (or use the integration test's stubbed `gh api`), then observe the verdicts for `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`. All four MUST be FAIL, not WARN. The verification path is the same as feature 019 US2's `quickstart.md`.

**Acceptance Scenarios**:

1. **Given** a repository whose default branch has no branch protection and the framework has authenticated access to the GitHub API, **When** any branch-protection control runs, **Then** the control resolves as FAIL with a reason that states the branch is not protected.
2. **Given** the same repository but the framework cannot reach the GitHub API (network error, rate-limit exhaustion, or unauthenticated request), **When** any branch-protection control runs, **Then** the control resolves as WARN because the answer is genuinely unknown.
3. **Given** a repository whose default branch IS protected but with weak settings, **When** a branch-protection control runs, **Then** the control's normal per-setting evaluation applies unchanged.
4. **Given** a control (any of the 12 in scope) whose exec handler returns FAIL via `fail_exit_codes` AND whose CEL expression also evaluates falsy, **When** the sieve orchestrator runs, **Then** the control resolves as FAIL (not INCONCLUSIVE, which is today's behavior).
5. **Given** a control whose exec handler returns FAIL AND whose CEL expression evaluates truthy (the ambiguous case), **When** the sieve orchestrator runs, **Then** the control resolves as INCONCLUSIVE (was PASS today; the ambiguous case now defers).

---

### Edge Cases

- What happens when the branch-protection API returns a 4xx that is NOT the specific "Branch not protected" 404 (e.g., 403 permission denied, 401 unauthenticated, 404 with a different body such as "Not Found")? The response is not definitive; the control remains WARN. This spec only sharpens the FAIL boundary; it does not touch WARN handling.
- What happens when a branch other than the default is queried and returns "Branch not protected"? Same rule applies: the response is definitive for that branch and resolves FAIL. Any control that scopes to a non-default branch inherits this behavior.
- What happens for controls outside the branch-protection family that today return WARN on a definitive negative? The orchestrator change benefits ANY control combining `fail_exit_codes` + `expr` (11 non-branch-protection controls listed in feature 019's `research.md` R5). The acceptance bar is the four named branch-protection controls; the broader benefit is a side effect and is expected, not a regression.
- What happens when a control's exec handler returns FAIL and CEL evaluates truthy? Today: PASS. New: INCONCLUSIVE. This is the "ambiguous" cell of the transition table (handler and CEL disagree in favor of the handler's original verdict). Any existing test that relied on this PASS is exercising buggy behavior and must be updated to reflect the new (correct) semantics.
- What happens for controls that use `expr` WITHOUT `fail_exit_codes`? Unchanged. Handler PASS is the only conclusive input; PASS + truthy CEL -> PASS, PASS + falsy CEL -> INCONCLUSIVE (today's behavior, preserved).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When the sieve orchestrator's CEL post-step evaluates on a handler result of FAIL and the CEL expression returns falsy, the control MUST resolve to FAIL. (Today: INCONCLUSIVE, which is the root cause of issue #343.)
- **FR-002**: When the sieve orchestrator's CEL post-step evaluates on a handler result of FAIL and the CEL expression returns truthy (the ambiguous case — handler and CEL disagree, with the handler saying fail and the CEL saying pass), the control MUST resolve to INCONCLUSIVE. (Today: PASS, which is a latent bug; see feature 019 `research.md` R5.)
- **FR-003**: Handler results of PASS with a CEL expression MUST continue to behave as today: PASS + truthy -> PASS, PASS + falsy -> INCONCLUSIVE. This spec does not alter the pass-boundary semantics.
- **FR-004**: Handler results of INCONCLUSIVE or ERROR MUST continue to pass through the CEL post-step unchanged. Same as today.
- **FR-005**: When the CEL expression is absent from a pass configuration, the handler's result MUST pass through unchanged. Same as today.
- **FR-006**: When the CEL expression evaluator raises or returns an error (not a boolean), the handler's original result MUST pass through unchanged. Same as today.
- **FR-007**: The framework's four named branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) MUST report FAIL when the GitHub API returns HTTP 404 with body containing `message == "Branch not protected"` (exit code 1 from `gh api`).
- **FR-008**: WARN semantics MUST be preserved: WARN continues to mean "the framework could not determine compliance" (network failure, missing authentication, ambiguous API response). This spec strengthens FAIL by removing one class of false WARN; it does not weaken WARN.
- **FR-009**: The change MUST NOT alter the behavior of any control that today returns PASS on a healthy branch-protection response (200 with expected fields). Regression coverage required.

### Key Entities

- **`PassOutcome`** (framework, `packages/darnit/src/darnit/sieve/models.py`): the four-valued enum (PASS / FAIL / INCONCLUSIVE / ERROR). Unchanged by this spec; only the transitions between them shift.
- **`HandlerResult`** (framework): the handler's return value carrying `status`, `message`, `confidence`, and `evidence`. `evidence` is the input to CEL evaluation. Unchanged.
- **CEL post-step** (framework, `packages/darnit/src/darnit/sieve/orchestrator.py:60-75`): the transformation this spec modifies. Documented as a contract in `contracts/cel-post-step.md` (lifted from feature 019).
- **Twelve affected controls** in `packages/darnit-baseline/openssf-baseline.toml` (from feature 019 `research.md` R5): `OSPS-AC-01.01`, `OSPS-AC-02.01`, `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-BR-03.01`, `OSPS-GV-02.01`, `OSPS-LE-02.01`, `OSPS-QA-01.01`, `OSPS-QA-03.01`, `OSPS-QA-07.01`, `OSPS-VM-03.01`, `OSPS-VM-04.01`. Acceptance bar is the four named branch-protection controls; the remaining eight benefit automatically.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A live audit against a repository whose default branch has no branch protection reports FAIL (not WARN) for all four named branch-protection controls.
- **SC-002**: The full eight-cell CEL post-step transition table is covered by unit tests, with the two new-behavior cells (H=FAIL+CEL=truthy -> INCONCLUSIVE, H=FAIL+CEL=falsy -> FAIL) explicitly asserted.
- **SC-003**: No control that today returns PASS on a healthy input changes verdict. The regression sweep runs all pre-existing tests and none fail unrelated to the transition-table change (any that fail are documented as testing buggy behavior).
- **SC-004**: An audit report reader can distinguish "we know this fails" (FAIL) from "we could not verify" (WARN) for the four named branch-protection controls without consulting external documentation.
- **SC-005**: The nondeterministic verification path (running the audit via the darnit MCP server + a coding-agent client) produces the same qualitative story for the four named controls as the deterministic unit tests.

## Assumptions

- Constitutional reference: this work strengthens Principle II (Conservative-by-default) and clarifies Principle V (Sieve Pipeline Integrity, "orchestrator stops at first conclusive result"). Today's CEL post-step arguably violates V by demoting a handler-conclusive FAIL to INCONCLUSIVE.
- WARN vs FAIL semantics: WARN counts the same as FAIL for compliance math today; this spec does not change that math, only the reported label. Users reading reports get sharper information.
- Feature 019 US1 (issue #342) has already shipped as PR #349. This spec is the second half of that feature bundle, lifted into its own feature per the "one PR per feature" pattern that emerged during US1's implementation.
- The regression risk audit and mitigations from feature 019 `research.md` R5 remain valid; the twelve controls listed there are the correct scope of "affected by this change."
- Definitive "not protected" signal: HTTP status 404 AND body containing `message == "Branch not protected"`. Other 4xx / other 404 bodies remain ambiguous (WARN).
- Testing framing: the deterministic verification (unit tests, integration tests with stubbed `gh api`) is necessary but not sufficient. The audit skills (`/darnit-audit` invoking `darnit serve` + MCP client) exercise the LLM-mediated path and are the actual product test.
- The relevant contracts and research are already written under `specs/019-verdict-correctness/`. This feature's planning phase should lift and adapt those artifacts rather than rewriting them.
