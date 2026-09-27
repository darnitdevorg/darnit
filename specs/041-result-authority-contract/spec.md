# Feature Specification: Result and Authority Contract

**Feature Branch**: `041-result-authority-contract`

**Created**: 2026-09-27

**Status**: Draft

**Input**: User description: "Result and authority contract (RFC-0001 September 2026 revision, 'Authority is per claim, not per handler' and 'Result model'). Each verification step declares which outcomes it may conclude for its control; presence and pattern steps may conclude FAIL but not PASS unless the requirement is literally about existence; an LLM step never concludes PASS on its own; ERROR is a broken measurement, never FAIL; authority can be earned against an adversarial fixture corpus."

## Background

A control is verified by an ordered list of steps (passes). Today, whether a step's result settles the control is decided by the kind of step: a file-presence check and a keyword match are both treated as proof. That makes controls about document *content* pass on weak evidence -- a README that says only "TODO" passes a documentation control, and a security policy that says the project has no process passes a disclosure control -- while a model's judgment, even when it is the only step that reads the content, can never change the verdict. Platform and API failures are also reported as failures of the project rather than as broken measurements.

The RFC-0001 September 2026 revision replaces this with a per-claim rule: what a step may conclude depends on what it proves about the specific control. This feature implements that rule, a result model that separates "the project fails" from "we could not measure", a human-confirmed path for model judgments, and a corpus of adversarial fixture repositories that measures each step and gates when a step may conclude PASS.

Constitution alignment: Principle II (Conservative-by-Default) -- unverified, errored, and pending results never count as compliant; Principle V (Sieve Pipeline Integrity) -- steps still run in order and the first conclusive result wins, but "conclusive" now depends on the step's declared authority for that outcome.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Weak evidence can no longer produce a PASS (Priority: P1)

A maintainer audits a repository whose documentation and policy files exist but are placeholders. They expect darnit to say those controls need verification or fail, not that they pass.

**Why this priority**: False PASS results are the most damaging error a compliance tool can make, and the evaluation found them on common repositories.

**Independent Test**: Audit fixture repositories whose README contains only "TODO" and whose SECURITY.md states there is no security policy; confirm the related controls are not PASS, and confirm that a repository missing those files entirely still FAILs.

**Acceptance Scenarios**:

1. **Given** a control about document content whose steps are a presence check then a keyword match, **When** the document exists and contains the keyword, **Then** the control is not concluded PASS by those steps; it is WARN (needs verification) or pending a judgment.
2. **Given** the same control, **When** the document is missing, **Then** the control is FAIL (absence is proven).
3. **Given** a control whose requirement is literally that a file exists, **When** the file exists, **Then** the control may be concluded PASS by the presence step.
4. **Given** a keyword step that finds no match, **When** it has not declared that a miss proves failure, **Then** its result is inconclusive and evaluation continues to the next step.

---

### User Story 2 - Broken measurements are reported as errors, not failures (Priority: P1)

An operator runs darnit with a token that cannot read some settings, or while the platform API is rate-limited. They need to see which controls could not be measured, not a list of false failures.

**Why this priority**: Reporting "API unavailable" as "the project fails" misleads maintainers and makes fleet runs with token or rate-limit problems look like mass regressions.

**Independent Test**: Audit a repository with the platform API returning not-found, forbidden, and rate-limit responses, and with the command-line tool absent; confirm affected controls are ERROR with the cause, and that the level is not compliant.

**Acceptance Scenarios**:

1. **Given** a step that calls the platform API, **When** the API responds with an authorization or rate-limit error, **Then** the step's result is ERROR with the cause, and evaluation does not conclude FAIL from it.
2. **Given** a step that calls the platform API, **When** the response is a genuine "does not exist" that the step declares as proving failure (for example no branch protection), **Then** the step may conclude FAIL.
3. **Given** a required tool is not installed, **When** the step runs, **Then** its result is ERROR naming the missing tool.
4. **Given** any control ends ERROR, **When** level compliance is computed, **Then** the level is not compliant.

---

### User Story 3 - Model judgments become PASS candidates that a person confirms (Priority: P1)

For controls that genuinely need judgment (does this document describe a disclosure process?), a model reads the gathered evidence. The operator wants the model to do that work, but never to be the only reason a control is reported as passing.

**Why this priority**: This is how the model tier becomes useful without being able to manufacture a compliance claim, and it closes the path where a coding agent decides a verdict itself.

**Independent Test**: Run a control whose only content-reading step is a model judgment; confirm a positive judgment yields a PASS candidate that counts as non-compliant until confirmed, that confirming it yields PASS labelled as asserted, and that a negative judgment yields a non-compliant result.

**Acceptance Scenarios**:

1. **Given** a model judgment that the evidence satisfies the control, **When** the audit completes, **Then** the control is reported as a PASS candidate, counts as non-compliant, and shows the judgment's reasoning and cited evidence.
2. **Given** a PASS candidate, **When** the operator confirms it through the confirmation flow, **Then** later audits report PASS with authority "asserted", the confirmer, and the time, until the evidence changes or the confirmation expires.
3. **Given** a model judgment that the evidence does not satisfy the control, **When** the audit completes, **Then** the control is non-compliant and labelled as a model finding.
4. **Given** a coding agent connected over MCP supplies a judgment for a pending control, **When** it is submitted, **Then** it is treated exactly like a model judgment from the headless harness: at most a PASS candidate, never a PASS.

---

### User Story 4 - A corpus of adversarial fixtures measures every step (Priority: P2)

A maintainer changing a check wants to know whether it can be fooled. A corpus of small repositories with labelled expected outcomes runs every step and reports, per step and per outcome, how often it was right.

**Why this priority**: Without measurement, "this check is reliable enough to conclude PASS" is an opinion. The corpus turns it into a recorded fact and is the acceptance gate for this feature.

**Independent Test**: Run the corpus against the Baseline controls and confirm the report lists each step's true and false results per outcome, and that the corpus run fails if any step allowed to conclude PASS produces a false PASS.

**Acceptance Scenarios**:

1. **Given** the corpus, **When** it runs, **Then** it reports for every step and outcome the number of correct and incorrect conclusions against the labels.
2. **Given** a step recorded as allowed to conclude PASS, **When** it produces any false PASS on the corpus, **Then** the corpus run fails and names the step and fixture.
3. **Given** a step not yet allowed to conclude PASS, **When** it has produced zero false PASS results on the corpus, **Then** the report marks it eligible, and a maintainer may record the promotion in the framework configuration where it is reviewable.
4. **Given** a new fixture is added with its labels, **When** the corpus runs, **Then** every step is measured against it without code changes.

---

### User Story 5 - The Baseline implementation follows the new rules (Priority: P2)

Maintainers of the OpenSSF Baseline implementation re-declare each control's steps under the new rules so audits of real repositories reflect them.

**Why this priority**: The rules only help once the shipped controls use them.

**Independent Test**: Audit the corpus and two real repositories before and after re-declaration; confirm no control concludes PASS from a step not allowed to, and that the before/after differences are all explained by the new rules.

**Acceptance Scenarios**:

1. **Given** the re-declared Baseline controls, **When** the corpus runs, **Then** there are zero false PASS results.
2. **Given** a real repository audited before and after, **When** results are compared, **Then** every change is attributable to a presence/keyword step no longer concluding PASS, a miss becoming inconclusive, a failure becoming ERROR, or a model judgment becoming a PASS candidate.

### Edge Cases

- A step declares it may conclude an outcome its step type cannot support (for example a keyword step declaring it may conclude PASS for a content control without a recorded promotion): configuration validation rejects it.
- A control has no step allowed to conclude PASS: the control can end PASS only through a confirmed candidate; otherwise WARN.
- A model judgment cites evidence that does not appear in the gathered content: the judgment is recorded but does not produce a PASS candidate.
- The model service is unavailable: the control is ERROR (for the model step) or pending, never FAIL.
- A confirmed PASS candidate's evidence changes: the confirmation lapses and the control returns to PASS candidate after a new judgment, or WARN without one.
- A platform response is ambiguous between "not found" and "not permitted to see": treated as ERROR unless the step declares otherwise.
- A step's promotion is recorded but the corpus later gains a fixture that fools it: the corpus run fails until the promotion is removed or the step is fixed.
- Deterministic-only test runs (issue #505) leave judgment-requiring controls pending and never report a level compliant.

## Requirements *(mandatory)*

### Functional Requirements

**Per-claim authority**

- **FR-001**: Every step type MUST declare the outcomes it can at most conclude (its ceiling). Presence and pattern step types MUST have a ceiling of FAIL only, except where a step is declared as verifying a requirement that is literally about existence.
- **FR-002**: Each step in a control MAY narrow, but never widen, its type's ceiling by declaring the outcomes it may conclude for that control. Configuration that widens a ceiling without a recorded promotion (FR-020) MUST be rejected when the framework configuration is loaded.
- **FR-003**: A step result for an outcome the step may not conclude MUST be treated as evidence only, and evaluation MUST continue to the next step.
- **FR-004**: A pattern step that finds no match MUST produce an inconclusive result unless the step declares that a miss proves failure.
- **FR-005**: When no step concludes, the control MUST be WARN (needs verification), carrying the evidence gathered (existing behavior preserved).

**Result model**

- **FR-006**: Results MUST distinguish PASS, FAIL, WARN, N/A, ERROR, and PENDING (awaiting a model judgment or a confirmation), and a PASS candidate MUST be distinguishable from PASS.
- **FR-007**: ERROR MUST be used for broken measurements -- platform or API errors (authorization, rate limit, unavailable), missing tools, and evaluation errors -- and MUST record the cause. ERROR MUST NOT be reported as FAIL.
- **FR-008**: A step MAY declare specific platform responses as proving failure (for example "no branch protection configured"); only those responses may conclude FAIL.
- **FR-009**: Level compliance MUST be computed in one place for every driver and output, and a level MUST NOT be compliant if any control at that level is FAIL, WARN, ERROR, PENDING, or a PASS candidate.

**Model judgments**

- **FR-010**: A model judgment MUST NOT conclude PASS. A positive judgment MUST produce a PASS candidate carrying the judgment's reasoning, the evidence it cited, the model and version, and a digest of the evidence it was given.
- **FR-011**: A PASS candidate MUST count as non-compliant until an operator confirms it; a confirmation MUST be recorded operator-side (reusing the confirmation mechanism from feature 040) with the confirmer, time, evidence digest, and expiry.
- **FR-012**: A confirmed PASS candidate MUST be reported as PASS with authority "asserted", the confirmer, and the time; it MUST lapse when the evidence digest changes or the confirmation expires.
- **FR-013**: A negative model judgment MUST produce a non-compliant result labelled as a model finding.
- **FR-014**: A judgment MUST NOT produce a PASS candidate when it cites evidence that is not present in the content it was given.
- **FR-015**: Judgments supplied by a coding agent over MCP MUST be submitted through a tool that applies FR-010 to FR-014; no driver may record a verdict for a judgment-requiring control by any other path. Agent skills MUST NOT instruct the agent to decide verdicts itself.

**Adversarial fixture corpus**

- **FR-016**: The project MUST include a corpus of small fixture repositories, each with human-labelled expected outcomes per control, covering at least: placeholder README, a security policy that denies having a process, a workflow granting write-all permissions, placeholder governance and maintainer files, and missing files for each document control.
- **FR-017**: A corpus run MUST report, for every step and outcome, the counts of correct and incorrect conclusions against the labels.
- **FR-018**: A corpus run MUST fail if any step allowed to conclude PASS produces a false PASS, naming the step and fixture.
- **FR-019**: Adding a fixture MUST require only the fixture files and its labels.
- **FR-020**: Permission for a step to conclude PASS beyond its type's ceiling (a promotion) MUST be recorded in the framework configuration per step and outcome, MUST reference the corpus measurement that justified it, and MUST be reviewable in the configuration diff. A step is eligible only with zero false PASS results on the corpus.

**Baseline implementation**

- **FR-021**: Every OpenSSF Baseline control MUST be re-declared under FR-001 to FR-008, with presence and pattern steps limited to FAIL unless the requirement is literally about existence.
- **FR-022**: The Baseline controls MUST produce zero false PASS results on the corpus.

### Key Entities

- **Step ceiling**: The outcomes a step type can at most conclude.
- **Step declaration**: A step within a control, with the outcomes it may conclude (narrowing the ceiling) and any platform responses that prove failure.
- **Promotion**: A recorded permission for a step to conclude PASS beyond its ceiling, with a reference to the corpus measurement.
- **Result**: Status (PASS, FAIL, WARN, N/A, ERROR, PENDING), authority, what concluded it, evidence, and for ERROR the cause.
- **PASS candidate**: A positive model judgment awaiting confirmation: reasoning, cited evidence, model and version, evidence digest.
- **Corpus fixture**: A small repository plus labelled expected outcomes per control.
- **Corpus report**: Per step and outcome, correct and incorrect conclusions; eligibility for promotion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the adversarial corpus, the Baseline controls produce 0 false PASS results.
- **SC-002**: 100% of controls affected by platform authorization, rate-limit, or unavailability errors in the test suite are reported as ERROR with a cause, and 0% as FAIL.
- **SC-003**: 0 controls in the test suite reach PASS solely from a model judgment; every model-positive result without confirmation is a PASS candidate counted as non-compliant.
- **SC-004**: Every step in the Baseline implementation has a corpus measurement for each outcome it may conclude.
- **SC-005**: Adding a new fixture to the corpus takes a maintainer under 15 minutes and requires no code change.
- **SC-006**: Every difference in results on two real repositories before and after re-declaration is explained by one of the four rule changes in User Story 5.

## Assumptions

- The corpus lives in this repository alongside the tests; publishing it as a shared asset for other tools is a later decision (RFC-0001 open question 8).
- The initial promotion bar is zero false PASS results on the corpus; severity-dependent bars are out of scope.
- No model judgment is ever promoted to conclude PASS in this feature; PASS from a judgment always requires confirmation.
- The confirmation flow, operator configuration, and trust decisions come from feature 040, which this feature depends on.
- Improving the content given to model judgments (evidence gathering, truncation, batching) is a separate feature; this feature only fixes who may conclude what.
- Deterministic-only runs remain test tooling per issue #505.
