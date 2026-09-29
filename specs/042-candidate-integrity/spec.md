# Feature Specification: Candidate Integrity for Project Values

**Feature Branch**: `042-candidate-integrity`

**Created**: 2026-09-28

**Status**: Draft

**Input**: User description: "042: candidate integrity for user-judgment project values. Detected guesses (maintainers, security contact, CI provider, release status) are never stored or consumed as confirmed; only a person's confirmation makes a value usable. Covers #468, #469, #465, #484, #470, #476, #463, and the typed confirmed/candidate model proposed in #358."

## Background

darnit reads project data such as maintainers, the security contact, the CI provider, and whether the project has made releases. Some of these can be observed; others require a person's decision. Constitution Principle IV (Never Guess User Values) says a detected value for a user-judgment key is only a candidate: it may be shown to a person, labelled with its origin, but it must never be consumed by verification results, compliance calculations, remediation inputs, attestations, or persisted project context until a person confirms it, and a stored candidate must remain distinguishable from a confirmed value on every later read.

The September 2026 evaluation found the opposite in practice:

- Listing what still needs confirmation (which every MCP audit does to print its "next steps") detects values, accepts any detection above a confidence threshold, and writes it into the repository's `.project/` files. On the next read, every bare value loads as confirmed by a user. An audit therefore silently records guesses as human decisions (#468).
- The OpenSSF Baseline configuration marks maintainers and security contact as auto-detectable, and the acceptance path ignores the flag that should forbid concluding them (#469).
- Remediation fills generated files (CODEOWNERS, SECURITY.md) from whatever is stored, with no check of how the value was obtained, so an email-domain fragment scraped from MAINTAINERS.md ends up in CODEOWNERS (#465).
- Questions shown to agents embed detected values inside ready-to-run confirmation calls, offer template placeholders as answers, and hide some enum choices (#484).
- A failed release lookup (bad token, rate limit, no network) is stored as "no releases", which marks release controls not applicable (#470).
- The CI provider has three key names and two vocabularies; confirming an unrelated value stores a spelling that no control condition recognizes, flipping CI controls to not applicable (#476).
- A user-authored `.project/project.yaml` that darnit's schema rejects is silently replaced with a scaffold on the next write (#463).

Feature 040 already gates not-applicable claims (explicit or implied by a context value) behind the trust model, and feature 041 made model judgments candidates that the operator confirms. This feature applies the same discipline to project context values.

## Clarifications

### Session 2026-09-28

- Q: How are values already stored without a confirmation record treated? -> A: Every such value of a user-judgment key is a candidate until a person confirms it, with a one-step review to confirm or remove all of them at once (FR-010).
- Q: Where are context confirmations recorded? -> A: In the repository's darnit extension file for repositories the operator controls (trusted), otherwise in the operator-side store from feature 040; never written into a repository the operator does not control (FR-011).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Audits and queries never write project data (Priority: P1)

A maintainer (or a coding agent on their behalf) runs an audit and asks what still needs confirmation. Nothing in the repository changes, and no value becomes confirmed as a side effect.

**Why this priority**: This is the entry point of every guess-becomes-fact chain found in the evaluation; closing it stops new bad data immediately.

**Independent Test**: On a repository with MAINTAINERS.md and SECURITY.md and no `.project/`, run an audit through every driver and list pending data; confirm no file is created or modified and every detected value is reported as a candidate.

**Acceptance Scenarios**:

1. **Given** a repository without `.project/`, **When** an audit runs through any driver (MCP tool, harness, test CLI), **Then** no file under the repository is created or modified.
2. **Given** a repository with detectable maintainers, **When** pending data is listed, **Then** maintainers appears as pending with a candidate and its origin, and nothing is stored.
3. **Given** a remediation dry run, **When** it completes, **Then** no file under the repository is created or modified.
4. **Given** the headless harness collect phase, **When** it runs, **Then** it persists nothing to the repository.

---

### User Story 2 - User-judgment keys are proposed, never concluded (Priority: P1)

For keys that require a person's decision (maintainers, security contact, governance model, and any key marked as requiring judgment), darnit may propose a candidate but never uses it as the value. Controls, compliance, remediation, and attestations treat an unconfirmed key as unverified.

**Why this priority**: Without this, any detector with a high enough confidence silently decides who the maintainers are and where vulnerabilities are reported.

**Independent Test**: With a detected but unconfirmed maintainers candidate, run an audit, a remediation, and an attestation; confirm none of them uses the candidate, and that remediation stops with "confirmation required" for templates that need it.

**Acceptance Scenarios**:

1. **Given** a user-judgment key with a detected candidate at any confidence, **When** context is resolved, **Then** the key is unconfirmed and the candidate is not used as its value.
2. **Given** a framework configuration that marks a key as requiring judgment, **When** any detection route (declared detection steps, sieve hints, legacy auto-detection) produces a value, **Then** it is only ever a candidate.
3. **Given** a remediation whose template refers to an unconfirmed user-judgment key, **When** it runs, **Then** it refuses to render that template and reports which key needs confirmation, whether or not the control declared the dependency.
4. **Given** a remediation tool parameter that corresponds to a user-judgment key (for example a license choice), **When** the caller omits it, **Then** the tool does not substitute a default value for it.
5. **Given** an attestation for a repository with an unconfirmed user-judgment key, **When** it is generated, **Then** the key's value does not appear as a fact in it.

---

### User Story 3 - Questions show candidates as data, never as ready-to-run answers (Priority: P1)

When darnit asks a person (directly or through a coding agent) to confirm a value, the candidate is shown as labelled, unconfirmed data with its origin. Nothing the agent could execute verbatim contains a guessed value, placeholders are never offered as answers, and every allowed value of a choice is reachable.

**Why this priority**: Agents execute what they are shown; a pre-filled confirmation call turns "the agent followed instructions" into "the guess was confirmed".

**Independent Test**: Request pending questions and a remediation preflight on repositories with detected maintainers, a single-commit history, and no data at all; inspect every returned command template and option list.

**Acceptance Scenarios**:

1. **Given** a detected candidate, **When** a question or preflight prompt is produced, **Then** any confirmation command template contains only a placeholder for the person's answer, and the candidate appears separately, labelled unconfirmed, with its origin.
2. **Given** a free-text key with no detection, **When** a question is produced, **Then** the configuration's illustrative examples are not offered as selectable answers.
3. **Given** a choice key, **When** a question is produced, **Then** every allowed value is reachable (none silently dropped).
4. **Given** a yes/no confirmation of a candidate, **When** the person answers yes, **Then** the confirmation records that the person accepted that specific candidate (and its origin), not merely that a value was stored.

---

### User Story 4 - Confirmation is recorded and stays distinguishable (Priority: P2)

A person confirms a value through the confirmation tool. darnit records who confirmed it, when, and which candidate (if any) it was based on. On every later read, confirmed values and candidates are distinguishable, and values that were stored without a recorded confirmation are candidates until a person confirms them.

**Why this priority**: This makes the safety property durable across runs and machines, and it is the only way to repair repositories that already contain guesses written by earlier darnit versions.

**Independent Test**: Confirm maintainers, re-load context in a new process, and confirm the record carries confirmer, time, and basis; load a repository that contains values written by an earlier darnit version and confirm they load as candidates and can all be confirmed or removed in one review step.

**Acceptance Scenarios**:

1. **Given** a person confirms a value, **When** context is later loaded, **Then** the value is confirmed and carries who, when, and the candidate it was based on.
2. **Given** a value stored without a confirmation record, **When** context is loaded, **Then** it is a candidate (origin: stored without confirmation) and is never silently upgraded to confirmed.
3. **Given** values stored without confirmation records, **When** the person asks to review them, **Then** darnit lists them with their current values so the person can confirm or remove each one, in one step for many keys.
4. **Given** a confirmed value, **When** the person changes the underlying data by hand, **Then** the changed value is not reported as confirmed by the earlier confirmation.

---

### User Story 5 - Failed detection is not a value; one name per key (Priority: P2)

When a lookup fails (authorization, rate limit, network, missing tool, no remote), the key stays unknown rather than becoming a negative value. Each context key has one name and one vocabulary, so a confirmed value always means what the control conditions expect.

**Why this priority**: Both defects make controls silently not applicable, which improves reported compliance without any verification.

**Independent Test**: Resolve release status with a failing platform lookup and with a working one; confirm the failing case leaves the key unknown and release controls unchanged. Confirm an unrelated value on a repository with CI workflows and confirm CI controls keep their conditions satisfied.

**Acceptance Scenarios**:

1. **Given** a release lookup that fails for any reason other than a successful answer, **When** release status is resolved, **Then** no value is produced or stored and release-gated controls are evaluated as if the value were unknown.
2. **Given** a detection step with a fallback value, **When** the step could not run to completion, **Then** the fallback is not applied; it applies only when the step ran and answered "no".
3. **Given** a repository using a CI system, **When** any context value is confirmed, **Then** the stored CI provider (if any) uses the same name and vocabulary that control conditions use.
4. **Given** a legacy spelling or legacy key name for the CI provider in stored data, **When** context is loaded, **Then** it is read under the canonical name and vocabulary.

---

### User Story 6 - A user-authored project file is never destroyed (Priority: P2)

A project maintains its own `.project/project.yaml`. If darnit cannot parse or validate it, darnit reports the problem and writes nothing to it; darnit never replaces it with a scaffold, and it never rewrites fields it does not own.

**Why this priority**: Silent data loss of a hand-maintained file is the most visible way a compliance tool can lose a project's trust.

**Independent Test**: Place a hand-written `project.yaml` that darnit's schema rejects, run an audit and a confirmation; confirm the file is byte-identical afterwards and the error is reported.

**Acceptance Scenarios**:

1. **Given** a `project.yaml` that fails to parse or validate, **When** any darnit operation needs to write context, **Then** it does not write that file and reports the validation error to the caller.
2. **Given** a valid `project.yaml`, **When** darnit records a confirmation, **Then** fields darnit does not own, comments, and ordering in that file are preserved.
3. **Given** an absent `.project/` directory, **When** a person confirms a value, **Then** darnit creates only what is needed to record that confirmation.

### Edge Cases

- A detector returns a value identical to a previously confirmed value: the key stays confirmed under the existing record; no new record is created from detection alone.
- A confirmed value's confirmation record exists but the value in the file was edited by hand: the new value is not confirmed by the old record (User Story 4, scenario 4).
- A key is marked as requiring judgment in one framework and as detectable in another loaded framework: the stricter rule applies.
- A repository is audited by an operator who does not trust it (feature 040): values from its `.project/` still load, but not-applicable implications continue to follow the feature 040 trust outcomes.
- A value that is not a user-judgment key (for example the detected primary language) may still be concluded from detection when the framework allows it, and is recorded with its origin.
- Harness runs with an answers file: answers supplied there are treated as the operator's confirmations for that run (feature 027 `asserted` answers) and are persisted only if the operator asks.
- The platform reports releases exist but lists none visible to the token: treated as unknown, not as "no releases".

## Requirements *(mandatory)*

### Functional Requirements

**No side effects from reading**

- **FR-001**: Auditing, listing pending data, generating reports, previewing remediation (dry run), and the harness collect phase MUST NOT create, modify, or delete any file in the audited repository.
- **FR-002**: Only an explicit confirmation action by a person (directly, or by an agent acting on the person's explicit instruction) and an applied (non-dry-run) remediation MAY write project context into the repository.

**Candidates versus confirmed values**

- **FR-003**: Every context value MUST carry its standing: confirmed (with who, when, and basis), candidate (with origin), or concluded-by-detection (only for keys that do not require judgment, with origin).
- **FR-004**: For a key that requires judgment, no detection route, confidence threshold, or framework setting MAY produce a confirmed value; only a person's confirmation MAY.
- **FR-005**: The OpenSSF Baseline configuration MUST mark maintainers and security contact as requiring judgment (candidates may still be proposed).
- **FR-006**: Control verification, compliance calculations, remediation inputs, attestations, and persisted project context MUST consume only confirmed values (or concluded values for keys that do not require judgment). An unconfirmed user-judgment key counts as unverified.
- **FR-007**: Remediation MUST refuse to render any template that refers to an unconfirmed user-judgment key, regardless of whether the control declares that dependency, and MUST report which keys need confirmation.
- **FR-008**: A remediation or tool parameter that corresponds to a user-judgment key MUST NOT default to a value when omitted.

**Recording confirmations**

- **FR-009**: A confirmation MUST record who confirmed, when, the confirmed value, and the candidate (value and origin) it was based on, if any. Confirmations MUST remain distinguishable from candidates on every later read and in every process.
- **FR-010**: A value of a user-judgment key found in stored project data without a confirmation record (in either the project file or darnit's extension file) MUST be treated as a candidate (origin: stored without confirmation) until a person confirms it. darnit MUST offer a one-step review that lists every such value, with its current value and location, so a person can confirm or remove any number of them in a single action.
- **FR-011**: Confirmation records MUST be stored in the repository's darnit extension file when the confirmation is made for a repository the operator controls (a repository in the operator's trusted list from feature 040), so that everyone who clones it sees the same confirmations; otherwise they MUST be stored in the operator-side store from feature 040, keyed by the repository's canonical identity, and MUST NOT write into the repository. When both exist for a key, the in-repository record for the current value takes precedence; an operator-side record applies only to that operator's runs.
- **FR-012**: A confirmation MUST apply only to the value that was confirmed; if the stored value later differs, the key is unconfirmed.

**Questions and prompts**

- **FR-013**: No prompt, question, command template, or answer mapping produced for a person or agent MAY contain a candidate or guessed value inside an executable form; candidates MUST be presented as separate, labelled, unconfirmed data with their origin.
- **FR-014**: Illustrative examples from a key's configuration MUST NOT be offered as answers.
- **FR-015**: Every allowed value of a choice key MUST be reachable in a question.

**Detection failures and key names**

- **FR-016**: A detection step's fallback value MUST apply only when the step ran to completion and answered negatively; a step that errored or could not decide MUST produce no value.
- **FR-017**: Release status MUST NOT be stored or used as "no releases" unless a successful platform answer showed none.
- **FR-018**: Each context key MUST have exactly one canonical name and one vocabulary, taken from the framework configuration; legacy names and spellings in stored data MUST be read as the canonical form, and darnit MUST write only the canonical form.

**Protecting user-authored files**

- **FR-019**: darnit MUST distinguish an absent project file from one that is present but unreadable or invalid, and MUST NOT write to a present-but-invalid file; it MUST report the error to the caller.
- **FR-020**: darnit MUST NOT replace an existing project file with a scaffold, and MUST preserve fields it does not own, comments, and ordering when it writes to a project file.
- **FR-021**: darnit-specific data (confirmation records, darnit-only keys) MUST be kept out of the upstream-format project file so that file stays conformant to its upstream definition.

### Key Entities

- **Context key**: A named piece of project data (maintainers, security contact, CI provider, release status, governance model, ...), with one canonical name, a vocabulary or shape, and a flag saying whether it requires a person's judgment.
- **Candidate**: A value produced by detection, with its origin (which detector, from what source). Never consumed as the key's value when the key requires judgment.
- **Confirmation**: A person's decision on a key's value: the value, who, when, and the candidate it was based on. Makes the value usable; applies only while the stored value matches.
- **Concluded value**: A detected value for a key that does not require judgment, accepted under the framework's rules and recorded with its origin.
- **Project file / extension file**: The repository's upstream-format project data file (owned by the project) and darnit's own extension file beside it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across the reproduction repositories from #468, #469, #465, #470, #476, #463, running an audit, listing pending data, and previewing remediation modifies 0 files in the repository.
- **SC-002**: In those reproductions, 0 detected values of user-judgment keys are reported as confirmed or consumed by a verification result, compliance calculation, remediation output, or attestation.
- **SC-003**: 100% of confirmation command templates and answer mappings returned to agents contain no candidate value; 100% of choice questions expose every allowed value.
- **SC-004**: A failing release lookup changes the result of 0 release-gated controls compared with an audit where release status is simply unknown.
- **SC-005**: A hand-written project file that darnit's schema rejects is byte-identical after any darnit operation, and the operation reports the validation error.
- **SC-006**: Every stored value read back in a new process is labelled confirmed, candidate, or concluded exactly as it was when stored.

## Assumptions

- Features 040 (operator configuration, trust, confirmation store) and 041 (result contract, PASS candidates) are in place; this feature builds on them and does not change their rules.
- Release status and CI provider are observable facts: they may be concluded from a successful detection without a person, but never from a failed one. Maintainers, security contact, and governance model require judgment.
- Confirmations of context values do not expire by default; an expiry policy, if wanted, is a follow-up (the constitution permits but does not require one).
- Adopting upstream `.project/` schema conformance in full (#498) is out of scope; this feature only guarantees darnit does not break or replace the project's own file.
- Remediation atomicity, dry-run fidelity, and the other remediation safety issues (#472-#475, #483) are a separate feature; this feature covers only which values remediation may use.
- ASCII-only text; no reference to unpublished security advisories.
