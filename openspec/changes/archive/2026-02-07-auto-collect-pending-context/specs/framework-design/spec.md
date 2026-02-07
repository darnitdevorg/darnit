## ADDED Requirements

### Requirement: Markdown audit output SHALL include structured agent directives

The `format_results_markdown()` function SHALL produce output that contains structured directives for LLM agents, not just informational content. The markdown output format SHALL include a "Next Steps" section at the end that provides ordered, actionable instructions with ready-to-execute tool calls.

This requirement adds a new subsection to the Output Formats specification (Section 8) covering the markdown output format consumed by LLM agents via MCP tools.

#### Scenario: Markdown output contains agent-actionable directives
- **WHEN** `format_results_markdown()` produces output with failures or pending context
- **THEN** the output SHALL end with a "Next Steps" section containing numbered directives with tool call syntax that the LLM agent can execute directly
