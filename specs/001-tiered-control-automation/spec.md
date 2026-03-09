# Feature Specification: Tiered Control Automation Pipeline

**Feature Branch**: `001-tiered-control-automation`
**Created**: 2026-03-08
**Status**: Draft
**Input**: User description: "Analyze the openssf baseline controls and see how we can make this all more automated. Run controls from deterministic to heuristic to LLM fallback. Collect context similarly — GitHub APIs, file checks, then user confirmation. Use that info for remediation. Deterministic first, LLM for generative tasks like threat models."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fully Automated Single-Repo Audit (Priority: P1)

A maintainer runs an audit on their repository. The system automatically
resolves as many controls as possible without human intervention by
executing deterministic checks (file existence, GitHub API calls, CLI
commands), then falling back to heuristic pattern matching, and only
flagging controls for user attention when no automated determination
is possible.

**Why this priority**: This is the core value proposition. Currently
38% of controls are manual-only and only 2% use LLM evaluation.
Reducing manual controls by adding deterministic, heuristic, and
LLM passes directly increases the tool's usefulness and reduces the
burden on maintainers.

**Independent Test**: Run an audit against a well-configured public
repository and verify that the number of controls resolved to PASS
or FAIL (not WARN) increases compared to the current baseline.

**Acceptance Scenarios**:

1. **Given** a repository with a SECURITY.md, branch protection enabled,
   and CI configured, **When** the user runs an audit at level 1,
   **Then** at least 80% of level 1 controls produce a conclusive
   PASS or FAIL result without user interaction.
2. **Given** a repository missing common compliance artifacts,
   **When** the user runs an audit, **Then** each failing control
   includes evidence explaining why it failed and what the system
   checked.
3. **Given** a control where the deterministic check is inconclusive,
   **When** the system falls back to heuristic or LLM evaluation,
   **Then** the result includes a confidence indicator and the
   fallback tier that produced the result.

---

### User Story 2 - Progressive Context Collection (Priority: P2)

A maintainer configures their project for the first time. The system
automatically collects as much project context as possible from the
repository and GitHub APIs (maintainers from CODEOWNERS, security
contact from SECURITY.md, CI provider from workflow files, etc.),
then presents only genuinely ambiguous items for user confirmation
rather than asking the user to fill in everything manually.

**Why this priority**: Context collection is the prerequisite for
accurate auditing and remediation. Automating it reduces onboarding
friction from minutes to seconds for most fields.

**Independent Test**: Point the tool at a repository with typical
open-source artifacts and verify that the system pre-populates
context fields, only prompting for fields that genuinely cannot be
determined.

**Acceptance Scenarios**:

1. **Given** a repository with CODEOWNERS, SECURITY.md, and GitHub
   Actions workflows, **When** the user initiates context collection,
   **Then** the system auto-fills maintainers, security contact, and
   CI provider without prompting.
2. **Given** a repository where the governance model is ambiguous
   (e.g., no GOVERNANCE.md but has CODEOWNERS), **When** the system
   cannot determine the governance model deterministically, **Then**
   it presents the user with its best guess and asks for confirmation.
3. **Given** auto-collected context, **When** the user reviews it,
   **Then** they can override any auto-detected value before the
   audit proceeds.

---

### User Story 3 - Automated Remediation with LLM Fallback (Priority: P3)

After an audit identifies compliance gaps, the system generates fixes.
For deterministic remediations (creating a SECURITY.md from a template,
enabling branch protection via API), it executes directly. For
generative remediations (drafting a threat model, writing a security
policy tailored to the project), it produces an initial template and
then uses the LLM to customize it based on project context.

**Why this priority**: Remediation is the end goal — finding problems
is only useful if the tool helps fix them. This story builds on the
audit (P1) and context (P2) results.

**Independent Test**: Run a remediation pass on a repository with
known compliance gaps and verify that deterministic fixes are applied
correctly and generative outputs are contextually relevant.

**Acceptance Scenarios**:

1. **Given** a repository missing SECURITY.md, **When** remediation
   runs for that control, **Then** the system creates a SECURITY.md
   from the template populated with project-specific contact info
   from the collected context, without LLM involvement.
2. **Given** a repository that needs a threat model, **When**
   remediation runs for that control, **Then** the system generates
   an initial STRIDE-based template and uses the LLM to tailor it
   to the project's architecture and dependencies.
3. **Given** a remediation that requires a GitHub API call (e.g.,
   enabling branch protection), **When** the system executes it,
   **Then** it performs a dry-run first and shows the user what will
   change before applying.

---

### User Story 4 - Cascading Pass Transparency (Priority: P4)

A maintainer or auditor wants to understand how each control result
was determined — which pass produced the answer and what evidence
supports it. The system provides a clear audit trail showing the
progression through passes for each control.

**Why this priority**: Trust in audit results requires transparency.
Users need to know whether a PASS came from a deterministic file
check or an LLM assessment so they can calibrate their confidence.

**Independent Test**: Run an audit and verify that every control
result includes metadata about which tier produced it and what
evidence was evaluated.

**Acceptance Scenarios**:

1. **Given** an audit result, **When** the user inspects a specific
   control, **Then** they see which pass (deterministic, heuristic,
   LLM, manual) produced the result and the evidence collected at
   each attempted pass in the cascade.
2. **Given** a control that fell through multiple passes, **When** the
   user views the result, **Then** they see why each earlier pass
   was inconclusive before the final pass resolved it.

---

### Edge Cases

- What happens when the GitHub API is unavailable or rate-limited?
  The system MUST degrade gracefully, skipping API-dependent checks
  and marking them as WARN with an explanation, not failing the
  entire audit.
- What happens when an LLM evaluation contradicts a deterministic
  check? The deterministic result MUST always take precedence — the
  LLM tier is only reached when prior tiers are inconclusive.
- What happens when the user has no `gh` CLI configured or
  authenticated? The system MUST detect this upfront and inform the
  user which controls will be limited, rather than failing mid-audit.
- What happens for private repositories where file content cannot
  be accessed via API? The system MUST use local file system checks
  as the primary mechanism and only fall back to API for metadata
  not available locally.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST execute control passes in TOML
  declaration order, stopping at the first conclusive result
  (PASS, FAIL, or ERROR). The conventional ordering is
  deterministic → heuristic → LLM → manual, reflecting
  decreasing confidence and increasing cost, but the framework
  MUST NOT enforce a particular phase ordering.
- **FR-002**: The system MUST tag every control result with the
  pass that produced it and the evidence collected at each
  attempted pass in the cascade.
- **FR-003**: The system MUST auto-collect project context from
  repository files and GitHub APIs before prompting the user for
  any input.
- **FR-004**: The system MUST assign a confidence level to each
  auto-detected context field. By default, canonical-source matches
  (e.g., CODEOWNERS, SECURITY.md) are auto-accepted and heuristic
  inferences require user confirmation. Implementations MUST be
  able to configure this threshold in their TOML (e.g.,
  `auto_accept_confidence = 0.8`) or force manual verification
  for all fields.
- **FR-005**: The system MUST allow users to override any
  auto-detected context value.
- **FR-006**: For deterministic remediations (file creation, API
  calls), the system MUST execute them directly using templates and
  collected context.
- **FR-007**: For generative remediations (threat models, tailored
  policies), the system MUST produce an initial template and then
  use the LLM to customize it based on project context.
- **FR-008**: The system MUST perform a dry-run for any remediation
  that modifies external state (GitHub API calls, branch protection
  changes) and present the planned changes before execution.
- **FR-009**: The system MUST degrade gracefully when external
  dependencies (GitHub API, LLM) are unavailable, marking affected
  controls as WARN with an explanation.
- **FR-010**: The system MUST respect the existing `auto_detect`
  TOML flag — fields marked `auto_detect = false` MUST NOT be
  auto-filled under any circumstance.
- **FR-011**: The system MUST preserve the conservative-by-default
  principle: inconclusive results MUST never be promoted to PASS.
- **FR-013**: Existing manual passes MAY be removed from a control
  when the remaining automated passes fully cover the control's
  checking requirements. Every control MUST end up with equal or
  better checking and remediation coverage after changes.
- **FR-012**: The system MUST support the existing TOML-first
  control definition model — new automation tiers MUST be
  configurable in TOML, not hard-coded in Python.

### Key Entities

- **Control Result**: The outcome of evaluating a single control,
  including status (PASS/FAIL/WARN/ERROR), the resolving pass
  (index and handler name), and evidence collected at each pass
  attempted. Confidence is available per-pass via pass_history.
- **Context Field**: A piece of project metadata (e.g., maintainers,
  security contact) with a source (auto-detected, user-confirmed,
  user-provided), a confidence level (0.0–1.0), and the detection
  method used. Canonical sources (exact file matches) default to
  high confidence; heuristic inferences default to low. The
  acceptance threshold is configurable per-implementation in TOML.
- **Remediation Action**: A planned fix for a failing control,
  categorized as deterministic (template + context) or generative
  (template + LLM customization), with dry-run support.
- **Pass**: A single handler invocation in a control's cascade.
  Passes are ordered by convention from deterministic to heuristic
  to LLM to manual, each returning PASS/FAIL/ERROR (conclusive)
  or INCONCLUSIVE (continue to next pass).

## Clarifications

### Session 2026-03-08

- Q: How does the "heuristic" tier map to the existing sieve pipeline? → A: No new pipeline phase. The framework already supports arbitrary cascading passes in TOML declaration order. "Deterministic → heuristic → LLM → manual" is a conventional ordering pattern (decreasing confidence, increasing cost), not an enforced phase structure. This feature adds more passes to currently-manual controls following that convention.
- Q: Should the feature only convert manual → deterministic/heuristic, or also expand LLM usage? → A: Both. Add deterministic/heuristic passes where possible, and add LLM evaluation passes as a middle tier for controls where deterministic checks aren't feasible but an LLM can reason about content.
- Q: How should auto-detected context confidence be handled? → A: Two-tier default: canonical-source matches (CODEOWNERS, SECURITY.md) auto-accept, heuristic inferences require confirmation. But this MUST be configurable per-implementation via TOML with confidence levels, so implementers can express thresholds like ">80% auto-accepted" or force manual verification for all fields.

## Assumptions

- The existing sieve pipeline already supports cascading passes in
  TOML declaration order with INCONCLUSIVE fallthrough. This feature
  enhances coverage by adding new deterministic and heuristic passes
  to currently-manual controls, AND expanding LLM evaluation passes
  as a middle tier for controls where deterministic checks are not
  feasible but an LLM can reason about content quality or compliance.
- The `gh` CLI is the primary mechanism for GitHub API interaction,
  consistent with existing exec-handler patterns in the TOML config.
- LLM evaluation is available via the MCP server context (the tool
  is used within an AI assistant). Standalone CLI usage without an
  LLM degrades to the deterministic + heuristic tiers only.
- Organization-wide automation (auditing all repos in an org) is
  out of scope for this feature — it focuses on single-repo
  automation depth. Org-wide orchestration can layer on top.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The percentage of level 1 controls that produce a
  conclusive result (PASS or FAIL, not WARN) without user
  interaction increases from the current baseline (~62%) to at
  least 80%.
- **SC-002**: The percentage of level 2 controls that produce a
  conclusive result increases to at least 70%.
- **SC-003**: Project context collection auto-fills at least 75%
  of context fields for a typical open-source repository without
  user prompting.
- **SC-004**: Every control result includes resolving pass and
  evidence metadata — 100% of results are traceable to a specific
  evaluation method.
- **SC-005**: Deterministic remediations (file creation, API calls)
  execute without LLM involvement and complete within 30 seconds
  per control.
- **SC-006**: Users report that the audit-to-remediation workflow
  requires fewer manual steps than the current process.
