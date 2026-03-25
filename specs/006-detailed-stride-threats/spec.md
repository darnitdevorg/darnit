# Feature Specification: Detailed STRIDE Threat Modeling

**Feature Branch**: `006-detailed-stride-threats`
**Created**: 2026-03-24
**Status**: Draft
**Input**: User description: "Can we update the stride threat modeling for baseline to go into a bit more detail if need be?"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Richer Threat Descriptions Per Category (Priority: P1)

As a security reviewer running the `generate_threat_model` tool, I want each STRIDE threat to include expanded detail — including realistic exploitation scenarios, affected data flows, and prioritized mitigation steps — so that I can act on the findings without needing to cross-reference external threat catalogs.

**Why this priority**: The core value of this feature. Currently, threats contain a title, short description, and a flat list of recommended controls. Reviewers must look elsewhere for context on *how* an attack would unfold and *which* control to implement first.

**Independent Test**: Run `generate_threat_model` against a sample repository and verify that each threat entry contains an exploitation scenario, data-flow impact description, and controls ranked by effectiveness.

**Acceptance Scenarios**:

1. **Given** a repository with unauthenticated API endpoints, **When** `generate_threat_model` runs, **Then** the Spoofing threat includes a step-by-step exploitation scenario, identifies the affected data flow (e.g., "client → unauthenticated endpoint → database"), and lists controls in priority order.
2. **Given** a repository with hardcoded secrets, **When** `generate_threat_model` runs, **Then** the Information Disclosure threat describes the realistic attack path (source code leak → secret extraction → lateral movement) and recommends controls ranked by effectiveness.
3. **Given** a repository with no discovered threats in a STRIDE category, **When** `generate_threat_model` runs, **Then** that category section still appears with an explanation of what was checked and why no threats were found.

---

### User Story 2 - Data Flow Diagrams in Markdown Output (Priority: P2)

As a security reviewer, I want the Markdown threat model report to include Mermaid data-flow diagrams showing how assets (entry points, data stores, trust boundaries) relate to each other, so that I can visually understand the attack surface.

**Why this priority**: Visual data-flow context makes threat reports significantly more actionable. Without it, reviewers must mentally reconstruct the system topology from individual threat entries.

**Independent Test**: Run `generate_threat_model` with `output_format=markdown` and verify the output contains at least one data-flow diagram showing entry points, data stores, and trust boundaries.

**Acceptance Scenarios**:

1. **Given** a repository with discovered entry points and data stores, **When** the Markdown report is generated, **Then** a data-flow diagram (Mermaid syntax) appears in the report showing connections between entry points, data stores, and external actors.
2. **Given** a repository where authentication mechanisms are detected, **When** the Markdown report is generated, **Then** trust boundaries are shown in the diagram separating authenticated from unauthenticated zones.

---

### User Story 3 - Configurable Detail Level (Priority: P2)

As a user invoking the threat model tool, I want to control the level of detail in the output (e.g., summary vs. detailed) so that I can get a quick overview or a deep-dive depending on my needs.

**Why this priority**: Different audiences need different depths. A quick triage may only need summary-level output, while a formal security review needs maximum detail.

**Independent Test**: Invoke `generate_threat_model` with a `detail_level` parameter set to "summary" and then "detailed", and verify the outputs differ in depth.

**Acceptance Scenarios**:

1. **Given** the tool is invoked with `detail_level=summary`, **When** the report generates, **Then** each threat shows only title, risk score, and top recommended control.
2. **Given** the tool is invoked with `detail_level=detailed` (or the default), **When** the report generates, **Then** each threat includes the full exploitation scenario, data-flow impact, all ranked controls, and references.
3. **Given** the tool is invoked without specifying `detail_level`, **When** the report generates, **Then** the default behavior produces the detailed output.

---

### User Story 4 - Cross-Threat Correlation and Attack Chains (Priority: P3)

As a security reviewer, I want the threat model to identify when multiple individual threats can be chained together into a compound attack, so that I can prioritize threats that are more dangerous in combination than in isolation.

**Why this priority**: Individual medium-severity threats can combine into critical attack paths. Identifying these chains greatly improves remediation prioritization.

**Independent Test**: Run `generate_threat_model` against a repository with both unauthenticated endpoints and hardcoded secrets, and verify the report identifies the combined attack chain.

**Acceptance Scenarios**:

1. **Given** a repository with an unauthenticated endpoint (Spoofing) and hardcoded API keys (Information Disclosure), **When** the report generates, **Then** an "Attack Chains" section identifies the combined risk: "Unauthenticated access + leaked API key → unauthorized data access" with a composite risk score.
2. **Given** a repository with only isolated, low-severity threats, **When** the report generates, **Then** the "Attack Chains" section states that no compound attack paths were identified.

---

### Edge Cases

- What happens when the repository has no discoverable assets (no entry points, no data stores, no secrets)? The report should clearly state that no assets were discovered and suggest manual review.
- What happens when a threat category has hundreds of findings (e.g., many hardcoded secrets)? Findings should be grouped and summarized with representative examples, not listed individually to avoid report bloat.
- What happens when the Mermaid diagram would be too large (50+ nodes)? The diagram should be simplified to show only high-risk paths, with a note that the full inventory is available in the asset table.
- How does the detail level parameter interact with non-Markdown output formats (SARIF, JSON)? SARIF and JSON always include full structured data regardless of detail level; the parameter only affects Markdown rendering.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each threat entry MUST include a multi-step exploitation scenario describing how an attacker would exploit the vulnerability. Scenarios are generated from predefined templates per threat type (deterministic and testable). The template system MUST be designed to allow future enrichment via LLM input without changing the public interface.
- **FR-002**: Each threat entry MUST include a data-flow impact description identifying which data flows (source → sink) are affected.
- **FR-003**: Recommended controls for each threat MUST be ordered by effectiveness (most effective first) with a brief rationale for each.
- **FR-004**: The Markdown output MUST include at least one Mermaid data-flow diagram showing entry points, data stores, trust boundaries, and external actors.
- **FR-005**: The `generate_threat_model` tool MUST accept a `detail_level` parameter with values "summary" and "detailed", defaulting to "detailed". This is an intentional breaking change from the current output format; the richer default is the primary value of this feature.
- **FR-006**: When `detail_level=summary`, the Markdown output MUST show only threat title, risk score, and top recommended control per threat.
- **FR-007**: The report MUST include an "Attack Chains" section identifying compound attack paths when multiple threats can be chained. Chains are identified using predefined STRIDE category combination patterns (e.g., Spoofing + Information Disclosure, Tampering + Elevation of Privilege) with a shared-asset tiebreaker to confirm relevance.
- **FR-008**: Attack chains MUST include a composite risk score derived from the individual threats' scores and their combinability.
- **FR-009**: When a STRIDE category has no findings, the report MUST still include that category with an explanation of what was checked.
- **FR-010**: When a single category has more than 10 findings, findings MUST be grouped and summarized with representative examples.
- **FR-011**: SARIF and JSON output formats MUST include all detailed fields regardless of the `detail_level` parameter.
- **FR-012**: Mermaid diagrams with more than 50 nodes MUST be simplified to show only high-risk paths with a note about the full asset inventory.

### Key Entities

- **Threat**: Extended with exploitation scenario, data-flow impact, ranked controls with rationale, and attack-chain references.
- **AttackChain**: A new entity representing a sequence of chained threats with a composite risk score, description, and references to constituent threats.
- **DataFlowDiagram**: A representation of system topology including entry points, data stores, trust boundaries, and external actors for visual rendering.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every generated threat entry contains an exploitation scenario of at least 3 steps and a data-flow impact statement.
- **SC-002**: Recommended controls are presented in ranked order with rationale for 100% of threats in the report.
- **SC-003**: Markdown reports include at least one data-flow diagram when entry points and data stores are both discovered.
- **SC-004**: Attack chains are identified when predefined STRIDE category combination patterns match AND constituent threats share at least one asset.
- **SC-005**: Summary-mode reports are at most 40% the length of detailed-mode reports for the same repository.
- **SC-006**: All existing tests continue to pass — no regressions in current threat model functionality.
- **SC-007**: Reports for repositories with 50+ threats complete generation within the same order of magnitude as current performance.

## Clarifications

### Session 2026-03-25

- Q: Should the default `detail_level` preserve current output (non-breaking) or default to "detailed" (breaking change)? → A: Default to "detailed" — breaking change accepted. Richer output is the point of this feature; users wanting brevity can opt into summary mode.
- Q: How are exploitation scenarios generated — templates, dynamic composition, or hybrid? → A: Predefined templates per threat type (deterministic, testable). Template system must be extensible to allow future LLM enrichment without changing the public interface.
- Q: What makes two threats "chainable" for attack chain detection? → A: Predefined STRIDE category combination patterns (e.g., S+I, T+E) with shared-asset tiebreaker to confirm relevance. No asset-overlap-only detection (too noisy).

## Assumptions

- The existing `ThreatAnalysis`, `Threat`, and related data models in `models.py` can be extended without breaking backward compatibility.
- Mermaid syntax is acceptable for diagrams since the project already uses GitHub-Flavored Markdown with Mermaid support (per CLAUDE.md active technologies).
- The `detail_level` parameter is a presentation concern — all analysis runs at full depth regardless, and detail level only controls what is rendered in Markdown.
- Attack chain detection uses predefined STRIDE category combination patterns with shared-asset tiebreakers rather than requiring a formal attack-tree solver or pure asset-overlap heuristics.

## Scope Boundaries

**In scope**:
- Enhancing threat detail in all 6 STRIDE categories
- Adding data-flow diagrams to Markdown output
- Adding `detail_level` parameter to the MCP tool
- Adding attack chain detection and reporting
- Updating SARIF and JSON generators to include new fields

**Out of scope**:
- Changing the risk scoring algorithm (existing `calculate_risk_score` is unchanged)
- Adding new detection patterns to `patterns.py` (existing pattern library is sufficient)
- Interactive/conversational threat modeling workflows
- Integration with external threat intelligence feeds
- LLM-based scenario enrichment (future enhancement; template system must accommodate it but this feature ships with templates only)
