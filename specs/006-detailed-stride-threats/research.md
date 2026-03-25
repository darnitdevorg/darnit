# Research: Detailed STRIDE Threat Modeling

**Branch**: `006-detailed-stride-threats` | **Date**: 2026-03-25

## R1: Exploitation Scenario Templates — Structure and Content

**Decision**: Each STRIDE category gets a bank of scenario templates keyed by threat sub-type. Templates are Python dicts with ordered step lists and placeholder tokens for asset names.

**Rationale**: The existing `analyze_stride_threats()` already creates threats per sub-type (unauthenticated endpoints, hardcoded secrets, injection sinks, etc.). Each sub-type has a predictable attack pattern. Templates map 1:1 to these sub-types, keeping generation deterministic and testable. A future LLM enrichment layer can replace or augment individual templates without changing the `Threat` dataclass or generator interfaces.

**Alternatives considered**:
- Dynamic composition from asset graph — rejected (non-deterministic, hard to test, noisy output)
- LLM-generated scenarios at runtime — rejected for this iteration (latency, cost, non-determinism); template system designed to accommodate it later via a pluggable `ScenarioProvider` interface

## R2: Data Flow Diagram Generation from AssetInventory

**Decision**: Build a `generate_mermaid_dfd()` function that takes an `AssetInventory` and `list[Threat]` and produces a Mermaid `flowchart LR` string. External actors are inferred from entry point types. Trust boundaries use Mermaid `subgraph` blocks to separate authenticated/unauthenticated zones.

**Rationale**: The `AssetInventory` already contains entry points (with `authentication_required`), data stores, and auth mechanisms — all the ingredients for a DFD. Mermaid `flowchart LR` is well-supported in GitHub-rendered Markdown and allows subgraphs for trust boundaries. No external dependencies needed.

**Alternatives considered**:
- ASCII art diagrams — rejected (poor readability, no rendering support)
- Graphviz DOT — rejected (requires external tool, not rendered by GitHub)
- Mermaid `graph TD` — rejected in favor of `flowchart LR` for better left-to-right data flow visualization

## R3: Attack Chain Pattern Definitions

**Decision**: Define a `CHAIN_PATTERNS` dict mapping pairs of `StrideCategory` values to chain descriptors (name, description, combined risk formula). Chains are emitted only when both categories have threats AND at least one shared asset (entry point, data store, or code file).

**Rationale**: Well-known STRIDE combinations (e.g., Spoofing + Information Disclosure = credential theft + data exfiltration, Tampering + Elevation of Privilege = input manipulation + privilege escalation) are documented in threat modeling literature. Predefined patterns are deterministic, testable, and avoid the false-positive noise of pure asset-overlap detection.

**Initial chain patterns**:
| Pattern | Categories | Typical Scenario |
|---------|-----------|-----------------|
| Credential Theft → Data Exfiltration | S + I | Spoofed identity accesses sensitive data |
| Input Manipulation → Privilege Escalation | T + E | Tampered input bypasses authorization |
| Repudiation + Information Disclosure | R + I | Unlogged access to sensitive data |
| Denial of Service + Tampering | D + T | Resource exhaustion enables data corruption |
| Spoofing + Elevation of Privilege | S + E | Unauthenticated access gains admin rights |

**Alternatives considered**:
- Full attack tree solver — rejected (over-engineered for static analysis tool)
- Pure asset-overlap — rejected (too noisy; "same file" doesn't mean chainable)

## R4: Composite Risk Score for Attack Chains

**Decision**: Composite risk = `max(individual_scores) + 0.1 * sum(other_scores)`, capped at 1.0. This reflects that the chain's risk is dominated by the highest-risk threat but amplified by supporting threats.

**Rationale**: Simple, deterministic, and produces intuitive results: a CRITICAL + MEDIUM chain scores higher than CRITICAL alone but doesn't exceed 1.0. The formula is easy to explain in the report's methodology section.

**Alternatives considered**:
- Multiplicative (score1 × score2) — rejected (produces unintuitive small numbers for two medium threats)
- Additive (sum / count) — rejected (averages down, doesn't capture amplification)
- CVSS-style temporal scoring — rejected (over-complex for this use case)

## R5: detail_level Parameter — Scope of Impact

**Decision**: `detail_level` is a Markdown rendering concern only. The `generate_threat_model()` MCP tool accepts it as a new optional parameter. Internally, all analysis runs at full depth. The Markdown generator checks `detail_level` to decide what to render. SARIF and JSON generators ignore it.

**Rationale**: Keeps analysis logic clean — no conditional paths in `analyze_stride_threats()`. The summary view is purely a presentation concern. This also means SARIF/JSON consumers always get full data regardless.

**Alternatives considered**:
- Short-circuit analysis for summary mode — rejected (saves negligible time, adds complexity)
- Separate tool parameter vs. output_format suffix — rejected (parameter is cleaner)

## R6: Backward Compatibility Strategy

**Decision**: Breaking change accepted (per clarification). The default output is "detailed" which includes new fields (exploitation scenario, data-flow impact, ranked controls). Existing consumers of the Markdown output will see richer content. The `Threat` dataclass gets new optional fields with defaults so existing code constructing `Threat` objects doesn't break.

**Rationale**: The whole point of this feature is richer default output. New fields on `Threat` use `field(default_factory=list)` or `default=""` so they're backward-compatible at the Python API level.

**Alternatives considered**:
- Versioned output format — rejected (over-engineering for a tool that generates on-demand reports)

## R7: Extensibility for Future LLM Enrichment

**Decision**: Scenario templates are stored in a module-level dict (`SCENARIO_TEMPLATES`) in a new `scenarios.py` file. A `get_scenario()` function takes a threat sub-type and returns the template. This function is the extension point — a future LLM integration would replace or wrap it.

**Rationale**: Single function as extension point is the simplest possible design. No abstract base classes, no plugin system — just a function that returns a dict. When LLM enrichment is added, `get_scenario()` can be made async or accept an optional enrichment callback.

**Alternatives considered**:
- Abstract `ScenarioProvider` class — rejected (YAGNI; a function is sufficient)
- Config-driven template selection — rejected (templates are code, not config)
