# Feature Specification: Close Remaining False-PASS Paths

**Feature Branch**: `044-false-pass-paths`

**Created**: 2026-10-04

**Status**: Draft

**Input**: User description: "044: close remaining false-PASS paths. A compliance verdict of PASS must come only from evidence that actually establishes the requirement. Covers #479, #486, #453; lowest priority #493. Builds on 041 (per-step outcome ceilings, ERROR, corpus false-PASS gate) and 040 (operator configuration). PR #532 (rename darnit-reproducibility to darnit-amber) is open; the #453 fix should survive that rename."

## Background

Constitution Principle II: a control that has not been explicitly verified as passing is not compliant, and a false PASS is worse than a false FAIL. Feature 041 made this mechanical: each step type has a ceiling on what it may conclude, a broken measurement is ERROR rather than a verdict, and a corpus gate fails the build on a false PASS. Four paths around that contract remain:

- **A step's expression can fail and the step still passes (#479).** A check may attach an expression that must hold for the step's result to stand. When the expression cannot be evaluated, the step's own result is kept unchanged, PASS included. The expression can only see the step's output: references to project data or to an API response fail to evaluate, and the `file_exists()` function always answers false because it is never told where the repository is. Shipped exposure: OSPS-BR-01.01 and OSPS-AC-04.02 run a workflow scanner and check its findings through such an expression. If the scanner exits with an accepted code but prints no findings document, the expression cannot be evaluated and the control passes.
- **A plugin can quietly redefine a built-in check (#486).** A plugin that registers a step type with the same name as a built-in one replaces it, including what it may conclude. A plugin can therefore turn the human-review step (which concludes nothing) into one that concludes PASS. Only a debug-level message records it. Separately, framework configuration accepts any unknown key on controls and steps, so a misspelled setting (for example `fail_on_mis`) silently has no effect, and a step naming a type that is not registered is silently skipped (#481).
- **Reproducibility checks pass on text signals (#453).** The reproducibility framework's checks conclude PASS when particular strings appear in CI files. For example, provenance generation "passes" when a workflow mentions a signing tool, whether or not any provenance is produced. All five of its check types are registered as able to conclude PASS, which 041 reserves for checks that observe ground truth.
- **The auditor's profile ends up in audit output (#493).** OSPS-AC-01.01 reads the auditing user's own account to see whether two-factor authentication is on (as evidence only). The whole account record (email, location, company, biography) is stored in the result evidence, JSON output, and signed attestations.

## Clarifications

### Session 2026-10-04

- Q: Which reproducibility checks lose the ability to conclude PASS on their own? -> A: All five check types that decide from text or file-presence signals (provenance, hermetic build, bit-for-bit, dependency pinning, build environment declared). They may still conclude FAIL; PASS needs a corpus measurement (041 promotion) or a check that verifies the property itself (FR-010).
- Q: When a scanner reports a finding through an accepted exit code, should the step's expression be able to prove failure? -> A: Yes, by opt-in per step: a step field makes the expression alone decide once the command ran successfully (true is PASS, false is FAIL). The two zizmor steps (OSPS-BR-01.01, OSPS-AC-04.02) set it (FR-015).
- Q: An unreadable or unresolved `requirements.txt` include was a FAIL under feature 037 FR-007; is it still? -> A: No. It is a missing signal, not proof that dependencies are unpinned: the step decides nothing and the control ends non-compliant unless another step concludes. This supersedes 037 FR-007 for that case.
- Q: A verified Witness attestation is a cryptographic check inside the hermetic-build step type, which is now FAIL-only. -> A: Out of scope; a follow-up splits it into its own step type that may conclude PASS.
- Q: Which account endpoints count as personal records? -> A: `/user`, anything under `/user/` (for example `/user/emails`), and anything under `/users/` (FR-012).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A step's expression decides or the step is an error (Priority: P1)

A framework author attaches an expression to a step. When the expression evaluates, its value decides with the step's result as today. When it cannot be evaluated (missing data, wrong type, an unknown variable), the step is a broken measurement (ERROR), never a PASS or FAIL.

**Why this priority**: It is a live false PASS in two shipped Baseline controls and applies to every framework that uses expressions.

**Independent Test**: Run OSPS-BR-01.01 with a scanner stand-in that exits successfully but prints no findings document; confirm the control is ERROR, not PASS. Repeat with a findings document that contains a matching finding (FAIL) and one with no matching finding (PASS).

**Acceptance Scenarios**:

1. **Given** a step whose own result is PASS, **When** its expression cannot be evaluated, **Then** the step result is ERROR with an evaluation error and its cause, and the control does not pass on it.
2. **Given** a step whose own result is FAIL, **When** its expression cannot be evaluated, **Then** the step result is ERROR (a broken measurement is not proof of failure either).
3. **Given** an expression that evaluates to something other than true or false, **When** the step runs, **Then** the result is ERROR.
4. **Given** an expression referring to project data, **When** the step runs, **Then** it sees only confirmed (or concluded) project values, as every other consumer does since 042, and a reference to an unconfirmed value is an evaluation error, not a silent false.
5. **Given** an expression calling `file_exists(path)`, **When** the step runs, **Then** the answer reflects the audited repository.
6. **Given** an expression referring to data its step type never provides (for example an API response in a command step), **When** the framework loads, **Then** loading fails and names the control, the step, and the reference.

---

### User Story 2 - Built-in checks and settings cannot be silently changed (Priority: P1)

Operators rely on built-in step types behaving as documented. A plugin cannot replace one, and a misspelled or unknown setting is reported when the framework loads instead of being ignored.

**Why this priority**: Replacing a built-in step type bypasses 041's authority contract entirely, and silent no-op settings make false PASSes impossible to spot in review.

**Independent Test**: Load a plugin that registers a step type named `manual` that concludes PASS; confirm the registration is refused and reported, and a control using `manual` still concludes nothing. Load a framework file with a misspelled step setting; confirm loading fails naming the file, control, step, and key.

**Acceptance Scenarios**:

1. **Given** a plugin registering a step type whose name a built-in step type already uses, **When** plugins load, **Then** the registration is refused, the refusal is reported at warning level or above with the plugin and type names, and the built-in step type is unchanged.
2. **Given** two plugins registering the same step type name, **When** plugins load, **Then** the second registration is refused and reported, and the result does not depend on discovery order being lucky (the refusal names both plugins).
3. **Given** a framework file with a control-level key the schema does not define, **When** it loads, **Then** loading fails naming the file, control, and key.
4. **Given** a step with a key that is neither a common step setting nor declared by its step type, **When** the framework loads, **Then** loading fails naming the file, control, step, and key.
5. **Given** a plugin step type that does not declare its settings, **When** a framework using it loads, **Then** it loads, and a single warning per step type says its settings are not checked.
6. **Given** a step naming a step type that is not registered, **When** the framework loads, **Then** loading fails naming the control and type; **and if** the type belongs to a plugin that is not installed, the audit reports that control as an error naming the missing type rather than skipping the step.

---

### User Story 3 - Reproducibility controls pass only on real evidence (Priority: P2)

A team auditing reproducibility gets PASS only where a check observed what the requirement asks for. A string in a workflow file is evidence for a reviewer, not a verdict.

**Why this priority**: It is a false PASS in a shipped framework, but that framework is newer and less widely used than the Baseline.

**Independent Test**: Audit a repository whose workflow merely mentions a signing tool in a comment and produces no provenance; confirm the provenance control is not PASS and the mention appears as evidence.

**Acceptance Scenarios**:

1. **Given** a reproducibility check that matches text or file presence, **When** it finds its signals, **Then** the control is not concluded PASS by that check; the signals are carried as evidence to the later steps (model judgment or human review).
2. **Given** such a check finds none of the required signals in a way that proves the requirement is unmet, **When** it runs, **Then** it may still conclude FAIL.
3. **Given** a reproducibility check that should conclude PASS, **When** it does, **Then** that is justified by a corpus measurement recorded with the framework (041 promotion) or by a check that verifies the property itself.
4. **Given** the reproducibility framework is renamed (PR #532), **When** the rename lands, **Then** these rules still hold (they are expressed in the framework's own configuration and registration, not tied to the package name).

---

### User Story 4 - Audit output does not carry the auditor's personal data (Priority: P3)

The person running an audit should not find their email, location, or biography in the audit's JSON output or in a signed attestation about someone else's repository.

**Why this priority**: A privacy defect rather than a false verdict; the data is the auditor's own, but it is published with attestations.

**Independent Test**: Run OSPS-AC-01.01 with a recorded account response that includes email, location, company, and biography; confirm none of those values appear in the result evidence, JSON output, or attestation, while the two-factor value the step reads is still recorded.

**Acceptance Scenarios**:

1. **Given** a step that reads the auditing user's own account, **When** it records evidence, **Then** only the fields the check needs are kept.
2. **Given** an attestation generated from such a result, **When** it is produced, **Then** it contains none of the auditor's personal profile fields.

### Edge Cases

- An expression references a project value that is a candidate (unconfirmed): an evaluation error, and the step is ERROR. It is never treated as an absent value that happens to make the expression true.
- A step type evaluates its own expression (the platform API step): unchanged; it already reports failed evaluation as ERROR.
- A plugin re-registers its own step type (for example on reload): allowed when the same plugin registers the same name again.
- A third-party framework file uses keys that were silently ignored before: loading now fails with the key named. The release notes call this out, and the error message says how to fix it.
- A plugin step type named in a framework is missing because the plugin is not installed: the control is ERROR with a cause naming the missing type, which is non-compliant, consistent with "missing implementations degrade gracefully" (they never pass).
- A scanner prints a findings document in an unexpected shape: the expression fails to evaluate, so the step is ERROR.
- Existing corpus fixtures that expected PASS from a reproducibility text signal: updated to the new expected outcome, with the reason recorded.

## Requirements *(mandatory)*

### Functional Requirements

**Expressions (#479)**

- **FR-001**: When a step's expression cannot be evaluated, or evaluates to a value other than true or false, the step result MUST be ERROR with an evaluation error class and the cause, regardless of the step's own result.
- **FR-002**: An expression MUST have access to the step's output, to project data limited to usable values (confirmed or concluded, 042), and to a `file_exists(path)` function that answers for the audited repository.
- **FR-003**: A reference in an expression to data its step type never provides MUST fail framework loading, naming the control, step, and reference.
- **FR-004**: The documentation of expression variables MUST match what is provided; anything documented but not provided is removed from the documentation or provided.

**Step types and settings (#486, #481)**

- **FR-005**: A plugin MUST NOT replace a built-in step type. Such a registration is refused and reported at warning level or above with both names; the built-in is unchanged.
- **FR-006**: A step type name registered by one plugin MUST NOT be replaced by a different plugin; the later registration is refused and reported naming both plugins.
- **FR-007**: Unknown control-level keys in a framework file MUST fail loading, naming the file, control, and key.
- **FR-008**: Each built-in step type MUST declare the settings it accepts. A step key that is neither a common step setting nor declared by its step type MUST fail loading, naming the file, control, step, and key. Plugin step types MAY declare their settings and then get the same check; a plugin step type that does not declare them loads with one warning per step type.
- **FR-009**: A step naming a step type that is not registered MUST fail framework loading, except when the type is expected from a plugin that is not installed, in which case the affected control MUST be reported as ERROR naming the missing type. A step MUST never be silently skipped.

**Reproducibility checks (#453)**

- **FR-010**: A reproducibility check that decides from text or file-presence signals MUST NOT conclude PASS unless a corpus measurement recorded with the framework justifies it (041 promotion). Its signals MUST be kept as evidence for later steps. This applies to all five such check types: provenance, hermetic build, bit-for-bit, dependency pinning, and build environment declared.
- **FR-011**: The reproducibility controls affected by FR-010 MUST keep a path to a verdict: their later steps (model judgment and human review) MUST receive the signals as evidence.

**Expressions that decide (clarification 2026-10-04)**

- **FR-015**: A step MAY declare that its expression decides on its own: when the step's command or check completed successfully, the expression's true is PASS and false is FAIL (within the step type's ceiling). Without that declaration the outcome rules of FR-001 and the existing agreement table apply. The OSPS-BR-01.01 and OSPS-AC-04.02 scanner steps MUST declare it, so a matching finding is FAIL rather than a manual-review warning.

**Personal data (#493)**

- **FR-012**: A step that reads people's account records MUST declare the fields it keeps and record only those; the auditor's other profile fields MUST NOT appear in evidence, output files, or attestations. The personal-record endpoints are a documented list (framework-design 3.8), each including every path under it, with any one path segment standing for a placeholder: `/user`, `/users/*`, `/orgs/*/members`, `/orgs/*/outside_collaborators`, `/orgs/*/teams/*/members`, and `/repos/*/*/collaborators`. A command step that runs `gh api` against one of them MUST fail loading, directing the author to the platform API step, which can declare the fields it keeps.

**Verification**

- **FR-014**: The framework templates and examples that ship with darnit (`darnit-hello`, `darnit-example`) and their documentation MUST use only registered step types, so they load under FR-009 (#501).
- **FR-013**: The false-PASS corpus gate (041) MUST include a case for each path closed here: an expression that cannot be evaluated on a passing step, a plugin redefining a built-in step type, and a reproducibility text signal without the real property.

### Key Entities

- **Step type**: A named kind of check (built-in or from a plugin), with a ceiling on what it may conclude and, after this feature, a declared set of settings.
- **Expression**: A condition attached to a step that must hold for the step's result to stand; it sees the step's output, usable project data, and a repository-aware `file_exists`.
- **Corpus measurement**: The recorded evidence (041) that justifies a check concluding PASS beyond its ceiling.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the reproduction for #479 (scanner exits successfully with no findings document), OSPS-BR-01.01 and OSPS-AC-04.02 report ERROR, not PASS; across all shipped frameworks, 0 steps conclude PASS or FAIL when their expression cannot be evaluated.
- **SC-002**: A plugin attempting to redefine any built-in step type changes the behavior of 0 controls, and the attempt appears in the run's warnings.
- **SC-003**: Every shipped framework file loads under the stricter checks; a file with a misspelled setting fails to load 100% of the time with the key named.
- **SC-004**: In the reproduction for #453, 0 reproducibility controls conclude PASS from a text mention alone.
- **SC-005**: In the reproduction for #493, 0 of the auditor's profile fields other than those the check reads appear in evidence, JSON output, or attestations.
- **SC-006**: The corpus false-PASS gate covers each closed path and reports 0 false PASSes.

## Assumptions

- Feature 041's ceilings, ERROR classes, promotion mechanism, and corpus gate are in place and unchanged; this feature applies them to the paths they missed.
- The platform API step already evaluates its own expression and reports failed evaluation as ERROR; it is unchanged except for FR-012.
- Stricter loading may reject third-party framework files that relied on silently ignored keys; this is intended and is announced in the release notes as a breaking change.
- PR #532 may land before or after this feature; the reproducibility changes are made in that framework's own configuration and registration so either order works, and whichever lands second rebases.
- The gittuf checks run a cryptographic verification tool and keep their PASS ceiling; the Baseline branch-protection check reads platform settings and keeps its PASS ceiling.
- ASCII-only text; no reference to unpublished security advisories.
