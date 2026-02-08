## ADDED Requirements

### Requirement: Report formatter accepts implementation-provided branding
The `format_results_markdown()` function SHALL accept optional `report_title` and `remediation_map` parameters so that implementations can customize the report without modifying the framework.

#### Scenario: Default report title when none provided
- **WHEN** `format_results_markdown()` is called without `report_title`
- **THEN** the report SHALL use a generic title: "# Compliance Audit Report"

#### Scenario: Implementation provides custom report title
- **WHEN** `format_results_markdown()` is called with `report_title="OpenSSF Baseline Audit Report"`
- **THEN** the report SHALL use that title as the H1 heading

### Requirement: Remediation map is implementation-provided
The framework SHALL NOT contain hardcoded control-ID-to-tool mappings. Implementations SHALL provide remediation suggestions via a `remediation_map` parameter.

#### Scenario: Implementation provides remediation map
- **WHEN** `format_results_markdown()` is called with a `remediation_map` containing `{"OSPS-AC-03.01": {"tool": "enable_branch_protection", "description": "Configure branch protection"}}`
- **AND** the audit results contain a FAIL for `OSPS-AC-03.01`
- **THEN** the report SHALL include the `enable_branch_protection` tool suggestion

#### Scenario: No remediation map provided
- **WHEN** `format_results_markdown()` is called without `remediation_map`
- **AND** there are FAIL results
- **THEN** the report SHALL show the generic remediation section without tool-specific suggestions

#### Scenario: No OSPS control IDs in framework code
- **WHEN** searching the `packages/darnit/` source tree for `OSPS-` string literals
- **THEN** zero matches SHALL be found (excluding test fixtures and comments)

### Requirement: Git workflow defaults are parameterizable
The framework git operations SHALL accept branch name and branding as parameters rather than hardcoding implementation-specific values.

#### Scenario: Default branch name is generic
- **WHEN** `create_remediation_branch()` is called without specifying a branch name
- **THEN** the default branch name SHALL be `fix/compliance` (not `fix/openssf-baseline-compliance`)

#### Scenario: Implementation overrides branch name default
- **WHEN** darnit-baseline's TOML config specifies a default branch name
- **THEN** the implementation's branch name SHALL be used as the default
