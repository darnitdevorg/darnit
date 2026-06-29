## ADDED Requirements

### Requirement: Controls can declare ordering dependencies
A control MAY declare `depends_on` as a list of control IDs. The sieve orchestrator SHALL execute dependent controls only after their dependencies have been evaluated through the handler pipeline.

#### Scenario: Control B depends on control A
- **WHEN** control B declares `depends_on = ["CTRL-A"]`
- **THEN** the orchestrator SHALL evaluate CTRL-A before evaluating control B

#### Scenario: Dependency fails
- **WHEN** control B depends on CTRL-A
- **AND** CTRL-A produces a FAIL result
- **THEN** control B SHALL still be evaluated normally
- **AND** the dependency result SHALL be available in control B's evidence as `dependency.CTRL-A.status`

#### Scenario: Circular dependency detected
- **WHEN** control A depends on control B and control B depends on control A
- **THEN** the framework SHALL log a warning
- **AND** SHALL evaluate both controls in their natural order (ignoring the cycle)

### Requirement: Controls can declare logical inference from another control
A control MAY declare `inferred_from` as a single control ID. When the referenced control PASSES, the declaring control SHALL automatically PASS with a message indicating the inference, WITHOUT running its own handler pipeline.

#### Scenario: Inferred control passes because source passes
- **WHEN** control OSPS-LE-03.02 declares `inferred_from = "OSPS-LE-03.01"`
- **AND** OSPS-LE-03.01 produces a PASS result
- **THEN** OSPS-LE-03.02 SHALL produce a PASS result
- **AND** the result message SHALL indicate it was inferred from OSPS-LE-03.01
- **AND** the result evidence SHALL include `inferred_from = "OSPS-LE-03.01"`

#### Scenario: Inferred control runs normally when source does not pass
- **WHEN** control OSPS-LE-03.02 declares `inferred_from = "OSPS-LE-03.01"`
- **AND** OSPS-LE-03.01 produces a FAIL or WARN result
- **THEN** OSPS-LE-03.02 SHALL run its own handler pipeline normally

#### Scenario: Inferred_from implies depends_on
- **WHEN** a control declares `inferred_from = "CTRL-A"`
- **THEN** the orchestrator SHALL treat this as an implicit `depends_on = ["CTRL-A"]`
- **AND** SHALL evaluate CTRL-A before evaluating the declaring control

### Requirement: Dependencies reference only controls within the same audit
A control's `depends_on` and `inferred_from` SHALL only reference control IDs that are part of the current audit scope (same level filter). If a referenced control is not in scope, the dependency SHALL be ignored with a debug-level log message.

#### Scenario: Dependency target filtered out by level
- **WHEN** control B at level 2 declares `depends_on = ["CTRL-A"]`
- **AND** CTRL-A is a level 3 control
- **AND** the audit runs at level 2
- **THEN** the dependency on CTRL-A SHALL be ignored
- **AND** control B SHALL be evaluated normally
