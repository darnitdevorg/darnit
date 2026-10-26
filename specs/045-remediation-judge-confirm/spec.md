# Feature Specification: Judge and Confirm After Remediation

**Feature Branch**: `045-remediation-judge-confirm`

**Created**: 2026-10-25

**Status**: Draft

**Input**: User description: "681" (issue #681: Comply leaves remediated documents PENDING: judge and confirm after remediation)

## Background

Since feature 041, a check on a document's content concludes at most FAIL. The document passes only through a model judgment that becomes a PASS candidate, and the operator's confirmation of that candidate (framework-design 3.0.1-3.0.2, 5.4). That is intended: a keyword match in a file is not evidence that the file says what the control requires.

The comply flow was not updated to follow that path to its end. Measured on the reference repository wtf-frontend at 939e838 (#681), remediation writes SUPPORT.md, GOVERNANCE.md, CONTRIBUTING.md, CODEOWNERS, a threat model, and SECURITY.md. The re-check of each of those six controls is PENDING, awaiting a model judgment, and remediation reports them `changed_not_passing`. The comply skill judges PENDING controls once, from the first audit, before remediation. It never judges the documents it just wrote, and it never asks the person to confirm any PASS candidate, including the ones from its first judgments. The person ends with new documents that still count as non-compliant, an outcome that reads as "the fix did not work", and no prompt saying what to do next.

This is most of the drop measured in #666: PASS 29 -> 42 after remediation at v0.1.0, 17 -> 18 on main. Part of the old number came from regex matches concluding PASS, which feature 041 removed on purpose; this feature does not restore them. It completes the path feature 041 defines, so a document darnit wrote can pass the way any document passes: a model judges it, and the person confirms the judgment.

Depends on the judgment tools of #669-#672 (`get_judgment_requests`, subset re-gathering, procedures returned by the tools, and `pending.kind` on summary rows), and on features 041 (PASS candidates, confirmation) and 043 (remediation outcomes, re-check).

## Clarifications

### Session 2026-10-25

- Q: How should a remediation outcome say what a PENDING re-check awaits? -> A: Keep the `changed_not_passing` kind and carry the re-check's `pending.kind` (`llm_judgment` or `confirmation`) on it. The set of outcome kinds in framework-design 15.4 is unchanged (FR-008).
- Q: Should the agent that wrote or edited a generated document also judge it? -> A: Yes. The same agent judges; when the candidate is shown, the person is told the document was written by remediation and edited by the agent, and that the agent's own judgment is what they are confirming (FR-004).
- Q: Should confirmations given in comply also count in CI or on another maintainer's machine? -> A: No, out of scope. Confirmations stay operator-side as today; the final report says they apply only where they were given, and portability is a follow-up issue (FR-006).
- Q: Should `/darnit-audit` on its own also ask the person to confirm PASS candidates? -> A: Yes. `/darnit-audit` and `/darnit-comply` end with the same confirmation step, from the procedure the tools return (FR-002, FR-007).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Comply judges what it wrote and asks the person to confirm (Priority: P1)

A maintainer runs `/darnit-comply` in a coding agent. After darnit writes documents and the agent improves them, the agent gets the judgment requests for the controls those documents were written for, judges each one, and then shows the maintainer every PASS candidate, its reasoning, and the passages it cites. The maintainer confirms the ones that are true of the project. Only those controls pass in the final audit; the rest stay non-compliant and are listed as waiting for the maintainer.

**Why this priority**: Without it, every document-content control darnit remediates stays non-compliant, and comply cannot bring a repository into compliance. This is the regression the work exists to fix.

**Independent Test**: Run `/darnit-comply` on a fresh copy of the reference repository with the recorded answers, answer the confirmation questions as a person would, and compare the final audit with the confirmations given.

**Acceptance Scenarios**:

1. **Given** remediation wrote a document whose re-check is PENDING awaiting a judgment, **When** comply continues after improving the generated files, **Then** it obtains and submits a judgment for that control from the document as it now stands, before the final audit.
2. **Given** one or more PASS candidates exist for the repository, **When** comply reaches the confirmation step, **Then** it shows the person each candidate (control, what the control requires, the file, the model's reasoning, and the quoted passages) and asks about it, and confirms only those the person confirms.
3. **Given** the person confirms some candidates and declines or skips others, **When** the final audit runs, **Then** the confirmed controls are PASS (asserted, with the confirmer) and the others are PENDING and listed as awaiting the person, not as failures of the fix.
4. **Given** a candidate concerns a document darnit generated and the agent edited, **When** it is shown to the person, **Then** the question says the document was generated by remediation and edited by the agent, that the judgment is the agent's own, and asks whether it reflects the project's actual practice, not whether the text looks correct.
5. **Given** the person gives no answer about a candidate, or the run cannot reach a person, **When** comply finishes, **Then** nothing is confirmed and the report lists the candidate as awaiting confirmation.
6. **Given** the model judges a generated document as not meeting its control (for example because it still holds template placeholders), **When** comply reports, **Then** the control is listed with the model's finding and what the person would need to change, and no candidate is offered for it.

---

### User Story 2 - Candidates from the first judgments are offered too (Priority: P1)

Comply and `/darnit-audit` already judge controls that were PENDING, which can produce PASS candidates for documents the project already had. Today neither skill offers those candidates for confirmation, so they stay non-compliant as well. The same confirmation step covers them, in both skills.

**Why this priority**: Same failure as User Story 1, for documents the project wrote itself. It costs nothing extra once the confirmation step exists.

**Independent Test**: Run comply on a repository that already has a SECURITY.md that a model judges as meeting its control, and with nothing to remediate for that control; check that the candidate is offered and, once confirmed, passes.

**Acceptance Scenarios**:

1. **Given** the first judgments produced a PASS candidate for a control remediation did not touch, **When** comply reaches the confirmation step, **Then** that candidate is offered with the same information as in User Story 1.
2. **Given** a person runs `/darnit-audit` alone and its judgments produced PASS candidates, **When** the audit flow ends, **Then** it offers the same confirmation step as comply, with the same information and rules.
3. **Given** a candidate's document changed after it was judged (remediation or the agent's improvements rewrote it), **When** comply reaches the confirmation step, **Then** the stale candidate is not offered; the control is judged again from the current content first.

---

### User Story 3 - Remediation says what a changed control is waiting for (Priority: P2)

A maintainer or an agent reads the result of a remediation apply. For each control whose re-check did not pass, the result says whether it failed, needs verification, or is waiting for a judgment or a confirmation, and names the next step (judge these controls, or ask the person about these candidates).

**Why this priority**: The outcome is truthful today but misleading: "changed, not passing" for a document awaiting review looks like a broken fix. Agents and reports decide what to do next from outcomes, never from text (framework-design 15.4).

**Independent Test**: Apply remediation on the reference repository and read the outcomes of the six document controls: each says it awaits a judgment, and the result names the next step.

**Acceptance Scenarios**:

1. **Given** a control changed and its re-check is PENDING awaiting a judgment, **When** the apply result is produced, **Then** that control's outcome says it is awaiting a judgment, distinguishable without reading report text from a control whose re-check is FAIL or WARN.
2. **Given** a control changed and its re-check is a PASS candidate, **When** the apply result is produced, **Then** the outcome says it is awaiting the operator's confirmation.
3. **Given** any controls are awaiting a judgment or a confirmation, **When** the apply result is produced, **Then** it names them and the next step, compactly (control identifiers, not their evidence).
4. **Given** an outcome awaiting a judgment or confirmation, **When** any compliance summary, attestation, or level calculation reads it, **Then** the control is non-compliant, exactly as today.
5. **Given** the commit and pull request gates (framework-design 15.7), **When** a run's only changed controls are awaiting a judgment or confirmation, **Then** the gates behave as for any changed outcome: they see files changed.

---

### User Story 4 - The replay measures the whole path (Priority: P2)

A contributor running the reference-repository replay sees two numbers after remediation: PASS from deterministic checks alone, and PASS after recorded judgments and recorded confirmations are applied. A change that breaks the judge-and-confirm path lowers the second number, so it shows up in review.

**Why this priority**: The replay has no model, and the headless agent runs never confirm, so neither can reach a confirmed PASS today. A regression on this path would go unnoticed, as this one did.

**Independent Test**: Run the replay on the reference repository with its recorded answers, judgments, and confirmations; check that both counts are reported and that removing one recorded confirmation lowers the second count by one.

**Acceptance Scenarios**:

1. **Given** a reference repository with recorded answers, recorded judgments, and recorded confirmations, **When** the replay runs, **Then** it reports PASS before remediation, PASS after remediation, and PASS after judge-and-confirm, and the remediation outcomes.
2. **Given** a recorded judgment whose cited passages are not in the content remediation produced, **When** the replay submits it, **Then** it is rejected exactly as a model's would be, and the replay reports which control and passage, rather than skipping it.
3. **Given** the recorded judgments and confirmations, **When** the product runs outside the replay, **Then** it never reads them.

---

### Edge Cases

- The agent improves a generated document after it was judged. The evidence digest changes, the candidate no longer matches, and the control must be judged again before it is offered (User Story 2, scenario 2). Comply therefore judges after improving, not before.
- The person edits a document after confirming it. The confirmation stops applying when the evidence changes (framework-design 5.4); the next audit shows the control PENDING again. Unchanged by this feature.
- The repository identity was not named. Candidates are stored only for a named repository (5.4); comply already confirms the repository before its first call (#672). Without it, no candidate exists and the report says so.
- A generated document still holds placeholders. A faithful judgment is FAIL; the report names it as needing the person's edits (User Story 1, scenario 6). The flow never confirms a document because darnit wrote it.
- A remediated control's re-check is WARN (for example OSPS-VM-05.03 after `.github/dependabot.yml` is written, #681 item 4). It is reported as needing verification, not as awaiting a judgment. Why it is WARN is investigated separately.
- Judgment requests for many controls exceed what a tool result can carry. The requests are paged (`remaining`), as `get_judgment_requests` already does.
- The person asks the agent to confirm everything without looking. The agent shows each candidate and asks about each; it confirms one only when the person says to confirm that candidate (framework-design 5.4, Principle IV). A single answer naming several candidates the person has been shown counts for each one named.
- The remediation pull request is audited in CI or by another maintainer. The confirmations given in comply are not there, so those controls show PENDING (confirmation) in that audit. The comply report says so (FR-006).
- The model service is unavailable during the post-remediation judgments. Those controls stay PENDING awaiting a judgment, the report says the judgment could not be obtained, and nothing is confirmed.

## Requirements *(mandatory)*

### Functional Requirements

**Comply flow (framework-design 15, then the comply skill)**

- **FR-001**: After remediation is applied and the generated files are improved, the comply flow MUST obtain judgment requests for the controls remediation changed whose state is PENDING awaiting a judgment, judge them from their current content, and submit the judgments, before any confirmation step or final audit.
- **FR-002**: The comply flow and the audit flow (`/darnit-audit`) MUST each end with the same confirmation step, which offers the person every PASS candidate stored for the named repository whose evidence still matches the current content, whether it came from the first judgments or from FR-001. FR-003 to FR-005 apply to both.
- **FR-003**: For each candidate offered, the flow MUST show the control, what it requires, the file, the model's reasoning, and the cited passages, and MUST ask the person to decide about that candidate.
- **FR-004**: A candidate for a document written or rewritten by remediation in this run MUST be presented as generated by remediation, naming whether the agent then edited it, and stating that the judgment being confirmed is that same agent's. The question MUST ask whether the document reflects the project's actual practice. The same agent MAY judge a document it edited; the person's confirmation is the check.
- **FR-005**: The flow MUST confirm only the candidates the person explicitly confirms, each named. Silence, a skipped question, a run that cannot reach a person, or a request to confirm everything without naming candidates the person was shown MUST confirm nothing.
- **FR-006**: The final audit MUST run after the confirmation step, and the final report MUST list separately: controls that pass, controls awaiting the person's confirmation, controls awaiting a judgment (with why), controls the model judged as not meeting the requirement (with the finding), and the rest. The report MUST state that confirmations are recorded for the operator who gave them, on that machine, and that an audit elsewhere (CI, another maintainer) shows those controls as PENDING until confirmed there.
- **FR-007**: The steps of FR-001 to FR-006 MUST be returned by the tools as procedures (as `get_judgment_requests` and `get_pending_data` do after #671), so a skill or other client defers to them instead of restating them. The confirmation step is one procedure, shared by the audit and comply flows.

**Remediation outcomes (framework-design 15.4, 15.5)**

- **FR-008**: When a changed control's re-check is PENDING, its outcome MUST state what it awaits (a judgment, or the operator's confirmation of a PASS candidate), in a form readable without parsing report text: the outcome kind stays `changed_not_passing` and carries the re-check's `pending.kind` (`llm_judgment` or `confirmation`). The set of outcome kinds in framework-design 15.4 MUST NOT change. A `changed_not_passing` outcome whose re-check is FAIL or WARN carries no `pending.kind`.
- **FR-009**: Every outcome of FR-008 MUST remain non-compliant and MUST count as a changed outcome for the commit and pull request gates. A re-check PASS remains the only path to `fixed`.
- **FR-010**: An apply result MUST list the controls awaiting a judgment and those awaiting confirmation, by identifier, and name the next step for each group, without repeating their evidence.

**Measurement (test tooling only)**

- **FR-011**: A reference repository's recorded data MUST be able to include, beside its answers, recorded judgments (per control: verdict, reasoning, cited passages) and recorded confirmations (per control), written by a person as corpus labels are.
- **FR-012**: The replay MUST submit recorded judgments through the same path a model's judgment takes, MUST apply recorded confirmations only through the operator confirmation path in its isolated environment, and MUST report PASS after judge-and-confirm separately from PASS after remediation.
- **FR-013**: A recorded judgment MUST identify itself as recorded, not as a model's, wherever a judgment's source is recorded.
- **FR-014**: The product MUST NOT read recorded judgments or recorded confirmations. They exist only for the replay and the end-to-end runs.

### Key Entities

- **PASS candidate**: Unchanged (framework-design 5.4). A positive judgment with verified citations, stored operator-side for a named repository and control, bound to the evidence digest. Non-compliant until confirmed.
- **Remediation outcome**: Unchanged set of kinds (15.4). A `changed_not_passing` outcome whose re-check is PENDING gains the re-check's `pending.kind`.
- **Recorded judgment**: Test-only. Control, verdict, reasoning, cited passages, labelled as recorded. Lives with the reference repository's recorded answers.
- **Recorded confirmation**: Test-only. Control identifier that a person, writing the fixture, would confirm for that reference repository after remediation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the reference repository (wtf-frontend at 939e838) with its recorded answers, judgments, and confirmations, the replay's PASS after judge-and-confirm is at least the deterministic PASS after remediation plus the number of remediated document controls whose recorded judgment is a pass and recorded confirmation exists; today the six controls of #681 add zero.
- **SC-002**: In a headless comply run on the reference repository (confirmation not allowed), every control remediation changed whose re-check is PENDING ends either with a submitted judgment or with a stated reason it has none; none is left without a judgment attempt. Today all six are left unjudged.
- **SC-003**: In that headless run, the final report lists every resulting PASS candidate as awaiting the person's confirmation, and confirms none.
- **SC-004**: In an interactive comply run (Layer 3 of the end-to-end checklist), the person is asked about every PASS candidate, sees the cited passages for each, and the final audit's PASS set equals the deterministic PASS set plus exactly the candidates the person confirmed.
- **SC-005**: No outcome awaiting a judgment or confirmation is ever counted as compliant or `fixed`, in any summary, report, attestation, or level calculation (verified by tests over every outcome kind).
- **SC-006**: An agent reading only the apply result can tell, for each changed control that did not pass, whether it failed, needs verification, or awaits a judgment or confirmation, without reading report prose.

## Assumptions

- The judgment tools from #669-#672 land first; this feature builds on `get_judgment_requests`, its subset re-gathering, `pending.kind` on summary rows, and procedures returned by tools.
- The product surface is the MCP tools and the audit and comply skills. `darnit run` and `darnit harness` are test scaffolding and are out of scope, except that their reports must not misreport the new outcome information.
- No regex or presence check regains authority to conclude PASS. The only route to PASS for document content remains a judged candidate plus the operator's confirmation.
- The replay is #666's `scripts/comply_replay.py` (#675 is closed). FR-011 to FR-014 apply to it and land after it.
- OSPS-VM-05.03 re-checking as WARN after remediation (#681 item 4) is investigated separately.
- The size of remediation preview and apply results, which today exceeds what an agent can read in one tool result, is a separate issue. FR-010 must not make it worse.
- Confirmations stay operator-side (framework-design 5.4). Making them count in CI or for another maintainer changes the feature 040 trust model and is a follow-up issue, not part of this feature.
- ASCII-only text throughout, per project convention.
