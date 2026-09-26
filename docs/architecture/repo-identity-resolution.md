## ADDED Requirements

### Requirement: Framework SHALL provide a single canonical function for repo identity resolution

The `darnit.core.utils` module SHALL expose a single function `detect_repo_from_git()` that resolves owner, repo name, and metadata for the current repository. This function SHALL be the ONLY place in the codebase that parses git remotes or calls external tools (e.g., `gh`) for owner/repo detection. No other module SHALL implement its own owner/repo detection logic.

#### Scenario: Single source of truth
- **WHEN** any module needs the repository owner or name
- **THEN** it SHALL call `detect_repo_from_git()` from `darnit.core.utils`
- **THEN** it SHALL NOT parse git remotes, call `gh repo view`, or implement custom detection logic

#### Scenario: Implementation packages use canonical detector
- **WHEN** an implementation package (e.g., `darnit-baseline`) needs owner/repo
- **THEN** it SHALL import and call the framework's `detect_repo_from_git()` rather than defining its own `_detect_owner_repo()` function

### Requirement: Repo identity resolution SHALL prefer origin remote over upstream

The canonical `detect_repo_from_git()` function SHALL check git remotes in the following order by default:
1. `origin` remote
2. `upstream` remote (fallback)

A fork clone is identified as itself, not as its parent. Remotes are part of the audited checkout, so an identity derived from them is a display hint only and SHALL NOT be used to decide trust (feature 040, FR-016a); `detect_checkout_identity()` returns the `origin` identity marked as `checkout_hint` and never consults `upstream`.

#### Scenario: Fork with upstream remote configured
- **WHEN** the local repo has both `upstream` (pointing to `github.com/org/repo`) and `origin` (pointing to `github.com/user/repo`) remotes
- **THEN** `detect_repo_from_git()` SHALL return the owner/repo from the `origin` remote

#### Scenario: Only an upstream remote
- **WHEN** the local repo has only an `upstream` remote
- **THEN** `detect_repo_from_git()` SHALL return the owner/repo from the `upstream` remote

#### Scenario: Explicit opt-in to upstream
- **WHEN** a caller passes `prefer_upstream=True`
- **THEN** `detect_repo_from_git()` SHALL check `upstream` first, then `origin`

### Requirement: Repo identity resolution SHALL support explicit owner/repo override

When the caller provides explicit `owner` and `repo` parameters, the function SHALL use those values without any git remote detection. This supports CI environments and non-git contexts.

#### Scenario: Explicit owner/repo provided
- **WHEN** a caller passes `owner="kusari-oss"` and `repo="darnit"`
- **THEN** `detect_repo_from_git()` SHALL return those values without running any subprocess commands

#### Scenario: Only owner or only repo provided
- **WHEN** a caller provides only one of `owner` or `repo` (not both)
- **THEN** `detect_repo_from_git()` SHALL detect the missing value from git remotes and use the provided value for the other

### Requirement: Repo identity resolution SHALL return structured metadata

The function SHALL return a dict with at minimum: `owner`, `repo`, `url`, `is_private`, `default_branch`, `resolved_path`, `source` (which remote or override was used), and `identity` (the remote's canonical `host/namespace/name`, keeping the host, or `None`). If detection fails entirely, it SHALL return `None`.

#### Scenario: Successful detection
- **WHEN** the function resolves owner/repo from a git remote
- **THEN** the returned dict SHALL include a `source` field indicating which remote was used (e.g., `"upstream"`, `"origin"`, `"explicit"`)

#### Scenario: No git remotes available
- **WHEN** no git remotes are configured and no explicit values are provided
- **THEN** the function SHALL return `None`

### Requirement: Repo identity resolution SHALL be resilient to missing tools

The function SHALL handle missing `gh` CLI and missing `git` gracefully, falling back to progressively simpler detection methods.

#### Scenario: gh CLI not installed
- **WHEN** `gh` CLI is not available
- **THEN** the function SHALL fall back to parsing `git remote get-url` output directly

#### Scenario: Not a git repository
- **WHEN** the local path is not inside a git repository
- **THEN** the function SHALL return `None` without raising an exception
