# GitHub API Remediation Specification

Platform remediation for OpenSSF Baseline controls on GitHub. Feature 043 replaced the `api_call` payload remediations with `platform_setting` requirements served by one platform engine; the authoritative rules are in [framework-design.md](./framework-design.md) section 4.5 (the handler, targets, and branch protection writes) and section 15 (policy, digest-bound approval, outcomes).

### Requirement: Platform changes are requirements, not payloads
Every remediation that changes a GitHub setting SHALL be a `platform_setting` step declaring a requirement on a target (`branch_protection`, `repository`, or `vulnerability_reporting`). The platform engine SHALL read the current settings first, plan the minimal change that satisfies the requirement without weakening any existing setting, write it only under the operator's remediation policy, and read the result back.

#### Scenario: Requirement already satisfied
- **WHEN** the current settings, or an active repository or organization ruleset, satisfy the requirement
- **THEN** the system SHALL write nothing and the outcome SHALL be `unchanged`

#### Scenario: Settings cannot be read
- **WHEN** reading the target fails (permission, not found, rate limit, network)
- **THEN** the system SHALL write nothing and the step SHALL be ERROR with its cause

### Requirement: MFA enforcement remediation
OSPS-AC-01.01 SHALL have a `manual` remediation: GitHub offers no API to require two-factor authentication for an organization, so it is manual under every remediation policy.

#### Scenario: Guide org-level MFA requirement
- **WHEN** OSPS-AC-01.01 fails (MFA not required)
- **AND** the user requests remediation
- **THEN** the system SHALL return manual steps that state the impact (outside collaborators and bot accounts without two-factor authentication are removed) and SHALL change nothing

### Requirement: No fork permission remediation
OSPS-AC-02.01 SHALL have no automated remediation. Enabling forking is not what the control requires (#513); its manual check steps are the guidance.

### Requirement: Branch protection remediations
OSPS-AC-03.01, OSPS-AC-03.02, and OSPS-QA-07.01 SHALL declare `branch_protection` requirements: `require_pull_request`, `prevent_deletion`, and `require_approvals = 1` respectively, on the repository's default branch.

#### Scenario: Several requirements on one branch
- **WHEN** a run remediates OSPS-AC-03.01, OSPS-AC-03.02, and OSPS-QA-07.01
- **THEN** the requirements SHALL be planned together as one change set for the branch
- **AND** every existing setting equal to or stricter than the requirements (more required approvals, status checks, push restrictions, code-owner review, linear history) SHALL be unchanged

### Requirement: Repository visibility remediation
OSPS-QA-01.01 SHALL declare a `repository` requirement `visibility = "public"`. The change is high-impact.

#### Scenario: Make repository public
- **WHEN** OSPS-QA-01.01 fails (repo is private)
- **AND** the remediation is applied under the default `prompt` policy
- **THEN** the system SHALL write the change only when its own change-set digest is approved, never as part of a batch approval
- **AND** the preview SHALL state the impact (code, history, and Actions logs become public; private forks are detached)

### Requirement: Status checks remediation
OSPS-QA-03.01 SHALL have a `manual` remediation: which status checks to require depends on the project's CI.

### Requirement: Private vulnerability reporting remediation
OSPS-VM-03.01 SHALL declare a `vulnerability_reporting` requirement `enabled = true`.

#### Scenario: Enable private vulnerability reporting
- **WHEN** OSPS-VM-03.01 fails (private reporting disabled)
- **AND** the remediation is applied with its change set approved (or under the `auto` policy)
- **THEN** the system SHALL enable private vulnerability reporting and read the setting back

### Requirement: Security advisories remediation
The implementation SHALL provide a `manual` remediation for OSPS-VM-04.01 that guides the user through publishing security advisories.

#### Scenario: Guide security advisory creation
- **WHEN** OSPS-VM-04.01 fails (no security advisories published)
- **AND** the user triggers remediation
- **THEN** the system SHALL provide manual steps for creating a security advisory via GitHub's advisory interface
- **AND** SHALL include a `docs_url` to GitHub's security advisory documentation
