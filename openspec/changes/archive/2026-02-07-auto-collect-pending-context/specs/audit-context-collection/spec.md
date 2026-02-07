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
- **THEN** the Next Steps section SHALL list context collection as step 1 with ready-to-execute `confirm_project_context()` calls, followed by remediation as step 2

#### Scenario: Audit with failures but no pending context
- **WHEN** audit completes with failed controls but all context is already confirmed
- **THEN** the Next Steps section SHALL begin with remediation directives (no context collection step)

#### Scenario: Audit with no failures and no pending context
- **WHEN** audit completes with all controls passing and no pending context
- **THEN** the Next Steps section SHALL NOT appear

### Requirement: Pending context SHALL be presented as ready-to-execute tool calls

When pending context exists, the audit output SHALL present each pending item as a `confirm_project_context()` call that the LLM agent can execute directly or present to the user for confirmation. The output SHALL NOT present context as informational bullets or questions.

Each tool call SHALL include:
- The context key name as a parameter
- A pre-filled value if auto-detected (from context sieve)
- A placeholder with the prompt text if no auto-detection is available

#### Scenario: Auto-detected context value available
- **WHEN** a pending context item has an auto-detected value from the context sieve
- **THEN** the output SHALL show a `confirm_project_context()` call with the detected value pre-filled and a note indicating it was auto-detected

#### Scenario: No auto-detected value available
- **WHEN** a pending context item has no auto-detected value
- **THEN** the output SHALL show a `confirm_project_context()` call with a placeholder and the prompt text from the TOML definition, directing the agent to ask the user

### Requirement: Pending context SHALL be grouped by confidence level

The pending context section SHALL group items into two tiers:
1. **Auto-detected (confirm or correct)**: Items where sieve detection found a value. These SHALL be presented as a single compound `confirm_project_context()` call with all auto-detected values pre-filled.
2. **Needs user input**: Items where no auto-detection is available. These SHALL be listed individually with their prompt text.

The auto-detected group SHALL appear first since it requires less user effort (just confirmation).

#### Scenario: Mixed auto-detected and unknown context
- **WHEN** pending context includes 2 auto-detected items and 1 unknown item
- **THEN** the output SHALL show the 2 auto-detected items as a single compound tool call first, followed by the unknown item with its prompt

#### Scenario: All context is auto-detected
- **WHEN** all pending context items have auto-detected values
- **THEN** the output SHALL show a single compound `confirm_project_context()` call with all values, and a directive for the agent to execute it after user confirmation

### Requirement: Context collection directive SHALL instruct the agent to re-audit after confirmation

After the pending context tool calls, the output SHALL include a directive telling the agent to re-run the audit after context is confirmed. This ensures the user gets an updated, more accurate result.

#### Scenario: Agent follows context collection flow
- **WHEN** the LLM agent reads the Next Steps section with pending context
- **THEN** the directive SHALL tell the agent to: (1) present the auto-detected values for user confirmation, (2) call `confirm_project_context()`, (3) re-run `audit_openssf_baseline()` to get updated results

### Requirement: The legacy "Help Improve This Audit" section SHALL be removed

The `_get_pending_context_section()` function currently produces a "Help Improve This Audit" section with informational bullets. This section SHALL be replaced entirely by the new Next Steps context collection directives. The old section title and format SHALL NOT appear in audit output.

#### Scenario: Audit output format
- **WHEN** an audit completes with pending context
- **THEN** the output SHALL NOT contain a section titled "Help Improve This Audit"
- **THEN** the output SHALL contain the new Next Steps section with context collection directives
