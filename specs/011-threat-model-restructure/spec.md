# Feature Specification: Threat Model Output Restructure

**Feature Branch**: `011-threat-model-restructure`
**Created**: 2026-04-13
**Status**: Draft
**Input**: User description: "Restructure the threat model generator so its output is human-readable — split the single monolithic report into a summary + grouped detail files, carry mitigation decisions across regenerations via a sidecar, and teach the baseline audit to find the new layout while keeping the old one valid."

## Clarifications

### Session 2026-04-13

- Q: How should the "mitigation stance" cell in the summary's top-risks table display a class's status when instances have mixed decisions? → A: Count form `<mitigated>/<total>` — e.g. `8/27` — where "mitigated" includes the statuses mitigated, accepted, and false-positive.
- Q: How many classes should the summary's top-risks table display when a scan produces many distinct classes? → A: Cap at top N classes by max severity (default N=20); classes beyond the cap are collapsed into a single "and N more classes" line linking to a complete index of all detail files. The "Unmitigated findings" section and detail files are not capped.
- Q: Should the finding fingerprint incorporate the file path (so renames invalidate sidecar entries) or be path-independent (so renames preserve them)? → A: Include the file path. Renames/moves invalidate existing entries, which go stale on next regen and must be manually re-recorded by a reviewer. This is the safer default: a decision cannot silently reattach to code the reviewer never looked at.
- Q: Should the raw-findings JSON export include mitigation status from the sidecar, or remain scan-only? → A: Include mitigation fields. Each finding in the raw export carries its fingerprint plus mitigation status, note, reviewer, review date, and stale flag when a matching sidecar entry exists; fields are absent when no sidecar entry matches.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Reviewer gets a readable top-level risk picture (Priority: P1)

A security reviewer opens a repository's threat model to understand what risks exist and what the team has done about them. Today they are confronted with a monolithic document that lists the same vulnerability class dozens of times (for example, one command-injection pattern matched at 27 different call sites produces 27 separate multi-paragraph entries). The reviewer cannot quickly answer "what are the top-level risks?" or "which classes of finding dominate?"

After this change, the reviewer opens one short summary document that lists each distinct vulnerability class once, with its instance count, severity band, and current mitigation stance. They drill into a class-specific detail document when they want to see every location where that class was found.

**Why this priority**: This is the core user-visible value. Everything else in the feature is in service of making this experience possible. A reviewer who gets only this slice already has a dramatically better experience than today.

**Independent Test**: Regenerate a threat model against a repository that produces many findings. A reviewer must be able to (a) read the summary document end-to-end in a single sitting, (b) identify the distinct vulnerability classes present, (c) click through to a class-specific detail file and find every instance of that class listed compactly. No expert knowledge of the tool's internals is required.

**Acceptance Scenarios**:

1. **Given** a repository whose scan produces findings spanning multiple vulnerability classes, **When** a reviewer opens the summary document, **Then** they see a single "top risks" table with one row per class, each row showing the class name, instance count, maximum severity, and mitigation stance.
2. **Given** the same summary document, **When** the reviewer follows a link from a top-risks row, **Then** they land on a class-specific detail page that has one shared header (class description, mitigation narrative, a small number of representative code snippets) followed by a compact listing of every instance with its file location, severity, and mitigation status — no repeated narrative or code blocks per instance.
3. **Given** a reviewer wants to audit the complete machine data, **When** they open the accompanying raw-findings export, **Then** every finding the scan produced is present with no findings dropped, even ones that did not appear in the summary's top-risks table.
4. **Given** the scan finds a large number of distinct vulnerability classes, **When** the summary document is rendered, **Then** its length stays short enough for a reviewer to read end-to-end (target: roughly 150 lines or fewer for a representative project-scale scan).

---

### User Story 2 — Maintainer's mitigation decisions survive regeneration (Priority: P2)

A project maintainer reviews a threat model, reaches a decision about a particular finding (for example: "this finding is mitigated because input validation happens upstream"), and records that decision in a committed, human-editable file. The next time anyone regenerates the threat model — whether minutes or months later — the reviewer's decision is reflected in the new output: the finding is shown as mitigated in the summary's top-risks table, and it is excluded from the "Unmitigated findings" list. If the code the decision referred to is later deleted or moved so much that it no longer matches, the recorded decision is kept and flagged as stale; the tool never silently discards prior reviewer decisions.

**Why this priority**: Without this, every regeneration is a blank slate. Teams either stop regenerating (losing currency) or stop recording decisions (losing institutional memory). Either failure negates most of the value of user story 1 over time. It is P2 only because user story 1 is already a dramatic improvement on its own.

**Independent Test**: Hand-author a mitigation entry for a known finding, regenerate the threat model, and confirm the summary reflects the decision. Then delete the referenced code and regenerate again — confirm the decision entry is flagged stale but still present in the sidecar file.

**Acceptance Scenarios**:

1. **Given** a sidecar entry marking a specific finding as mitigated with a note and reviewer name, **When** the threat model is regenerated, **Then** that finding is counted as mitigated in the summary's top-risks table and does not appear in the "Unmitigated findings" section.
2. **Given** the same sidecar entry, **When** the underlying source code is modified so the finding no longer occurs, **Then** the next regeneration flags the sidecar entry as stale but does not delete it.
3. **Given** a repository with no sidecar file, **When** the threat model is generated for the first time, **Then** generation succeeds and every finding is treated as having no recorded decision (neither mitigated nor stale).
4. **Given** multiple findings share the same mitigation decision rationale, **When** a reviewer records separate sidecar entries for each, **Then** each entry is matched independently and each status is applied independently at render time.
5. **Given** a sidecar entry exists but the code it references has moved to a different file or been reformatted, **When** regeneration runs, **Then** the entry is considered stale (the fingerprint no longer matches) rather than silently reattached to the new location.

---

### User Story 3 — Compliance audit recognizes the new canonical location (Priority: P3)

A compliance tool (the OpenSSF Baseline audit, control OSPS-SA-03.02) is used to confirm that a repository has a threat model. After this change, the audit recognizes the new canonical location as evidence of compliance. At the same time, repositories that have not yet migrated continue to pass the same audit against their existing threat model file at any of the previously supported locations.

**Why this priority**: Adoption friction. Without this, any project that moves to the new layout fails its own compliance audit until someone updates the tool configuration manually. P3 because it only affects teams that already run this specific audit; teams that only consume the threat model for human review (user story 1) are unaffected.

**Independent Test**: Run the OSPS-SA-03.02 audit against a repository that has only the new-layout file, then against one that has only a legacy-location file. Both must pass.

**Acceptance Scenarios**:

1. **Given** a repository whose threat model lives at the new canonical location, **When** the OSPS-SA-03.02 audit runs, **Then** it passes.
2. **Given** a repository whose threat model lives only at a legacy location (such as the repository root), **When** the OSPS-SA-03.02 audit runs, **Then** it still passes.
3. **Given** a repository with threat models at both the new canonical location and a legacy location, **When** the audit runs, **Then** the new canonical location is preferred for reporting purposes, but the audit result is "pass" regardless of which is chosen.
4. **Given** a repository that has a legacy threat model at the repository root, **When** regeneration runs and writes the new layout, **Then** the legacy file is left untouched (never auto-deleted), and a migration note is surfaced in the regeneration result informing the maintainer they may remove the legacy file.

---

### Edge Cases

- **Empty scan**: A repository that produces zero findings must still produce a valid summary document indicating no findings and no detail files.
- **Single-class scan**: A repository where every finding belongs to one vulnerability class must still produce one summary plus one detail file (not collapse them into a single doc).
- **Sidecar file present but empty or malformed**: Malformed sidecar files must not silently be treated as "no prior decisions." Generation should fail loudly with a clear message rather than discarding reviewer intent.
- **Stale entries across multiple regenerations**: An entry flagged stale on one run must remain flagged stale on subsequent runs until a human removes it or the referenced finding reappears.
- **Finding with no mitigation narrative available**: A vulnerability class for which the tool has no pre-canned mitigation narrative must still render a valid detail file — the narrative section may be empty or say "no guidance available," but the file must not be suppressed.
- **Discovery priority tie**: If a repository somehow has threat model files at both the new canonical and a legacy location, the new canonical location wins for reporting purposes; the audit still passes in any case.
- **Reviewer renames a file**: A fingerprint that was previously recorded against a file that has since been renamed will no longer match, and the sidecar entry is flagged stale. This is by design; re-recording the decision is a conscious human action.
- **Regeneration produces identical output**: Running regeneration twice in a row with no changes in the codebase, scan rules, or sidecar must produce byte-identical output files (idempotence).

## Requirements *(mandatory)*

### Functional Requirements

#### Output structure

- **FR-001**: The system MUST produce a short executive summary document suitable for a reviewer to read end-to-end, containing scan metadata, a "top risks" table listing each distinct vulnerability class, an explicit "Unmitigated findings" section, and navigation links to per-class detail documents, the data-flow document, and the raw-findings export. Each row of the top-risks table MUST show, at minimum, the class name, its total instance count, its maximum severity, and a mitigation stance cell in the form `<mitigated>/<total>` (e.g. `8/27`), where "mitigated" is the count of instances whose sidecar status is `mitigated`, `accepted`, or `false_positive`.
- **FR-002**: The system MUST produce one detail document per distinct vulnerability class identified in the scan, where the class is identified by the rule that matched. Each detail document MUST contain a single shared header (class name, category, rule identifier, one aggregate mitigation narrative, and a small number of representative code snippets drawn from the highest-severity instances) followed by a compact per-instance listing (file location, severity, confidence, mitigation status) of every occurrence of that class. The listing MUST NOT repeat the mitigation narrative or full code block per instance.
- **FR-003**: The system MUST produce a standalone document containing the data-flow diagram and asset inventory, separated from the executive summary to keep the summary short.
- **FR-004**: The system MUST produce a machine-readable export containing every finding the scan produced, with no findings dropped due to any display or ranking limit. Each finding in the export MUST include its computed fingerprint. When a matching sidecar entry exists for a finding, the export MUST include the mitigation status, note, reviewer, review date, and stale flag alongside the scan-level data. When no sidecar entry matches, those fields MUST be absent (not defaulted to a sentinel value).
- **FR-005**: The system MUST NOT drop findings from the per-class detail documents under any circumstances. Any existing ranking limit MUST be scoped to the executive summary's top-risks display only.
- **FR-005a**: The summary's top-risks table MUST cap its visible rows at the top N vulnerability classes ordered by maximum severity score (default N=20, configurable). When more than N classes exist, the system MUST render a single trailing line indicating the number of additional classes omitted (e.g. "and 17 more classes") and link it to a complete, uncapped index listing every per-class detail document. The "Unmitigated findings" section MUST NOT apply this cap, and detail documents themselves MUST NOT be suppressed by it.
- **FR-006**: Per-class detail documents MUST group all instances of the same rule identifier into a single document. Each document's name MUST be derived from the rule identifier in a stable, human-readable way.

#### Mitigation sidecar

- **FR-007**: The system MUST support a committed sidecar file, co-located with other per-project configuration, where reviewers hand-record mitigation decisions about individual findings. Each decision entry MUST carry a stable fingerprint identifying the finding, a status (one of: mitigated, accepted, false positive, unmitigated), a free-form note, a reviewer identifier, and a review date.
- **FR-008**: On each regeneration, the system MUST read the sidecar, match every finding's fingerprint against recorded decisions, and surface the recorded status in both the summary document and the per-class detail documents.
- **FR-009**: The fingerprint algorithm MUST be deterministic and stable across regenerations where the underlying finding has not substantively changed. It MUST incorporate the rule identifier, the repository-relative file path, and a whitespace-normalized representation of the matched code so that trivial reformatting does not break existing decisions. Including the file path is a deliberate safety choice: renaming or moving a file invalidates its existing sidecar entries (they go stale on next regen), preventing a recorded decision from silently re-attaching to code the reviewer never explicitly evaluated at the new location.
- **FR-010**: When a sidecar entry's fingerprint does not match any finding in the current scan, the system MUST mark that entry as stale and persist the mark. The system MUST NOT delete, overwrite, or silently discard stale entries.
- **FR-011**: The system MUST NOT automatically create new sidecar entries. All mitigation decisions originate from human action (hand-editing the sidecar file). A future interactive tool for managing entries is out of scope for this change.
- **FR-012**: A finding whose fingerprint matches a sidecar entry with status "mitigated", "accepted", or "false positive" MUST be excluded from the summary's "Unmitigated findings" section. A finding with status "unmitigated" or no matching entry MUST be included.

#### Compliance audit

- **FR-013**: The OpenSSF Baseline control responsible for detecting the presence of a threat model (OSPS-SA-03.02) MUST recognize the new canonical summary location as satisfying evidence, in addition to all locations it previously recognized.
- **FR-014**: The discovery path list MUST be evaluated in a first-match order that prefers the new canonical location while still accepting every previously supported legacy location. No previously passing repository may begin failing the control solely as a result of this change.

#### Regeneration and legacy handling

- **FR-015**: When regeneration runs in a repository that already contains a threat model file at the legacy root-level location, the system MUST leave that file untouched (no automatic deletion, overwrite, or move) and MUST surface a migration note in the regeneration result informing the maintainer that the legacy file may be removed manually.
- **FR-016**: Regeneration MUST be idempotent: running it twice in succession with no intervening changes to the code, the scan configuration, or the sidecar MUST produce byte-identical output across the summary, detail, data-flow, and raw-findings artifacts.
- **FR-017**: Existing programmatic callers that previously obtained the threat model as a single combined document (rather than by reading the multi-file output) MUST continue to succeed. A compatibility path MUST return the concatenated equivalent of the multi-file output for such callers.

#### Error handling

- **FR-018**: A malformed or unreadable sidecar file MUST cause regeneration to fail with a clear, actionable error identifying the file and the parse problem, rather than silently proceeding as if no prior decisions existed.
- **FR-019**: An empty scan (zero findings) MUST still produce a valid summary document, a data-flow document, and a raw-findings export. No per-class detail documents are produced in this case.

### Key Entities

- **Vulnerability class**: A distinct category of finding identified by the rule (tree-sitter query) that matched. All instances sharing a rule identifier belong to the same class. Each class has a human-readable name, a category label (STRIDE), a stable rule identifier used to derive file names, and an aggregate mitigation narrative.
- **Finding instance**: A single occurrence of a vulnerability class at a specific file and line. Carries a severity score, a confidence score, a code snippet, and a deterministic fingerprint.
- **Mitigation decision**: A reviewer's recorded judgment about a specific finding instance. Carries a status, a note, a reviewer identifier, a review date, and the fingerprint it applies to. Becomes stale if its fingerprint no longer matches any current finding; never auto-deleted.
- **Summary document**: A short, navigable overview that a reviewer reads first. Aggregates findings by class, highlights unmitigated items, and links to detail.
- **Detail document**: One document per vulnerability class. Shared header plus compact per-instance listing.
- **Data-flow document**: The asset inventory and data-flow diagram, separated from the summary.
- **Raw-findings export**: The full, unfiltered machine-readable dump of every finding. The source of truth for auditors, scripts, and downstream tools.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reviewer can open the summary document for a representative project-scale scan and read it end-to-end in a single sitting (summary length ≤ roughly 150 lines for a scan producing hundreds of findings across dozens of classes).
- **SC-002**: Regenerating a threat model that previously produced a single monolithic document preserves 100% of findings in the new multi-file structure (zero finding loss, verified by comparing counts between the pre-change output and the sum of findings across the post-change detail documents plus the raw export).
- **SC-003**: A reviewer can identify every distinct vulnerability class present in the scan by reading only the summary document, without opening any detail document, and can reach the detail for any class they choose in one navigation step from the summary.
- **SC-004**: A hand-authored mitigation decision recorded against a specific finding is reflected in output across at least three successive regenerations without further human action, as long as the referenced code is not materially altered.
- **SC-005**: When code referenced by a mitigation decision is deleted, the decision entry is still present in the sidecar file after regeneration (never removed), but is now flagged stale.
- **SC-006**: A repository that had a passing OSPS-SA-03.02 audit before this change continues to pass after this change, with no manual configuration updates required by the project maintainer.
- **SC-007**: A repository that adopts the new canonical layout passes the OSPS-SA-03.02 audit with no manual configuration updates.
- **SC-008**: Running regeneration twice in succession on an unchanged repository produces byte-identical artifacts in both runs.

## Assumptions

- Threat model regeneration is explicitly triggered (by a maintainer or an automation step), not continuously in the background. The cost model for a slightly heavier multi-file generation is therefore acceptable.
- The sidecar file is committed to version control so that mitigation decisions are reviewable in pull requests and travel with the codebase; this matches existing project conventions for project-local configuration.
- Reviewers are comfortable hand-editing a structured plain-text sidecar for now. A dedicated interactive workflow for managing decisions is recognized as valuable but explicitly out of scope here.
- "Representative" code snippets in per-class detail documents means a small number (roughly one to three) drawn from the highest-severity instances, sufficient to illustrate the class without bloating the document.
- Machine-readable export consumers (scripts, dashboards, downstream tools) prefer a single dump containing every finding over a paginated or truncated form. This also serves as the audit trail answering "did we really keep every finding?"
- The data-flow diagram and asset inventory are referenced by reviewers less often than the top-risks summary, so moving them to a separate document improves the summary's signal-to-noise without meaningfully harming the data-flow readers' workflow.

## Out of Scope

- An interactive command-line or GUI tool for creating, editing, or browsing mitigation decisions. The sidecar is hand-edited in this change; tooling comes later.
- Automatic migration or deletion of existing legacy-location threat model files.
- Cross-repository aggregation of threat models or mitigation decisions.
- Changes to the underlying discovery engine (the set of vulnerability classes detected, their severity heuristics, or the code parsing that produces findings). This change is purely about output structure and decision persistence, not about what findings are surfaced.
- Changes to the machine-readable export format beyond ensuring it contains every finding. Downstream consumers of the existing export format continue to work.
