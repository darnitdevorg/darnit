# Org-Level .project Repository Resolution Specification

## ADDED Requirements

### Requirement: Resolve org-level .project repository
The framework SHALL discover and fetch metadata from `{owner}/.project` GitHub repositories when auditing repos that belong to an org.

#### Scenario: Org has a .project repository
- **WHEN** auditing a repository owned by `my-org`
- **AND** `my-org/.project` exists on GitHub
- **THEN** the framework SHALL fetch `project.yaml` from that repository
- **AND** SHALL make its metadata available as default context

#### Scenario: Org does not have a .project repository
- **WHEN** auditing a repository owned by `my-org`
- **AND** `my-org/.project` does not exist on GitHub
- **THEN** the framework SHALL continue with local-only context
- **AND** SHALL NOT fail or error

#### Scenario: gh CLI not available
- **WHEN** the `gh` CLI is not installed or not authenticated
- **THEN** the framework SHALL skip org-level resolution gracefully
- **AND** SHALL log a debug message

### Requirement: Fetch org-level maintainers.yaml
The framework SHALL also fetch `maintainers.yaml` from the org `.project` repository when present.

#### Scenario: Org .project repo has maintainers.yaml
- **WHEN** `{owner}/.project` contains a `maintainers.yaml` file
- **THEN** the framework SHALL fetch and parse it using the same maintainer parsing logic as local files

#### Scenario: Org .project repo has no maintainers.yaml
- **WHEN** `{owner}/.project` does not contain `maintainers.yaml`
- **THEN** the framework SHALL use only `project.yaml` from the org repo

### Requirement: Cache org resolution results
The framework SHALL cache org-level `.project` resolution results per owner for the duration of the session.

#### Scenario: Same org audited multiple times
- **WHEN** multiple repositories from `my-org` are audited in one session
- **THEN** the framework SHALL fetch `my-org/.project` only once
- **AND** SHALL reuse the cached result for subsequent repos

#### Scenario: Cache can be cleared
- **WHEN** the cache is explicitly cleared
- **THEN** subsequent resolution calls SHALL fetch fresh data from GitHub

### Requirement: Merge org config with local config
The framework SHALL merge org-level `.project` defaults with local `.project/` directory config, with local taking precedence at the section level.

#### Scenario: Local has security section, org also has security
- **WHEN** the local repo has `.project/project.yaml` with a `security` section
- **AND** the org `.project` repo also has a `security` section
- **THEN** the local `security` section SHALL completely override the org `security` section

#### Scenario: Local missing a section that org provides
- **WHEN** the local repo has no `governance` section in `.project/project.yaml`
- **AND** the org `.project` repo has a `governance` section
- **THEN** the org `governance` section SHALL be used as a default

#### Scenario: Local scalar fields override org
- **WHEN** the local repo sets `description` in `.project/project.yaml`
- **AND** the org `.project` repo also sets `description`
- **THEN** the local `description` SHALL be used

#### Scenario: Org provides defaults for empty local fields
- **WHEN** the local repo does not set `website` in `.project/project.yaml`
- **AND** the org `.project` repo sets `website`
- **THEN** the org `website` SHALL be used as a default

#### Scenario: Merge does not mutate inputs
- **WHEN** org and local configs are merged
- **THEN** neither the org config nor the local config SHALL be modified
- **AND** the result SHALL be a new config instance

### Requirement: Wire org resolution into audit pipeline
The framework SHALL automatically perform org-level resolution during audits when owner information is available.

#### Scenario: Audit with owner context
- **WHEN** a check context includes an `owner` field
- **THEN** the framework SHALL pass the owner to the mapper for org resolution

#### Scenario: Audit without owner context
- **WHEN** a check context has no `owner` or an empty `owner`
- **THEN** the framework SHALL skip org resolution
- **AND** SHALL use only local `.project/` data
