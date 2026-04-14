# Threat Model Report

## Executive Summary

| Field | Value |
|-------|-------|
| Repository | `mlieberman85/darnit` |
| Scan date | 2026-04-14 11:20:00 |
| Languages | python, yaml |
| Total findings | 176 |
| Critical | 0 |
| High | 5 |
| Medium | 78 |
| Low | 93 |

## Top Risks

| Class | STRIDE | Instances | Severity | Mitigation |
|-------|--------|-----------|----------|------------|
| [Potential command injection via subprocess.run](findings/python-sink-dangerous_attr.md) | Tampering | 122 | HIGH | 122/122 |
| [Unauthenticated mcp tool (mcp): (dynamic — registered from registry.tools)](findings/python-entry-mcp_tool_imperative.md) | Spoofing | 2 | MEDIUM | 2/2 |
| [Dynamic import via importlib.import_module(module_path)](findings/python-eop-dynamic_import_attr.md) | Elevation of Privilege | 4 | MEDIUM | 4/4 |
| [File open with variable path: filepath](findings/python-info_disc-open_call.md) | Information Disclosure | 48 | MEDIUM | 48/48 |

## Unmitigated Findings

All findings have been mitigated, accepted, or marked as false positives.

## Companion Artefacts

- [Data Flow Diagram](data-flow.md)
- [Raw Findings (JSON)](raw-findings.json)

## Recommendations Summary

### Immediate Actions (Critical / High)

No critical or high severity findings requiring immediate action.

### Short-term Actions (Medium)

No medium severity findings.

## Verification Prompts

<!-- darnit:verification-prompt-block -->

**For the calling agent (Claude via MCP):** this summary was produced by the darnit tree-sitter discovery pipeline. Before committing, follow these steps:

1. Open each detail file under `findings/` and review the representative code snippets.
2. For each finding class, ask: does the code at these locations plausibly exhibit the described threat? If not, remove the detail file and its entry from this summary.
3. Refine narrative with project-specific details where helpful.
4. Preserve this `darnit:verification-prompt-block` section — it marks the draft as having gone through review.

<!-- /darnit:verification-prompt-block -->

## Limitations

- Scanned **182** in-scope files (python=137, yaml=45).
- Skipped **48** vendor/build directories and **381** files in unsupported languages.
- Opengrep taint analysis: available.

- **156** additional candidate findings were trimmed to fit the finding cap.

*This is a threat-modeling aid, not an exhaustive vulnerability scan. Use Kusari Inspector or an equivalent SAST tool for deeper coverage.*

