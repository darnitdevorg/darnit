## ADDED Requirements

### Requirement: Audit output SHALL include a Next Steps section with ordered agent directives

The `format_results_markdown()` function SHALL append a "Next Steps" section after the audit results. This section SHALL contain numbered directives that tell the LLM agent exactly what to do, in order, removing ambiguity about the post-audit flow.

The Next Steps section SHALL follow this structure:
1. **Collect pending context** (if any exists) — imperative directive with tool calls
2. **Remediate failures** (if any exist) — directive to run remediation
3. **Review manual controls** (if WARN results exist) — brief note

If no pending context exists, the section SHALL skip step 1 and begin with remediation.

#### Scenario: Audit with pending context and failures
- **WHEN** audit completes with both pending context items and failed controls
- **THEN** the Next Steps section SHALL list context collection as step 1, directing the agent to `get_pending_data()` with the number of items needed, followed by remediation as step 2

#### Scenario: Audit with failures but no pending context
- **WHEN** audit completes with failed controls but all context is already confirmed
- **THEN** the Next Steps section SHALL begin with remediation directives (no context collection step)

#### Scenario: Audit with no failures and no pending context
- **WHEN** audit completes with all controls passing and no pending context
- **THEN** the Next Steps section SHALL NOT appear

### Requirement: Pending context SHALL be referenced, never pre-filled

When pending context exists, the audit output SHALL state how many items are needed and direct the agent to `get_pending_data()`, which presents each question with any detected value as a labelled, unconfirmed candidate (feature 042; framework-design.md 7.10). The audit output SHALL NOT contain a detected or example value inside a tool call, and SHALL NOT group detected values into a single confirmation call.

#### Scenario: Auto-detected context value available
- **WHEN** a pending context item has a candidate from the context sieve
- **THEN** the audit output SHALL NOT include the candidate's value in any tool call
- **AND** `get_pending_data()` SHALL present it as `candidate` data with its origin and digest

#### Scenario: No auto-detected value available
- **WHEN** a pending context item has no candidate
- **THEN** `get_pending_data()` SHALL present the prompt text from the TOML definition, directing the agent to ask the user

### Requirement: Context collection directive SHALL instruct the agent to re-audit after confirmation

After the pending context tool calls, the output SHALL include a directive telling the agent to re-run the audit after context is confirmed. This ensures the user gets an updated, more accurate result.

#### Scenario: Agent follows context collection flow
- **WHEN** the LLM agent reads the Next Steps section with pending context
- **THEN** the directive SHALL tell the agent to: (1) call `get_pending_data()` and present each question and candidate to the user, (2) call `confirm_project_data()` only with the user's answers, (3) re-run `audit_openssf_baseline()` to get updated results

### Requirement: The legacy "Help Improve This Audit" section SHALL be removed

The `_get_pending_context_section()` function currently produces a "Help Improve This Audit" section with informational bullets. This section SHALL be replaced entirely by the new Next Steps context collection directives. The old section title and format SHALL NOT appear in audit output.

#### Scenario: Audit output format
- **WHEN** an audit completes with pending context
- **THEN** the output SHALL NOT contain a section titled "Help Improve This Audit"
- **THEN** the output SHALL contain the new Next Steps section with context collection directives
