# GitHub API Remediation Specification

### Requirement: MFA enforcement remediation
The implementation SHALL provide an `api_call` remediation for OSPS-AC-01.01 that enables required two-factor authentication at the organization level.

#### Scenario: Enable org-level MFA requirement
- **WHEN** OSPS-AC-01.01 fails (MFA not required)
- **AND** the user triggers remediation
- **THEN** the system SHALL call `PUT /orgs/$OWNER/actions/permissions` with MFA enforcement enabled
- **AND** the remediation SHALL be marked `safe = false` (changes org-wide settings)

### Requirement: Fork permission remediation
The implementation SHALL provide an `api_call` remediation for OSPS-AC-02.01 that enables forking on the repository.

#### Scenario: Enable repository forking
- **WHEN** OSPS-AC-02.01 fails (forking disabled)
- **AND** the user triggers remediation
- **THEN** the system SHALL call `PATCH /repos/$OWNER/$REPO` with `allow_forking: true`
- **AND** the remediation SHALL be marked `safe = true`

### Requirement: Branch deletion protection remediation
The implementation SHALL provide an `api_call` remediation for OSPS-AC-03.02 that prevents branch deletion on the default branch.

#### Scenario: Enable branch deletion protection
- **WHEN** OSPS-AC-03.02 fails (branch deletion allowed)
- **AND** the user triggers remediation
- **THEN** the system SHALL update branch protection rules via `PUT /repos/$OWNER/$REPO/branches/$BRANCH/protection` to include `allow_deletions: false`
- **AND** the remediation SHALL be marked `safe = false` (modifies branch protection)

### Requirement: Repository visibility check and remediation
The implementation SHALL provide an `exec` check and `api_call` remediation for OSPS-QA-01.01 (repository is public).

#### Scenario: Check repository visibility
- **WHEN** OSPS-QA-01.01 is evaluated
- **THEN** the system SHALL call `gh api /repos/$OWNER/$REPO` and check `output.json.private == false`

#### Scenario: Make repository public
- **WHEN** OSPS-QA-01.01 fails (repo is private)
- **AND** the user triggers remediation
- **THEN** the system SHALL call `PATCH /repos/$OWNER/$REPO` with `private: false`
- **AND** the remediation SHALL be marked `safe = false` (irreversible visibility change)

### Requirement: Status checks remediation
The implementation SHALL provide an `api_call` remediation for OSPS-QA-03.01 that enables required status checks on the default branch.

#### Scenario: Enable required status checks
- **WHEN** OSPS-QA-03.01 fails (no required status checks)
- **AND** the user triggers remediation
- **THEN** the system SHALL update branch protection via `PUT /repos/$OWNER/$REPO/branches/$BRANCH/protection` with `required_status_checks` configured
- **AND** the remediation SHALL be marked `safe = false`

### Requirement: PR approval remediation
The implementation SHALL provide an `api_call` remediation for OSPS-QA-07.01 that requires PR approval before merging.

#### Scenario: Enable required PR reviews
- **WHEN** OSPS-QA-07.01 fails (PRs can merge without approval)
- **AND** the user triggers remediation
- **THEN** the system SHALL update branch protection via `PUT /repos/$OWNER/$REPO/branches/$BRANCH/protection` with `required_pull_request_reviews.required_approving_review_count >= 1`
- **AND** the remediation SHALL be marked `safe = false`

### Requirement: Private vulnerability reporting remediation
The implementation SHALL provide an `api_call` remediation for OSPS-VM-03.01 that enables private vulnerability reporting.

#### Scenario: Enable private vulnerability reporting
- **WHEN** OSPS-VM-03.01 fails (private reporting disabled)
- **AND** the user triggers remediation
- **THEN** the system SHALL call `PUT /repos/$OWNER/$REPO/private-vulnerability-reporting` to enable private reporting
- **AND** the remediation SHALL be marked `safe = true`

### Requirement: Security advisories remediation
The implementation SHALL provide a `manual` remediation for OSPS-VM-04.01 that guides the user through publishing security advisories.

#### Scenario: Guide security advisory creation
- **WHEN** OSPS-VM-04.01 fails (no security advisories published)
- **AND** the user triggers remediation
- **THEN** the system SHALL provide manual steps for creating a security advisory via GitHub's advisory interface
- **AND** SHALL include a `docs_url` to GitHub's security advisory documentation

### Requirement: API remediation payload templates
Each `api_call` remediation SHALL reference a named template from the `[templates]` section for its JSON payload.

#### Scenario: Template variable substitution
- **WHEN** an `api_call` remediation executes
- **AND** the payload template contains `$OWNER`, `$REPO`, or `$BRANCH`
- **THEN** the system SHALL substitute these with actual repository values

#### Scenario: Template exists for each api_call
- **WHEN** any `api_call` remediation handler specifies `payload_template = "<name>"`
- **THEN** a corresponding `[templates.<name>]` entry SHALL exist in the TOML config
