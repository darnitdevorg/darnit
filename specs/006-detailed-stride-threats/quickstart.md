# Quickstart: Detailed STRIDE Threat Modeling

**Branch**: `006-detailed-stride-threats` | **Date**: 2026-03-25

## What This Feature Changes

The `generate_threat_model` MCP tool produces richer output:
- Each threat includes a multi-step exploitation scenario and data-flow impact
- Controls are ranked by effectiveness with rationale
- Markdown reports include Mermaid data-flow diagrams
- An "Attack Chains" section identifies compound attack paths
- A new `detail_level` parameter toggles between "summary" and "detailed" (default)

## Files Modified

| File | Change |
|------|--------|
| `threat_model/models.py` | Add `RankedControl`, `AttackChain`, `DetailLevel`; extend `Threat` and `ThreatAnalysis` |
| `threat_model/scenarios.py` | **New file** — exploitation scenario templates per threat sub-type |
| `threat_model/chains.py` | **New file** — attack chain pattern definitions and detection logic |
| `threat_model/stride.py` | Populate new `Threat` fields (scenarios, data-flow impact, ranked controls) |
| `threat_model/generators.py` | Add DFD generation, detail_level rendering, attack chains section, empty category explanations |
| `threat_model/__init__.py` | Export new types and functions |
| `tools.py` | Add `detail_level` parameter to `generate_threat_model()` |

## Testing Strategy

| Test Area | Location | What to Test |
|-----------|----------|-------------|
| Scenario templates | `tests/darnit_baseline/threat_model/test_scenarios.py` | Each template has >=3 steps, all threat sub-types covered |
| Attack chain detection | `tests/darnit_baseline/threat_model/test_chains.py` | Pattern matching, shared-asset tiebreaker, composite risk formula |
| Markdown detail levels | `tests/darnit_baseline/threat_model/test_generators.py` | detailed vs summary output, Mermaid diagram presence, empty categories |
| Data model extensions | `tests/darnit_baseline/threat_model/test_models.py` | Backward compat (old construction still works), new field defaults |
| Integration | `tests/darnit_baseline/threat_model/test_integration.py` | End-to-end: `generate_threat_model()` with sample repo fixtures |

## Development Order

1. **Models** — extend dataclasses (no behavior change yet)
2. **Scenarios** — template bank + `get_scenario()` function
3. **Chains** — pattern definitions + `detect_attack_chains()` function
4. **Stride** — wire scenarios, data-flow impact, ranked controls into threat construction
5. **Generators** — Mermaid DFD, detail_level rendering, attack chains section
6. **Tools** — add `detail_level` parameter
7. **Tests** — unit tests for each new module, integration test for full pipeline

## Key Design Decisions

- **Templates, not LLM**: Scenarios are deterministic templates now; system designed for future LLM enrichment
- **Breaking change**: Default output is "detailed" — richer than before
- **Predefined chain patterns**: Attack chains use known STRIDE category combinations, not arbitrary asset overlap
- **Presentation-only detail_level**: Analysis always runs at full depth; detail_level only affects Markdown rendering
