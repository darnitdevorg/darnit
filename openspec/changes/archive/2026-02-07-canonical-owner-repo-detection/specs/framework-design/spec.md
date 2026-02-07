## ADDED Requirements

### Requirement: Template variable resolution SHALL use canonical repo identity detection

The `$OWNER`, `$REPO`, and `$BRANCH` template variables used in exec commands, API calls, and file templates SHALL be resolved using `detect_repo_from_git()` from `darnit.core.utils`. No template resolution code SHALL implement its own owner/repo detection logic.

#### Scenario: Template variables resolve to upstream in fork context
- **WHEN** a control's exec command or API call uses `$OWNER` and `$REPO`
- **AND** the local repository is a fork with an `upstream` remote
- **THEN** `$OWNER` and `$REPO` SHALL resolve to the upstream repository's owner and name

#### Scenario: Template variables resolve consistently across all tools
- **WHEN** `$OWNER` is resolved in an audit tool, a remediation tool, and the CLI
- **THEN** all three SHALL return the same value for the same repository state

### Requirement: No module outside darnit.core.utils SHALL implement repo identity detection

Repo identity detection (parsing git remotes, calling `gh repo view`, or extracting owner/repo from URLs) is a core framework concern. Implementation packages and tool modules SHALL import the canonical function rather than duplicating this logic.

#### Scenario: New tool needs owner/repo
- **WHEN** a developer creates a new MCP tool that needs the repository owner
- **THEN** the tool SHALL call `detect_repo_from_git()` from `darnit.core.utils`
- **THEN** the tool SHALL NOT contain functions named `_detect_owner_repo` or equivalent logic that parses git remotes

#### Scenario: Lint-level enforcement
- **WHEN** a module outside `darnit.core.utils` contains a call to `git remote get-url` or `gh repo view` for owner/repo detection purposes
- **THEN** it SHALL be considered a violation of this requirement
