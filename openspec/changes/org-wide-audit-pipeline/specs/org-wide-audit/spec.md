## ADDED Requirements

### Requirement: Enumerate org repositories
The framework SHALL enumerate all repositories in a GitHub org via `gh repo list` and return a list of repo names for auditing.

#### Scenario: Org with repositories
- **WHEN** `enumerate_org_repos(owner)` is called for an org with repositories
- **THEN** the framework SHALL return a list of non-archived repository names
- **AND** SHALL use `gh repo list {owner} --json name,isArchived --limit 500`

#### Scenario: Org with no repositories
- **WHEN** `enumerate_org_repos(owner)` is called for an org with no repos
- **THEN** the framework SHALL return an empty list
- **AND** SHALL NOT fail or error

#### Scenario: gh CLI not available
- **WHEN** the `gh` CLI is not installed or not authenticated
- **THEN** the framework SHALL return an error message indicating gh is required for org-wide audits
- **AND** SHALL NOT raise an unhandled exception

#### Scenario: Include archived repos
- **WHEN** `enumerate_org_repos(owner, include_archived=True)` is called
- **THEN** the framework SHALL include archived repositories in the returned list

#### Scenario: Filter by repo names
- **WHEN** `enumerate_org_repos(owner, repos=["repo-a", "repo-b"])` is called with a specific repo list
- **THEN** the framework SHALL return only the specified repos (validated against the org)
- **AND** SHALL warn about any requested repos that do not exist in the org

### Requirement: Clone repo to temp directory
The framework SHALL clone each repo to a temporary directory using shallow clones for auditing.

#### Scenario: Successful shallow clone
- **WHEN** a repo is cloned for auditing
- **THEN** the framework SHALL use `gh repo clone {owner}/{repo} {tmpdir} -- --depth 1`
- **AND** the temp directory SHALL be cleaned up after the audit completes

#### Scenario: Clone failure
- **WHEN** cloning a repo fails (permissions, network, etc.)
- **THEN** the framework SHALL log a warning with the repo name and error
- **AND** SHALL continue to the next repo
- **AND** SHALL include the failed repo in results with status "ERROR"

#### Scenario: Temp directory isolation
- **WHEN** multiple repos are audited sequentially
- **THEN** each repo SHALL be cloned to a separate temp directory
- **AND** the previous temp directory SHALL be cleaned up before cloning the next repo

### Requirement: Run per-repo audits
The framework SHALL run the existing single-repo audit pipeline (`run_sieve_audit`) against each cloned repo.

#### Scenario: Audit a cloned repo
- **WHEN** a repo has been cloned to a temp directory
- **THEN** the framework SHALL call `run_sieve_audit()` with the temp directory as `local_path`
- **AND** SHALL pass the correct `owner` and `repo` values

#### Scenario: Audit parameters passed through
- **WHEN** the org-wide audit is invoked with `level`, `tags`, or other parameters
- **THEN** those parameters SHALL be passed through to each per-repo `run_sieve_audit()` call

#### Scenario: Per-repo audit failure
- **WHEN** `run_sieve_audit()` raises an exception for a repo
- **THEN** the framework SHALL catch the exception and log a warning
- **AND** SHALL continue to the next repo
- **AND** SHALL include the failed repo in results with status "ERROR" and the error message

### Requirement: Aggregate org-wide results
The framework SHALL aggregate per-repo audit results into a combined org-wide report.

#### Scenario: Markdown aggregated report
- **WHEN** the org-wide audit completes with `output_format="markdown"`
- **THEN** the report SHALL include an org-level summary table with columns: repo name, level, PASS count, FAIL count, WARN count, compliance status
- **AND** SHALL include per-repo detail sections using the existing `format_results_markdown()` format

#### Scenario: JSON aggregated report
- **WHEN** the org-wide audit completes with `output_format="json"`
- **THEN** the result SHALL include an `org_summary` object with per-repo compliance data
- **AND** SHALL include a `repo_results` array with full per-repo audit results

#### Scenario: All repos pass
- **WHEN** all repos in the org pass at the requested level
- **THEN** the org-level summary SHALL indicate full compliance

#### Scenario: Mixed results
- **WHEN** some repos pass and some fail
- **THEN** the org-level summary SHALL show the count of compliant vs non-compliant repos
- **AND** SHALL list non-compliant repos with their failing control counts

### Requirement: Org-wide audit MCP tool
The implementation SHALL expose an `audit_org` MCP tool that triggers org-wide auditing.

#### Scenario: Tool invocation with owner
- **WHEN** the `audit_org` tool is called with `owner="my-org"`
- **THEN** it SHALL enumerate repos, clone each, run audits, and return the aggregated report

#### Scenario: Tool invocation with level filter
- **WHEN** the `audit_org` tool is called with `owner="my-org"` and `level=1`
- **THEN** it SHALL audit each repo at level 1 only

#### Scenario: Tool invocation with repo filter
- **WHEN** the `audit_org` tool is called with `owner="my-org"` and `repos=["repo-a"]`
- **THEN** it SHALL audit only the specified repos, not the entire org

### Requirement: Write-back routing classification
After org-wide audit, the framework SHALL classify each remediation action as targeting either the org `.project` repo or the individual repo's `.project/` folder.

#### Scenario: Org-level metadata classification
- **WHEN** a remediation would set `security.contact`, `maintainers`, or `governance` fields
- **AND** those fields exist in the org `.project` repo
- **THEN** the routing SHALL classify the action as `org`
- **AND** SHALL indicate the target is `{owner}/.project`

#### Scenario: Repo-level metadata classification
- **WHEN** a remediation creates repo-specific artifacts (SECURITY.md, CODEOWNERS)
- **OR** sets fields that do not exist in the org `.project` repo
- **THEN** the routing SHALL classify the action as `repo`
- **AND** SHALL indicate the target is the individual repo's `.project/` folder

#### Scenario: Routing report in audit output
- **WHEN** the org-wide audit completes and there are remediation suggestions
- **THEN** the report SHALL include a "Write-back Routing" section
- **AND** each suggested remediation SHALL be labeled `[org]` or `[repo]`

#### Scenario: No auto-push
- **WHEN** write-back routing classifies actions
- **THEN** the framework SHALL NOT automatically push changes to any remote repository
- **AND** SHALL present the classification for user review

### Requirement: Single-repo audit compatibility
The org-wide audit mode SHALL NOT affect the existing single-repo audit path.

#### Scenario: Existing audit_openssf_baseline unchanged
- **WHEN** `audit_openssf_baseline()` is called with `owner` and `repo` for a single repo
- **THEN** behavior SHALL be identical to before this change
- **AND** no org enumeration or cloning SHALL occur

#### Scenario: Existing run_sieve_audit unchanged
- **WHEN** `run_sieve_audit()` is called directly
- **THEN** its signature and behavior SHALL remain backward compatible
- **AND** the only additive change is `.project/` mapper context injection (see audit-pipeline spec)
