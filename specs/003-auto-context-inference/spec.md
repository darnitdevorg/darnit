# Auto Context Inference

## Overview

Improve the context collection pipeline so that values like `ci_provider`, `has_releases`, and `platform` can be reliably auto-detected from repository evidence and persisted to `.project/darnit.yaml` without requiring the user to manually answer every prompt.

Today, the TOML `detect` pipeline for `ci_provider` defines `file_exists` checks against paths like `.github/workflows` — but the `file_exists` handler uses `os.path.isfile()`, which fails for directories. The `has_releases` context has only a GitHub API-based detect step (requires `gh` CLI auth), with no local filesystem fallback. As a result, auto-detection is unreliable and users must manually confirm values that should be obvious from local evidence.

## Clarifications

### Session 2026-03-08
- Q: What should platform detection do when git remote fails (no remote configured)? → A: Return null value but still include platform in pending context so user can fill it manually.
- Q: Should has_releases detection require corroborating signals or is one sufficient? → A: Single signal sufficient — first matching detect step wins (standard TOML pipeline behavior).
- Q: Should FR-4 merge all persisted context keys or only existing collect_auto_context keys? → A: Merge all persisted context keys from .project/darnit.yaml into the audit context.

## Context

- **MCP Tool Path**: `get_pending_context` → `_run_detect_pipeline()` (TOML handlers) → `_try_sieve_detection()` (Python fallback) → returns `ContextPromptRequest` with `current_value` pre-filled
- **Storage Path**: `confirm_project_context` → `save_project_config()` → `.project/darnit.yaml`
- **Audit Path**: `audit_openssf_baseline` → `collect_auto_context()` — this uses a *separate* plain auto-detect function, not the confidence-based pipeline
- **Key Bug**: `file_exists_handler` at `builtin_handlers.py:72` uses `os.path.isfile()` which returns `False` for directories

## Functional Requirements

### FR-1: Fix `file_exists` handler for directories
The `file_exists` handler must detect both files AND directories. The TOML `ci_provider` detect pipeline checks `.github/workflows` (a directory), `.circleci/config.yml` (a file), etc. The handler must support both.

**Acceptance Criteria:**
- `file_exists` handler returns PASS when a specified path exists as either a file or directory
- All existing `ci_provider` detect pipeline entries work correctly
- Glob patterns (`*`) continue to work as before

### FR-2: Add local filesystem detection for `has_releases`
Add deterministic filesystem-based detection steps to the `has_releases` TOML detect pipeline, before the existing GitHub API step.

Detection signals (in priority order):
1. Presence of release workflow files (e.g., `.github/workflows/release*.yml`)
2. Presence of CHANGELOG/CHANGES files
3. Git tags matching semver patterns (e.g., `v1.0.0`, `1.2.3`)

**Acceptance Criteria:**
- `has_releases` can be detected without network access when local evidence exists
- The GitHub API step remains as a fallback after local detection
- Each detection step provides a `value_if_pass` of `true`

### FR-3: Add local filesystem detection for `platform`
Add a `platform` context definition to the TOML `[context.*]` section with a detect pipeline that identifies the hosting platform from git remote URLs and CI config files.

Detection signals:
1. Git remote URL containing `github.com` → `"github"`
2. Git remote URL containing `gitlab.com` → `"gitlab"`
3. Presence of `.github/` directory → `"github"` (lower confidence)

**Failure behavior:** When `git remote get-url origin` fails (no remote configured), platform detection returns no value but `platform` still appears in `get_pending_context` results with `current_value: null` so the user can provide it manually.

**Acceptance Criteria:**
- `platform` is detectable from local git configuration without API calls
- Platform detection uses `exec` handler with `git remote get-url origin`
- Detected value is available in `get_pending_context` results
- When no git remote exists, `platform` still appears in pending context with null value

### FR-4: Wire auto-detected values into audit path
The `collect_auto_context()` function (used by the audit tool) should incorporate values already persisted in `.project/darnit.yaml` so that previously confirmed context values inform audit results.

**Acceptance Criteria:**
- `collect_auto_context()` reads from `.project/darnit.yaml` if it exists
- All persisted context keys are merged into the returned dict, not just keys that `collect_auto_context()` already handles (e.g., confirmed `ci_provider`, `has_releases` are included alongside auto-detected `platform`, `languages`)
- Persisted values take precedence over re-detection
- Audit results reflect confirmed context (e.g., `ci_provider: github` affects CI-related control checks)

## Non-Functional Requirements

### NFR-1: No network required for basic detection
All filesystem and git-based detection must work offline. Network-dependent steps (GitHub API) must be last in the detect pipeline and must not block results when earlier steps succeed.

### NFR-2: Conservative by default
Following the project's conservative-by-default principles:
- Auto-detected values are presented for user confirmation, not silently applied
- The `get_pending_context` tool returns detected values with `current_value` pre-filled so the MCP client can present them for confirmation
- Values are only persisted after explicit user confirmation via `confirm_project_context`

### NFR-3: Backward compatibility
- Existing `.project/darnit.yaml` files continue to work unchanged
- All current TOML detect pipelines continue to function
- No changes to the `ComplianceImplementation` protocol

## User Scenarios

### Scenario 1: First audit of a GitHub Actions project
1. User runs audit via MCP tool on a repo with `.github/workflows/ci.yml`
2. `get_pending_context` auto-detects `ci_provider: github` via the fixed `file_exists` handler
3. MCP client presents: "CI provider detected as **github** — confirm?"
4. User confirms; value persisted to `.project/darnit.yaml`
5. Subsequent audits use the persisted value without re-prompting

### Scenario 2: Project with releases detected locally
1. User runs `get_pending_context` on a repo with `CHANGELOG.md` and semver git tags
2. Local filesystem detection finds release evidence, pre-fills `has_releases: true`
3. User confirms; no GitHub API call was needed

### Scenario 3: Offline audit
1. User runs audit without network access
2. All local filesystem detections succeed (ci_provider, has_releases, platform)
3. GitHub API steps fail silently; local results are used
4. User confirms pre-filled values

## Scope

### In Scope
- Fix `file_exists` handler directory support
- Add filesystem-based `has_releases` detection in TOML
- Add `platform` context definition with detect pipeline
- Wire persisted context into `collect_auto_context()`
- Tests for all changes

### Out of Scope
- Auto-detecting `maintainers`, `security_contact`, or `governance_model` (these require human judgment)
- Changes to the context sieve Python module (sieve remains as fallback; improvements go in TOML pipelines)
- New MCP tools or changes to tool signatures
- Auto-accepting values without user confirmation (violates conservative-by-default principle)

## Assumptions

- The `file_exists` handler change from `os.path.isfile()` to `os.path.exists()` is safe because the handler's purpose is "check if path exists," not "check if path is a regular file"
- The `exec` handler can run `git remote get-url origin` for platform detection
- Git tags are accessible via `git tag --list` in the exec handler
- CHANGELOG detection is a reasonable heuristic for `has_releases` (not all projects with changelogs make formal releases, but it's a strong signal)

## Dependencies

- `file_exists` handler fix is a prerequisite for FR-2 and FR-3 (some detection steps use it)
- FR-4 depends on FR-1/FR-2/FR-3 being in place so there are values to persist and read back
