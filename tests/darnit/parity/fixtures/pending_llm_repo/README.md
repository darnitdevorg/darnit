# pending-LLM parity fixture

Exercises `STAGE1-REF-SECURITY-01`, whose first pass is a suggestive
`llm_extract` step. Under the MCP tool path (which never dispatches),
this control is left PENDING_LLM. Under the harness path with a
`MockLLMStep` returning `inconclusive`, it resolves to WARN. That
divergence is the sole documented allowed drift for Tier 1.

The README exists so the llm_extract step has content to reference.
No `SECURITY.md`, so a dispositive file_exists would FAIL if reached.
