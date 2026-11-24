# pending-LLM parity fixture

Exercises `OSPS-DO-01.01`, which reaches a model judgment on this
repository. Under the MCP tool path (which never dispatches), the
control is left PENDING_LLM. Under the harness path with a
`MockLLMStep` returning `inconclusive`, it resolves to WARN. That
divergence is the sole documented allowed drift for Tier 1.

The README exists so the judgment step has content to reference.
