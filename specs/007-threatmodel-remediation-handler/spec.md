# Feature Specification: Threat Model Remediation Handler

**Feature Branch**: `007-threatmodel-remediation-handler`
**Created**: 2026-03-25
**Status**: Draft
**Input**: User description: "Wire generate_threat_model as a remediation handler for SA-03.02 so that the dynamic STRIDE analysis (with exploitation scenarios, DFD, attack chains) runs during remediation instead of using the static template. Follow the existing handler registration pattern - reuse the same generate_threat_model code, just wrap it as a remediation handler."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dynamic Threat Model During Remediation (Priority: P1)

As a user running `remediate_audit_findings` for control SA-03.02, I want the remediation to generate a project-specific threat model using the dynamic STRIDE analysis engine (with exploitation scenarios, data-flow diagrams, and attack chains) instead of writing a generic static template, so that the resulting THREAT_MODEL.md is immediately useful without manual customization.

**Why this priority**: This is the entire purpose of the feature. Today, remediation creates a generic template that requires extensive manual editing. The dynamic analysis engine already exists — it just needs to be wired into remediation so users get a real threat model on first run.

**Independent Test**: Run `remediate_audit_findings` targeting SA-03.02 on a repository with discoverable assets. Verify the generated THREAT_MODEL.md contains project-specific threats, exploitation scenarios, a Mermaid data-flow diagram, and attack chains — not the generic template text.

**Acceptance Scenarios**:

1. **Given** a repository with API endpoints and a database, **When** SA-03.02 remediation runs, **Then** THREAT_MODEL.md contains STRIDE threats specific to the discovered endpoints/data stores, each with exploitation scenarios and ranked controls.
2. **Given** a repository with no discoverable assets, **When** SA-03.02 remediation runs, **Then** THREAT_MODEL.md is still created with a valid report structure that explains no assets were discovered and suggests manual review.
3. **Given** THREAT_MODEL.md already exists, **When** SA-03.02 remediation runs, **Then** the existing file is NOT overwritten (respects the overwrite=false setting).

---

### User Story 2 - Fallback to Static Template on Analysis Failure (Priority: P2)

As a user, I want the remediation to gracefully fall back to the existing static template if the dynamic analysis fails (e.g., due to an unsupported project structure), so that remediation never fails completely.

**Why this priority**: Reliability is critical for a compliance tool. The dynamic analysis may encounter edge cases where asset discovery produces no useful results or errors out. Users should still get a usable starting point.

**Independent Test**: Trigger SA-03.02 remediation on a repository where the threat analysis engine raises an error. Verify that THREAT_MODEL.md is created using the static template rather than failing the remediation entirely.

**Acceptance Scenarios**:

1. **Given** the dynamic analysis engine raises an error during remediation, **When** the handler catches the error, **Then** it falls back to creating the file from the static template and includes a note that dynamic analysis was unavailable.
2. **Given** the dynamic analysis produces an empty report (no threats, no assets), **When** the handler evaluates the result, **Then** it still writes the report (which will explain that no assets were found) rather than falling back to the template.

---

### Edge Cases

- What happens when the repository path is invalid or inaccessible? The handler should return an error result, same as other remediation handlers.
- What happens during a dry run? The handler should report what it would do (generate dynamic threat model at the specified path) without writing any files.
- What happens when the TOML config specifies `overwrite = true` and THREAT_MODEL.md already exists? The handler should regenerate and overwrite the file with fresh analysis.
- Does the `llm_enhance` field still apply? No — the dynamic analysis replaces the need for LLM enhancement since it already produces project-specific content.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The remediation system MUST support a handler that generates a dynamic STRIDE threat model for the target repository using the existing analysis engine.
- **FR-002**: The handler MUST reuse the same analysis pipeline (framework detection, asset discovery, threat analysis, attack chain detection) that the existing tool uses.
- **FR-003**: The handler MUST follow the existing handler registration pattern (same function signature, same registry, same dispatch mechanism).
- **FR-004**: The handler MUST respect the `overwrite` configuration field — if false and the target file exists, skip generation.
- **FR-005**: The handler MUST respect the `path` configuration field for the output file location.
- **FR-006**: The handler MUST support dry-run mode, reporting what it would generate without writing files.
- **FR-007**: If the dynamic analysis fails, the handler MUST fall back to the static template approach and report the fallback in its result message.
- **FR-008**: The SA-03.02 control's TOML remediation configuration MUST be updated to replace the `file_create` handler entirely with the new handler. The new handler owns both dynamic generation and static template fallback internally — no handler chaining required.
- **FR-009**: The handler MUST produce Markdown output by default with detail_level="detailed" (exploitation scenarios, DFD, attack chains).
- **FR-010**: The `project_update` configuration for SA-03.02 MUST remain unchanged (still sets `security.threat_model.path`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: SA-03.02 remediation on a repository with discoverable assets produces a THREAT_MODEL.md containing at least one project-specific STRIDE threat (not generic template text).
- **SC-002**: SA-03.02 remediation on a repository where dynamic analysis fails still produces a valid THREAT_MODEL.md (via fallback).
- **SC-003**: Dry-run mode for SA-03.02 reports the intended action without creating any files.
- **SC-004**: All existing remediation tests continue to pass — no regressions.
- **SC-005**: The handler follows the same registration and dispatch pattern as other handlers — no special-case code paths in the executor.

## Clarifications

### Session 2026-03-25

- Q: Should the new handler replace `file_create` entirely or be chained before it? → A: Replace entirely. The new handler owns both dynamic generation and static template fallback internally — no handler chaining needed.

## Assumptions

- The sieve handler registry is the correct registry for remediation handlers (not the MCP tool handler registry).
- The handler function signature is `(config: dict, context: HandlerContext) -> HandlerResult`, matching all existing remediation handlers.
- The dynamic analysis engine is fast enough to run during remediation without timeout concerns (it currently completes in seconds for typical repositories).
- The static template (`threat_model_basic`) remains available as a fallback and is not removed.

## Scope Boundaries

**In scope**:
- Creating a new remediation handler that wraps the existing threat model generation
- Registering it following the existing pattern
- Updating SA-03.02's TOML remediation config to use the new handler
- Fallback to static template on failure
- Dry-run support

**Out of scope**:
- Changes to the threat model analysis engine itself (feature 006 already handled that)
- Changes to the remediation executor dispatch logic
- Adding new TOML configuration fields beyond what existing handlers support
- Making the handler available for controls other than SA-03.02 (though the pattern is reusable)
