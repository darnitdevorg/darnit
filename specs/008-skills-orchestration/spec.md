# Feature Specification: Skills-Based Orchestration Layer with Audit Profiles

**Feature Branch**: `008-skills-orchestration`  
**Created**: 2026-04-04  
**Status**: Draft  
**Input**: User description: "Skills-based orchestration layer for compliance workflows with audit profiles support (issue #140)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a Compliance Audit via Skill (Priority: P1)

A developer working in Claude Code wants to audit their repository for compliance. Instead of discovering and calling individual MCP tools in the right order, they type `/audit` and get a complete compliance report with actionable next steps — including resolution of controls that need LLM judgment.

**Why this priority**: This is the foundational skill that replaces the most common MCP workflow. It delivers immediate value by eliminating the multi-tool discovery problem and providing a single, reliable entry point for the most frequent operation.

**Independent Test**: Can be fully tested by running `/audit` in a repository and verifying that a complete compliance report is returned with pass/fail/warn statuses, compliance percentages, and suggested next steps.

**Acceptance Scenarios**:

1. **Given** a repository with a `.project/` directory and existing context, **When** the user runs `/audit`, **Then** the system runs the full sieve pipeline, resolves PENDING_LLM controls using Claude as the LLM, and displays a formatted compliance report with per-level compliance percentages and a list of failing controls with descriptions.
2. **Given** a repository with no `.project/` directory, **When** the user runs `/audit`, **Then** the system auto-initializes project context using detectors (forge, CI, build system), runs the audit, and displays results — noting that additional context collection could improve accuracy.
3. **Given** audit results that include WARN controls, **When** the report is displayed, **Then** each WARN control includes a brief explanation of why it couldn't be automatically verified and what manual verification would entail.
4. **Given** audit results with failures that have available auto-fixes, **When** the report is displayed, **Then** the report includes a "Remediation Available" section listing which controls can be automatically fixed, prompting the user to run `/remediate` if desired.

---

### User Story 2 - Guided Context Collection via Skill (Priority: P1)

A developer has run an audit and sees that several controls returned WARN because project context is missing (e.g., maintainers, governance model, CI provider). They run `/context` and are guided through a structured question-and-answer flow that collects the needed information and persists it to `.project/`.

**Why this priority**: Context collection is a prerequisite for accurate audits. The current MCP approach embeds workflow directives in tool descriptions and hopes the LLM follows them. A skill makes this reliable.

**Independent Test**: Can be fully tested by running `/context` in a repository with missing context values and verifying that the user is prompted with relevant questions, answers are saved to `.project/project.yaml`, and a re-audit of affected controls shows improved results.

**Acceptance Scenarios**:

1. **Given** a repository with incomplete project context, **When** the user runs `/context`, **Then** the system identifies which context values are missing, runs auto-detection where possible, and presents remaining questions to the user in priority order (by number of controls affected).
2. **Given** auto-detection identifies a value with high confidence (e.g., CI provider is GitHub Actions based on `.github/workflows/` existing), **When** context collection runs, **Then** the auto-detected value is presented to the user for confirmation rather than asked as an open question.
3. **Given** the user answers all context questions, **When** answers are submitted, **Then** values are persisted to `.project/project.yaml` and the system reports which controls are now unblocked for verification.
4. **Given** the user skips a question, **When** context collection continues, **Then** the skipped value is noted and the system proceeds with remaining questions without blocking.

---

### User Story 3 - Full Compliance Pipeline via Skill (Priority: P2)

A developer wants to bring their repository into compliance end-to-end. They run `/comply` and the system orchestrates the entire pipeline: audit, context collection, remediation, and optionally creating a PR with all fixes.

**Why this priority**: This is the highest-value workflow but depends on `/audit` and `/context` working correctly. It's the "happy path" that most users ultimately want.

**Independent Test**: Can be fully tested by running `/comply` in a repository with known compliance gaps and verifying that the system audits, collects context, applies safe remediations, and offers to create a PR.

**Acceptance Scenarios**:

1. **Given** a repository with compliance gaps, **When** the user runs `/comply`, **Then** the system runs an audit, identifies missing context, prompts for context values, re-audits affected controls, shows a remediation plan for fixable failures, and asks the user to confirm before applying changes.
2. **Given** the user confirms the remediation plan, **When** remediation is applied, **Then** the system creates a branch, applies fixes, commits with descriptive messages, and offers to create a PR.
3. **Given** some controls have unsafe remediations (e.g., require API access or manual review), **When** the remediation plan is shown, **Then** unsafe remediations are clearly marked and excluded from automatic application, with instructions for manual follow-up.
4. **Given** the user declines remediation, **When** they reject the plan, **Then** the system shows the audit results as-is without making any changes.

---

### User Story 4 - Audit with Named Profile (Priority: P2)

An implementation module author (e.g., for gittuf) has defined multiple audit profiles representing distinct audit scenarios (e.g., "onboard" for setup verification, "verify" for ongoing compliance). A developer runs `/audit --profile onboard` and only the controls relevant to that profile are evaluated, with profile-specific context prompts and remediation actions.

**Why this priority**: Named profiles are a force multiplier for implementation authors. Without them, modules are limited to a single flat control set, which doesn't match real-world compliance scenarios where the same tool serves different audit purposes.

**Independent Test**: Can be fully tested by creating a TOML config with two profiles containing different control sets, running `/audit --profile <name>` for each, and verifying that only the correct controls are evaluated.

**Acceptance Scenarios**:

1. **Given** an implementation with profiles "onboard" and "verify" defined in TOML, **When** the user runs `/audit --profile onboard`, **Then** only controls listed in the "onboard" profile are evaluated and reported.
2. **Given** an implementation with profiles, **When** the user runs `/audit` without specifying a profile, **Then** all controls are evaluated (default behavior, backward compatible).
3. **Given** a profile defined with tag-based filters (e.g., `security_severity_gte = 8.0`), **When** the user runs `/audit --profile security_critical`, **Then** only controls matching the tag filter are evaluated.
4. **Given** a profile name that doesn't exist, **When** the user runs `/audit --profile nonexistent`, **Then** the system returns a clear error listing available profiles.
5. **Given** a profile is specified alongside additional tag filters, **When** the audit runs, **Then** both the profile's control set and the tag filters are applied (intersection).

---

### User Story 5 - Remediation via Skill (Priority: P3)

A developer has reviewed audit results and wants to apply fixes. They run `/remediate` and the system creates a branch, applies safe auto-fixes, commits changes with descriptive messages, and offers to create a PR.

**Why this priority**: Remediation is the final step in the compliance pipeline. It can be exercised independently after a manual audit review.

**Independent Test**: Can be fully tested by running `/remediate` after an audit with known failures and verifying that a branch is created, fixes are applied, and a PR is offered.

**Acceptance Scenarios**:

1. **Given** cached audit results with failing controls that have safe remediations, **When** the user runs `/remediate`, **Then** the system shows a dry-run plan listing each fix, asks for confirmation, and applies fixes on a new branch.
2. **Given** no cached audit results, **When** the user runs `/remediate`, **Then** the system runs an audit first, then proceeds with remediation.
3. **Given** applied remediations, **When** the user confirms PR creation, **Then** the system commits changes with per-control messages, pushes the branch, and creates a PR with a summary of all fixes.

---

### User Story 6 - Profile-Aware Context and Remediation (Priority: P3)

When running the compliance pipeline with a specific profile, context collection only asks questions relevant to that profile's controls, and remediation only applies fixes for that profile's failing controls.

**Why this priority**: This completes the audit profiles feature across the full pipeline, ensuring profiles aren't just a filter on the audit step.

**Independent Test**: Can be fully tested by running `/comply --profile onboard` and verifying that only onboard-relevant context questions are asked and only onboard-relevant remediations are offered.

**Acceptance Scenarios**:

1. **Given** a profile "onboard" with 3 controls, **When** the user runs `/context --profile onboard`, **Then** only context values affecting those 3 controls are collected.
2. **Given** a profile "onboard" with failing controls, **When** the user runs `/remediate --profile onboard`, **Then** only remediations for those controls are applied.
3. **Given** a profile is used throughout `/comply`, **When** the pipeline completes, **Then** the final report only covers the profile's controls, not the full control set.

---

### Edge Cases

- What happens when a profile references a control ID that doesn't exist in the TOML? The system should warn and skip the missing control.
- What happens when auto-detection fails for all context values? The system should present all questions as open-ended prompts.
- What happens when the user runs `/remediate` but all failures have unsafe remediations? The system should report that no automatic fixes are available and list manual steps.
- What happens when a skill is run outside of Claude Code (e.g., in a CI environment)? Skills should degrade gracefully — the core engine works without skills, and the LangGraph agent mode covers headless use cases.
- What happens when two profiles overlap (share controls)? Controls should be deduplicated; each control runs exactly once.
- What happens when multiple implementations define a profile with the same name? The system should require disambiguation via `<impl>:<profile>` syntax and return a clear error listing the conflicting implementations.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide an `/audit` skill that runs the full sieve verification pipeline and returns a formatted compliance report.
- **FR-002**: System MUST resolve PENDING_LLM controls within the `/audit` skill by delegating to Claude (the active LLM) rather than requiring a separate backend.
- **FR-003**: System MUST provide a `/context` skill that identifies missing project context, runs auto-detection, and guides the user through providing remaining values.
- **FR-004**: System MUST persist context values collected via `/context` to `.project/project.yaml` using the existing context storage system.
- **FR-005**: System MUST provide a `/comply` skill that orchestrates the full pipeline: audit, context collection, remediation, and PR creation.
- **FR-006**: System MUST provide a `/remediate` skill that creates a branch, applies safe auto-fixes, commits changes, and offers PR creation.
- **FR-007**: System MUST support named audit profiles defined in implementation TOML configs under an `[audit_profiles]` section. Profile names are scoped per-implementation.
- **FR-008**: Each audit profile MUST specify its control set via either explicit control IDs, tag-based filters, or both. When both are provided, the profile includes the union of explicitly listed controls and controls matching the tag filter.
- **FR-009**: Profiles MUST be filterable across all three pipeline layers: audit (control selection), context gathering (relevant questions only), and remediation (relevant fixes only).
- **FR-010**: System MUST accept an optional `--profile` parameter on `/audit`, `/context`, `/remediate`, and `/comply` skills. When only one loaded implementation defines a given profile name, the short name suffices (e.g., `--profile onboard`). When multiple implementations define the same profile name, the system MUST require disambiguation via `--profile <impl>:<profile>` syntax.
- **FR-011**: When no profile is specified, the system MUST evaluate all controls (backward compatible default behavior).
- **FR-012**: System MUST expose profiles via the existing CLI (`darnit audit --profile <name>`) and MCP tools (optional `profile` parameter).
- **FR-013**: The `ComplianceImplementation` protocol MUST support an optional `get_audit_profiles()` method, checked via `hasattr()` for backward compatibility.
- **FR-014**: System MUST provide a way to list available profiles for an implementation (via skill, CLI, or MCP tool).
- **FR-015**: Skills MUST use darnit's MCP tools as their primary building blocks for all pipeline operations. When an MCP tool returns partial or ambiguous results, skills MAY fall back to Claude's own reasoning to interpret, supplement, or resolve the gap — but darnit's tools remain the source of truth.
- **FR-016**: System MUST show a dry-run remediation plan and require user confirmation before applying changes.

### Key Entities

- **Skill**: A predefined workflow that orchestrates multiple core engine operations in a structured sequence. Skills are the primary interface for Claude Code users.
- **Audit Profile**: A named, documented subset of controls within an implementation module, representing a distinct audit scenario. Profiles include a description, a control set (explicit IDs or tag filters), and are visible across audit, context, and remediation layers.
- **Compliance Engine**: A facade over the core subsystems (sieve, remediation, context storage) that skills and other consumers call. Provides a unified API without requiring knowledge of internal module structure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can complete a full compliance audit via a single `/audit` command, receiving results within the same time as the equivalent multi-tool MCP workflow.
- **SC-002**: Context collection via `/context` results in zero TOML-directive workarounds — the skill enforces the correct question-answer-confirm flow without relying on tool description directives.
- **SC-003**: The full `/comply` pipeline (audit + context + remediate + PR) can be completed in a single conversation without the user needing to know which tools to call or in what order.
- **SC-004**: Implementation authors can define audit profiles in TOML and have them work across audit, context, and remediation without writing any Python code.
- **SC-005**: All existing MCP tools continue to work unchanged — skills are an additive layer, not a replacement.
- **SC-006**: Running `/audit --profile <name>` evaluates only the controls in that profile, with no false inclusions from other profiles or the full control set.
- **SC-007**: 100% of skill workflows call the existing core engine functions — no duplication of sieve, remediation, or context logic.

## Clarifications

### Session 2026-04-04

- Q: How should skills invoke the core engine — direct Python, MCP tools, or a mix? → A: Skills invoke existing MCP tools as their primary building blocks. Darnit's MCP tools are the primary source of truth. However, skills should include instructions allowing Claude to fall back to its own reasoning when an MCP tool returns partial or ambiguous results (e.g., PENDING_LLM controls, WARN controls needing judgment).
- Q: Should audit profiles be scoped per-implementation or global? → A: Per-implementation, auto-resolved when unambiguous. `--profile onboard` works if only one implementation defines it; `--profile gittuf:onboard` required if multiple implementations define the same profile name.

## Assumptions

- Skills are implemented as Claude Code skill definitions (prompt templates with structured steps), not as new Python runtime code. Skills invoke darnit's MCP tools as their primary building blocks. Claude may use its own reasoning to fill gaps when tools return partial results, but tool outputs are the source of truth.
- The existing `run_sieve_audit()` function and `RemediationExecutor` are sufficient for skills to call — no new core engine facade is required for the initial implementation, though one may be extracted as a follow-up.
- Audit profiles are an optional feature — implementations that don't define profiles continue to work exactly as before.
- The LangGraph agent mode (PR #137) is a separate concern. Skills target Claude Code users; LangGraph targets headless/CI. They share the same core engine but have different orchestration layers.
- Profile-aware context and remediation (User Story 6) may be deferred to a follow-up if the initial profile filtering at the audit layer proves sufficient for initial use cases.

## Dependencies

- Existing sieve pipeline (`run_sieve_audit()`) must be callable from skill context.
- Existing remediation executor must support filtering by control ID list (for profile support).
- Existing context storage system must support filtering pending context by affected control IDs.
- Claude Code skill system must support parameterized skills (e.g., `/audit --profile onboard`).

## Scope Boundaries

**In scope**:
- `/audit`, `/context`, `/comply`, `/remediate` skills
- Audit profiles TOML schema and protocol extension
- Profile filtering across audit, context, and remediation
- CLI `--profile` flag and MCP `profile` parameter

**Out of scope**:
- Changes to the LangGraph agent mode (separate concern)
- Attestation or threat model skills (can be added later)
- Org-wide audit skills (can be added later)
- Profile inheritance or composition (profiles are flat, independent sets)
