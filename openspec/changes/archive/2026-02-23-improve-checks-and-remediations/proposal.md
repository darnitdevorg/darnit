# Proposal: Strengthen Baseline Checks & Remediations

## Problem Statement

Many OpenSSF Baseline controls only verify file existence, not content quality. A SECURITY.md containing just "TODO" currently passes. Eight remediation templates consist of >40% TODO placeholders. The `llm_eval` handler is fully implemented and wired into the orchestrator and MCP layer, but zero controls use it.

This creates two problems:
1. **False compliance**: Repos with stub files appear compliant when they aren't
2. **Useless remediations**: Generated files need immediate manual rewriting

## Goals

1. **Checks validate content structure, not just file presence** — strengthen regex passes to require substantive content, and add llm_eval passes for nuanced quality judgment on 5 high-value controls
2. **Remediations produce useful files** — rewrite TODO-heavy templates with real default content, and add `llm_enhance` metadata for AI-assisted customization
3. **Wire `files_to_include`** — the spec already defines this field for llm_eval but the handler ignores it; implement file content injection

## Impact

- 8 controls get stronger regex patterns (may cause currently-passing stubs to fall through to llm_eval/WARN — correct per conservative-by-default)
- 5 controls gain llm_eval passes for AI-assisted content quality checking
- 5 remediation templates rewritten from TODO stubs to substantive defaults
- No breaking changes to framework APIs or plugin protocol
- `llm_eval` only fires when regex is inconclusive — repos with real content still pass at regex level with no added latency
