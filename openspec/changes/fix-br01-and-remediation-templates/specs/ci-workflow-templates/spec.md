## ADDED Requirements

### Requirement: Remediation templates must not introduce security findings
All CI workflow templates SHALL be hardened so that generated files do not introduce high-severity findings when scanned by workflow security tools (e.g., zizmor, actionlint).

#### Scenario: Templates use persist-credentials false
- **WHEN** any CI workflow template includes an `actions/checkout` step
- **THEN** the step SHALL include `persist-credentials: false` to prevent credential leakage via artifacts

#### Scenario: Templates do not use expressions in run blocks
- **WHEN** any CI workflow template includes a `run:` block
- **THEN** the block SHALL NOT contain `${{ }}` expressions referencing user-controllable GitHub contexts (e.g., `github.event.issue`, `github.event.pull_request`, `github.head_ref`)
- **AND** if dynamic values are needed in `run:` blocks, the template SHALL use `env:` intermediary variables

#### Scenario: Remediation does not worsen compliance
- **WHEN** the remediation tool generates a workflow file for one control
- **THEN** the generated file SHALL NOT introduce failures for other controls in the same audit
- **AND** the generated file SHALL NOT increase the total finding count from workflow security scanners

### Requirement: Zizmor exec pass declares valid exit codes
The BR-01.01 zizmor exec pass SHALL declare `pass_exit_codes` covering all valid zizmor exit codes so the CEL expression can evaluate the JSON output.

#### Scenario: Zizmor returns findings
- **WHEN** zizmor runs and returns a non-zero exit code indicating findings (exit codes 10-14)
- **THEN** the exec handler SHALL treat the exit code as valid (not INCONCLUSIVE)
- **AND** the CEL expression SHALL evaluate the JSON output to determine pass/fail based on finding types

#### Scenario: Zizmor is not installed
- **WHEN** zizmor is not available on the system
- **THEN** the exec handler SHALL return INCONCLUSIVE
- **AND** the pipeline SHALL fall through to the pattern-based fallback pass
