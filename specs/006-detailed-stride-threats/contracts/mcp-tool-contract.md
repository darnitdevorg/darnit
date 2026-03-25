# MCP Tool Contract: generate_threat_model

**Branch**: `006-detailed-stride-threats` | **Date**: 2026-03-25

## Updated Signature

```python
def generate_threat_model(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    output_format: str = "markdown",   # "markdown", "sarif", "json"
    output_path: str | None = None,
    detail_level: str = "detailed",    # NEW: "summary" or "detailed"
) -> str
```

## New Parameter: `detail_level`

| Value | Behavior |
|-------|----------|
| `"detailed"` (default) | Full output: exploitation scenarios, data-flow impact, ranked controls, attack chains, Mermaid DFD |
| `"summary"` | Minimal output: threat title, risk score, top control per threat. No diagrams, no attack chains section |

**Scope**: Only affects Markdown output. SARIF and JSON always include all fields regardless of `detail_level`.

## Output Format Changes

### Markdown (detail_level="detailed")

New sections added to report:
1. **Data Flow Diagram** — Mermaid flowchart after Asset Inventory section
2. **Exploitation Scenario** — per-threat sub-section with numbered steps
3. **Data Flow Impact** — per-threat line identifying affected flows
4. **Ranked Controls** — per-threat table replacing flat control list
5. **Attack Chains** — new top-level section after STRIDE Threats
6. **Empty Category Explanations** — STRIDE categories with no findings explain what was checked

### Markdown (detail_level="summary")

Per-threat output reduced to:
- Threat title
- Risk score and level
- Top recommended control (single line)

No data flow diagrams, no attack chains section.

### SARIF

Existing SARIF structure unchanged. New fields added to rule properties:
- `exploitationScenario`: array of step strings
- `dataFlowImpact`: string
- `rankedControls`: array of {control, effectiveness, rationale}
- `attackChainIds`: array of chain ID strings

New `run.properties.attackChains` array with chain objects.

### JSON

Existing JSON structure unchanged. New fields added per threat:
- `exploitation_scenario`: array of step strings
- `data_flow_impact`: string
- `ranked_controls`: array of {control, effectiveness, rationale}
- `attack_chain_ids`: array of chain IDs

New top-level `attack_chains` array.

## Error Behavior

- Invalid `detail_level` value: ignored, falls back to "detailed"
- No assets discovered: report states "No assets discovered" with manual review suggestion (all formats)
- >50 diagram nodes: diagram simplified to high-risk paths with explanatory note
- >10 findings per category: grouped and summarized with representative examples
