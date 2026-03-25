# Data Model: Detailed STRIDE Threat Modeling

**Branch**: `006-detailed-stride-threats` | **Date**: 2026-03-25

## Extended Entities

### Threat (extended)

Existing `Threat` dataclass in `models.py` gains new optional fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `exploitation_scenario` | `list[str]` | `[]` | Ordered steps describing how an attacker exploits this threat |
| `data_flow_impact` | `str` | `""` | Description of affected data flows (source → sink) |
| `ranked_controls` | `list[RankedControl]` | `[]` | Controls ordered by effectiveness with rationale |
| `attack_chain_ids` | `list[str]` | `[]` | IDs of attack chains this threat participates in |

**Backward compatibility**: All new fields have defaults. Existing code constructing `Threat` objects without these fields continues to work.

**Relationship to existing fields**:
- `recommended_controls: list[str]` — retained for backward compat; `ranked_controls` is the preferred field. When `ranked_controls` is populated, generators use it instead of `recommended_controls`.
- `attack_vector: str` — retained as-is. `exploitation_scenario` provides the expanded multi-step version.

### RankedControl (new)

| Field | Type | Description |
|-------|------|-------------|
| `control` | `str` | Control description (same format as existing `recommended_controls` entries) |
| `effectiveness` | `str` | One of: "high", "medium", "low" |
| `rationale` | `str` | Brief explanation of why this control is effective for this threat |

### AttackChain (new)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique ID, format: `TC-{NUMBER:03d}` |
| `name` | `str` | Human-readable chain name (e.g., "Credential Theft → Data Exfiltration") |
| `description` | `str` | How the chain works as a compound attack |
| `threat_ids` | `list[str]` | Ordered list of constituent threat IDs |
| `categories` | `list[StrideCategory]` | STRIDE categories involved |
| `shared_assets` | `list[str]` | Asset IDs that connect the threats |
| `composite_risk` | `RiskScore` | Combined risk score for the chain |

### ThreatAnalysis (extended)

Existing `ThreatAnalysis` dataclass gains:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `attack_chains` | `list[AttackChain]` | `[]` | Detected compound attack paths |

### DetailLevel (new enum)

| Value | Description |
|-------|-------------|
| `SUMMARY` | Minimal output: title, risk score, top control |
| `DETAILED` | Full output: scenarios, data flows, ranked controls, references (default) |

## Entity Relationships

```
ThreatAnalysis
├── threats: list[Threat]
│   ├── risk: RiskScore
│   ├── code_locations: list[CodeLocation]
│   ├── ranked_controls: list[RankedControl]  (NEW)
│   └── attack_chain_ids: list[str]           (NEW, references AttackChain.id)
├── attack_chains: list[AttackChain]          (NEW)
│   ├── threat_ids: list[str]                 (references Threat.id)
│   ├── shared_assets: list[str]              (references EntryPoint.id / DataStore.id)
│   └── composite_risk: RiskScore
└── control_gaps: list[dict]
```

## Validation Rules

- `Threat.exploitation_scenario`: When populated, MUST have >= 3 steps (per SC-001)
- `Threat.ranked_controls`: When populated, MUST be ordered by effectiveness (high → medium → low)
- `AttackChain.threat_ids`: MUST contain >= 2 threat IDs
- `AttackChain.categories`: MUST match a predefined STRIDE combination pattern
- `AttackChain.shared_assets`: MUST contain >= 1 asset ID (the tiebreaker requirement)
- `AttackChain.composite_risk.overall`: MUST be <= 1.0

## State Transitions

No state machines in this feature. All entities are constructed once during analysis and are immutable for the lifetime of the report generation.
