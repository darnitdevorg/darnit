## ADDED Requirements

### Requirement: LLM directive footer on get_pending_context
The `get_pending_context` tool SHALL append a plaintext LLM directive block after the JSON payload to constrain calling-LLM behavior.

#### Scenario: Directive appended to response
- **WHEN** `get_pending_context` returns pending context questions
- **THEN** the response string SHALL end with a plaintext directive block after the JSON
- **AND** the directive SHALL instruct the caller to present the question using the exact `prompt` text
- **AND** the directive SHALL forbid batching multiple questions into a single message
- **AND** the directive SHALL forbid using markdown checkboxes, tables, or other formatting
- **AND** the directive SHALL forbid paraphrasing or rewording the prompt text

#### Scenario: Directive not appended when no pending context
- **WHEN** `get_pending_context` returns no pending questions (status: "complete")
- **THEN** the response SHALL NOT include the directive block

#### Scenario: Directive includes next-step instruction
- **WHEN** the directive block is appended
- **THEN** it SHALL instruct the caller to call `confirm_project_context` with the user's answer
- **AND** it SHALL instruct the caller to call `get_pending_context` again for the next question

### Requirement: Hardened get_pending_context docstring
The MCP tool docstring for `get_pending_context` SHALL define a behavioral contract for LLM callers, not merely describe the return format.

#### Scenario: Docstring defines sequential usage
- **WHEN** the `get_pending_context` tool description is read by an LLM
- **THEN** the docstring SHALL state that the tool returns one question at a time by default
- **AND** SHALL state that the caller MUST present the question using the exact `prompt` text from the response
- **AND** SHALL state that the caller MUST NOT batch, paraphrase, or use markdown formatting
- **AND** SHALL describe the loop: call `get_pending_context` → present question → call `confirm_project_context` → repeat

### Requirement: Presentation hint included in question payload
The `get_pending_context` question JSON SHALL include `presentation_hint` when available, so the calling LLM knows the exact format to use.

#### Scenario: Boolean question includes hint
- **WHEN** a pending context item has type `boolean`
- **THEN** the question JSON SHALL include `"presentation_hint": "[y/N]"` (or the explicitly configured hint)
- **AND** the calling LLM SHALL use this hint when formatting the prompt

#### Scenario: Enum question includes hint
- **WHEN** a pending context item has type `enum`
- **AND** the definition has `allowed_values` or `values`
- **THEN** the question JSON SHALL include a `presentation_hint` (explicit or auto-generated)

#### Scenario: Free text question with no hint
- **WHEN** a pending context item has type `string` and no `presentation_hint` is configured
- **THEN** the question JSON SHALL NOT include a `presentation_hint` field (or it SHALL be `null`)
