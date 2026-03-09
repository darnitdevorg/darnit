# Contract: SieveResult Extensions

**Date**: 2026-03-08
**Scope**: Additions to SieveResult for pass-level traceability.

## New Fields on SieveResult

```python
@dataclass
class SieveResult:
    # Existing fields (unchanged)
    status: str              # PASS, FAIL, WARN, ERROR, PENDING_LLM
    evidence: dict           # Accumulated evidence from all passes
    conclusive_phase: str    # Legacy phase name (kept for compat)
    pass_history: list[dict] # Per-pass results in cascade order

    # New fields
    resolving_pass_index: int | None = None
    # 0-based index into handler_invocations of the pass that
    # produced the conclusive result. None if no pass was conclusive.

    resolving_pass_handler: str | None = None
    # Handler name of the resolving pass (e.g., "exec", "pattern",
    # "llm_eval"). Populated from handler_invocations[resolving_pass_index].
```

## Orchestrator Changes

In the handler cascade loop, when a conclusive result is found:

```python
for i, invocation in enumerate(handler_invocations):
    result = dispatch(invocation, context)
    pass_history.append({"index": i, "handler": invocation.handler, ...})

    if result.status in ("PASS", "FAIL", "ERROR"):
        return SieveResult(
            status=result.status,
            evidence=accumulated_evidence,
            resolving_pass_index=i,
            resolving_pass_handler=invocation.handler,
            pass_history=pass_history,
            ...
        )

# No conclusive result
return SieveResult(
    status="WARN",
    resolving_pass_index=None,
    resolving_pass_handler=None,
    pass_history=pass_history,
    ...
)
```

## Consumer Impact

- **Formatters** (Markdown, JSON, SARIF): Can display which pass
  resolved each control and what evidence it used.
- **MCP tools**: Can include resolving pass info in audit responses.
- **Attestation**: Can include pass-level provenance in attestations.

## Backward Compatibility

- New fields default to None, so existing code that doesn't use
  them is unaffected.
- `conclusive_phase` is preserved for backward compatibility.
- `pass_history` structure unchanged — existing entries still work.
