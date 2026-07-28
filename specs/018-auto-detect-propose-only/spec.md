# Feature Specification: Propose-Only Auto-Detection for User-Judgment Keys

**Feature Branch**: `018-auto-detect-propose-only`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "Narrow `auto_detect = false` from 'the sieve MUST NOT run' to 'steps may propose, never conclude' - Stage 0 governance prerequisite from RFC-0001"

## Clarifications

### Session 2026-07-28

- Q: Do confirmations expire? -> A: The amendment states that confirmations
  record when and by whom they were made, and MAY expire per configuration.
  The expiry period itself is left to implementation.
- Q: Can a confidence threshold ever auto-accept a user-judgment key? -> A: No.
  The existing provision permitting configurable confidence thresholds is
  scoped explicitly to keys that do not require human judgment. Confidence-based
  auto-acceptance at remediation time is a separate concern and is unaffected.
- Q: What version does the constitution bump to? -> A: MINOR (1.3.0),
  justified by the precedent set at 1.0.0 -> 1.1.0, where the same principle
  was widened while its core requirement stayed intact.
- Q: Does the configuration flag keep its name? -> A: Yes. The amendment
  redefines the meaning of the existing flag only. Its name no longer describes
  what it does, and that mismatch is recorded as known debt for a later stage
  rather than fixed here.
- Q: How far does the amendment reach beyond the two governing documents? ->
  A: It also updates every prose document that restates the old rule, so that
  nothing in the documentation tree contradicts the amended rule on merge.
  Code, configuration files, and their comments are enumerated but left
  untouched, because changing them would change behavior.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Maintainer amends the governance rule (Priority: P1)

A darnit maintainer needs the project's own written rules to permit a workflow
that is currently forbidden: showing a person a detected candidate value for a
key that requires human judgment, so the person can accept or correct it rather
than research it from scratch.

Today both governing documents state that when a key is marked as requiring
human judgment, detection is forbidden outright. That wording bans a safe and
useful behavior along with the unsafe one, because it conflates *producing* a
candidate with *using* it. The maintainer amends both documents so the rule
forbids only the unsafe half: a detected value may be offered, but may never
become the key's value without explicit human confirmation.

**Why this priority**: RFC-0001 names this amendment as a hard prerequisite for
its Stage 1. No implementation work in that direction can begin while the
project's own constitution forbids it. This story is the entire reason the
feature exists; everything else supports it.

**Independent Test**: Read the amended text of both documents in isolation and
confirm that (a) offering a candidate for a human-judgment key is permitted,
and (b) accepting that candidate without explicit human confirmation is
forbidden. No code needs to exist for this to be testable.

**Acceptance Scenarios**:

1. **Given** the constitution's principle on user-judgment values, **When** a
   maintainer reads the amended rule, **Then** it permits detection to run for
   the sole purpose of producing an unconfirmed candidate, and forbids that
   candidate from being treated as the key's value.
2. **Given** the runtime development guidance in CLAUDE.md, **When** it is
   compared against the amended constitution, **Then** the two agree on the
   rule with no contradictory statement remaining in either.
3. **Given** the amendment, **When** the constitution's own amendment procedure
   is applied, **Then** the version is bumped by one MINOR increment and the
   recorded rationale states that the core requirement is unchanged.
4. **Given** the merged amendment, **When** RFC-0001's Stage 0 row is checked,
   **Then** it references this change as satisfied.

---

### User Story 2 - Contributor implements against an unambiguous rule (Priority: P2)

A contributor is about to build the behavior the amendment permits. They need
the rule to answer boundary questions without guesswork, because guessing wrong
here reintroduces exactly the failure mode the original rule existed to
prevent.

The rule must be specific about what "never conclude" covers: an unconfirmed
candidate must not reach audit results, compliance calculations, remediation
actions, attestations, or persisted project context, and must not be laundered
into confirmed status by a confidence score.

**Why this priority**: A rule that permits the new behavior but leaves its
limits vague is worse than the current strict rule, because it invites
divergent interpretations across implementations. This must land with the
amendment, not after it.

**Independent Test**: Present the amended rule to two readers with a list of
consumption paths (audit status, compliance math, remediation input,
attestation, persisted context) and ask which are permitted to consume an
unconfirmed candidate. Both should answer "none" without consulting code.

**Acceptance Scenarios**:

1. **Given** a key requiring human judgment and a detected candidate for it,
   **When** an audit runs, **Then** the rule requires the key be treated as
   unverified, identical to having no candidate at all.
2. **Given** a configured confidence threshold for automatic acceptance,
   **When** it is applied to a key requiring human judgment, **Then** the rule
   forbids automatic acceptance regardless of the threshold value or the
   candidate's confidence.
3. **Given** an unconfirmed candidate, **When** project context is written to
   disk, **Then** the rule forbids storing it in a form that later reads would
   treat as confirmed.
4. **Given** a prompt shown to a language model, **When** it references an
   unconfirmed candidate, **Then** the rule forbids that candidate appearing
   inside an executable snippet.
5. **Given** a candidate presented to a person, **When** they view it, **Then**
   the rule requires it be labelled as unconfirmed and carry its origin.

---

### User Story 3 - Reviewer confirms nothing regressed (Priority: P3)

A reviewer needs assurance that loosening a written rule did not silently
loosen behavior. Because the amendment permits something previously forbidden,
any existing code or configuration that relied on the strict wording could now
be read as compliant when it is not, or could be changed opportunistically
under cover of the amendment.

**Why this priority**: Valuable, but it verifies the first two stories rather
than delivering new capability. If it slipped, the amendment would still be
correct; the project would just have less confidence in it.

**Independent Test**: Run the existing audit suite against a fixed sample
project before and after the change and compare results. They must be
identical, because this feature changes documents only.

**Acceptance Scenarios**:

1. **Given** the merged amendment, **When** an audit is run against a project
   with keys requiring human judgment, **Then** the results are identical to a
   run before the amendment.
2. **Given** the inventory of places that restate or depend on the old wording,
   **When** each is reviewed, **Then** every prose entry is updated to match and
   every code or configuration entry is recorded as deferred with a reason.

---

### Edge Cases

- A candidate is produced but the person never responds. The key stays
  unconfirmed indefinitely and any control depending on it stays unverified;
  there is no timeout that converts silence into acceptance.
- A person confirms a candidate, and a later run detects a different value.
  The stored confirmation stays authoritative for as long as it remains
  unexpired; a new detection may surface a conflict but may not overwrite the
  confirmation on its own.
- A stored confirmation passes its configured expiry. It reverts to a
  candidate and must be confirmed again before it is usable, so a key that was
  compliant can return to unverified without anything in the project changing.
- Detection fails or produces nothing. Behavior is unchanged from today: the
  person is asked with no pre-filled answer.
- A candidate is produced for a key that feeds a remediation action. The
  remediation cannot proceed on the candidate; it is blocked on the same
  confirmation as everything else.
- Two keys are detected and the person confirms only one. The confirmed key
  becomes usable; the other remains unverified. Confirmation is per-key.
- The detected candidate is itself sourced from untrusted repository content.
  It is still only a candidate, so the confirmation step remains the trust
  boundary, and it must not be rendered as executable text on the way there.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The governing documents MUST permit detection to run for a key
  marked as requiring human judgment, for the sole purpose of producing a
  candidate value.
- **FR-002**: The governing documents MUST forbid an unconfirmed candidate from
  being consumed as the key's value by any of: control verification results,
  compliance calculations, remediation actions, generated attestations, or
  persisted project context.
- **FR-003**: The governing documents MUST require that a candidate presented
  to a person is labelled as unconfirmed and accompanied by its origin (how it
  was detected).
- **FR-004**: The governing documents MUST forbid confidence-based automatic
  acceptance from applying to keys requiring human judgment, at any threshold
  value. The existing provision permitting configurable confidence thresholds
  MUST be scoped explicitly to keys that do not require human judgment, so that
  no reader can apply it to a user-judgment key.
- **FR-005**: The governing documents MUST state that human confirmation is the
  only mechanism that converts a candidate into a usable value, and that
  storing a candidate does not constitute confirmation.
- **FR-006**: The governing documents MUST require that a stored confirmation
  records when it was made, by whom, and what candidate it was based on, and
  MUST permit a confirmation to expire after a configurable period, reverting
  the key to a candidate that requires re-confirmation. The amendment MUST NOT
  fix the period; that is left to implementation.
- **FR-007**: The governing documents MUST retain the existing prohibition on
  placing unconfirmed values inside executable snippets in prompts shown to
  language models.
- **FR-008**: Both the project constitution and the runtime development
  guidance MUST be amended together and MUST NOT contain any statement that
  contradicts the amended rule.
- **FR-009**: The constitution MUST record the amendment under its own
  amendment procedure, bumping the version by one MINOR increment. The recorded
  rationale MUST state that the core requirement (no unconfirmed value is ever
  used) is unchanged and only the permitted mechanism widens, matching the
  justification used the last time this same principle was widened.
- **FR-010**: An inventory MUST be produced of every location that restates,
  documents, or enforces the previous wording, with each entry marked as
  updated, deferred, or explicitly unaffected.
- **FR-011**: Every prose document that restates the previous wording MUST be
  updated alongside the governing documents, so that no document contradicts
  the amended rule once merged. Locations in code, configuration, or their
  comments MUST be recorded in the inventory as deferred and MUST NOT be
  changed by this feature.
- **FR-012**: RFC-0001 MUST reference this change as satisfying its Stage 0
  gate.
- **FR-013**: This feature MUST NOT change any observable audit, remediation,
  or context-collection behavior.
- **FR-014**: The existing configuration flag that marks user-judgment keys
  MUST keep its current name and accepted values, so that existing project
  configuration continues to load unchanged. The amendment MUST record that the
  flag's name no longer describes its narrowed meaning, as known debt to be
  addressed in a later effort.

### Key Entities

- **User-judgment key**: A named piece of project context whose correct value
  requires a person's decision rather than observation. Examples in the current
  configuration include maintainer lists, security contacts, and governance
  model.
- **Candidate value**: A value produced by detection for a user-judgment key.
  Carries its origin and, where the detecting step provides one, a confidence
  indication. Is never the key's value.
- **Confirmation**: An explicit human decision that a candidate is correct, or
  a human-supplied replacement. The only transition that makes a value usable.
  Records when it was made, by whom, and the candidate it was based on, and has
  a lifetime after which it reverts to a candidate.
- **Origin record**: The description of how a candidate was produced, retained
  alongside it so a person can judge whether to trust it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Two independent readers, given only the amended documents and a
  list of five consumption paths, agree on which paths may consume an
  unconfirmed candidate, with 100% agreement and the answer being "none".
- **SC-002**: Zero statements remain in any prose document, governing or
  contributor-facing, asserting that detection must not run for user-judgment
  keys.
- **SC-003**: All five consumption paths named in FR-002 are explicitly covered
  by the amended text; a reader can cite the sentence that covers each.
- **SC-004**: An audit of a fixed sample project produces identical results
  before and after the change, confirming zero behavior drift.
- **SC-005**: 100% of the inventory entries from FR-010 are resolved as either
  updated or explicitly unaffected, with no entry left undetermined.
- **SC-006**: RFC-0001's Stage 0 gate is satisfied: the change is merged as its
  own pull request and referenced from the RFC.

## Assumptions

- The amendment follows the project's existing governance process for
  architecture-affecting changes, including the comment period and maintainer
  consensus described in GOVERNANCE.md.
- This feature delivers document changes only. Implementing the permitted
  behavior is a separate, later effort (RFC-0001 Stage 1) and is out of scope
  here. This is why FR-013 requires zero behavior change.
- The existing configuration mechanism for marking user-judgment keys is
  retained unchanged, including its name and accepted values; only the meaning
  of the mark is narrowed. See FR-014.
- The permission to propose applies regardless of how the candidate was
  produced. No detection source can conclude a user-judgment key, so no source
  needs to be singled out.
- Existing automatic-acceptance behavior for keys that do not require human
  judgment is unaffected.
- This rule governs the verification side only, where a wrong answer is an
  invisible false pass. Automatic acceptance of remediation output, where a
  wrong answer is a visible and revertible change, is a separate trust boundary
  and is out of scope here.
- The safety property being preserved is that no unconfirmed value is ever
  used. The property being dropped is that no unconfirmed value is ever
  computed. These were previously conflated in a single sentence.
