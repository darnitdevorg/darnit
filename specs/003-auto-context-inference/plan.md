# Implementation Plan: Auto Context Inference

## Technical Context

- **Language**: Python 3.11+
- **Framework**: darnit (custom compliance auditing framework)
- **Package Manager**: uv
- **Test Framework**: pytest
- **Linter**: ruff
- **Config Format**: TOML (openssf-baseline.toml)
- **Expression Language**: CEL (celpy library)

## Architecture

This feature modifies 4 files and 1 TOML config. No new modules are created.

### Files Modified

| File | Change | FR |
|------|--------|----|
| `packages/darnit/src/darnit/sieve/builtin_handlers.py` | `os.path.isfile()` → `os.path.exists()` (line 72) | FR-1 |
| `packages/darnit-baseline/openssf-baseline.toml` | Add `has_releases` filesystem detect steps; add `[context.platform]` | FR-2, FR-3 |
| `packages/darnit/src/darnit/context/auto_detect.py` | Merge persisted context in `collect_auto_context()` | FR-4 |
| `tests/darnit/sieve/test_builtin_handlers.py` | Tests for `file_exists` directory support | FR-1 |
| `tests/darnit/config/test_context_storage.py` | Tests for detect pipeline with new TOML entries | FR-2, FR-3 |
| `tests/darnit/context/test_auto_detect.py` | Tests for persisted context merge | FR-4 |

### Data Flow

```
[TOML detect pipeline] → file_exists_handler (FR-1 fix)
                        → exec_handler (git tags, git remote)
                        → _run_detect_pipeline() returns ContextValue
                        → get_pending_context returns ContextPromptRequest
                        → User confirms via confirm_project_context
                        → Persisted to .project/darnit.yaml
                        → collect_auto_context() reads persisted (FR-4)
                        → Audit uses merged context
```

## Implementation Phases

### Phase 1: Fix `file_exists` handler (FR-1)

**Scope**: Single line change + tests.

1. Change `builtin_handlers.py:72` from `os.path.isfile(path)` to `os.path.exists(path)`
2. Add test: `file_exists_handler` returns PASS for a directory path
3. Add test: `file_exists_handler` still returns PASS for a file path
4. Add test: `file_exists_handler` returns FAIL for nonexistent path
5. Verify existing tests pass

### Phase 2: Add TOML detect pipelines (FR-2, FR-3)

**Scope**: TOML config changes + integration tests.

#### FR-2: `has_releases` detect pipeline

Add 3 steps before the existing `gh release list` step:

```toml
detect = [
    { handler = "file_exists", files = [".github/workflows/release*"], value_if_pass = true },
    { handler = "file_exists", files = ["CHANGELOG.md", "CHANGELOG", "CHANGES.md", "CHANGES"], value_if_pass = true },
    { handler = "exec", command = ["git", "tag", "--list", "v*"], pass_exit_codes = [0], expr = 'output.stdout != ""', value_if_pass = true },
    { handler = "exec", command = ["gh", "release", "list", "--repo", "$OWNER/$REPO", "--limit", "1"], pass_exit_codes = [0], value_if_pass = true, value_if_fail = false },
]
```

#### FR-3: `[context.platform]` definition

```toml
[context.platform]
type = "enum"
prompt = "What hosting platform does this project use?"
hint = "Select the platform where the canonical repository is hosted"
values = ["github", "gitlab", "bitbucket", "other"]
examples = ["github", "gitlab"]
affects = ["OSPS-AC-01.01", "OSPS-AC-02.01", "OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-BR-03.01"]
store_as = "project.platform"
auto_detect = true
required = false
presentation_hint = "[github/gitlab/bitbucket/other]"
detect = [
    { handler = "exec", command = ["git", "remote", "get-url", "origin"], pass_exit_codes = [0], expr = 'output.stdout.contains("github.com")', value_if_pass = "github" },
    { handler = "exec", command = ["git", "remote", "get-url", "origin"], pass_exit_codes = [0], expr = 'output.stdout.contains("gitlab.com")', value_if_pass = "gitlab" },
    { handler = "file_exists", files = [".github"], value_if_pass = "github" },
]
```

**Tests**:
1. `_run_detect_pipeline` detects `has_releases: true` when CHANGELOG.md exists
2. `_run_detect_pipeline` detects `has_releases: true` when git tags exist (mock exec)
3. `_run_detect_pipeline` detects `platform: github` from git remote (mock exec)
4. `_run_detect_pipeline` returns None for platform when no remote exists (mock exec failure)
5. `platform` appears in `get_pending_context` with null value when undetectable

### Phase 3: Wire persisted context into audit (FR-4)

**Scope**: Modify `collect_auto_context()` + tests.

1. At top of `collect_auto_context()`, call `load_context()` and flatten to bare keys
2. Guard each auto-detect call with `if key not in context` to avoid overriding persisted values
3. Wrap the load in try/except for graceful degradation (no config = no-op)

**Tests**:
1. `collect_auto_context()` returns persisted `ci_provider` from `.project/darnit.yaml`
2. Persisted values override auto-detected values
3. Auto-detection still works when no `.project/` exists
4. Mixed: some values persisted, some auto-detected

### Phase 4: Validation

1. Run full test suite: `uv run pytest tests/ --ignore=tests/integration/ -q`
2. Run linter: `uv run ruff check .`
3. Run spec sync: `uv run python scripts/validate_sync.py --verbose`
4. Manual smoke test: run `get_pending_context` on this repo and verify `ci_provider: github` is auto-detected

## Constraints

- **No new Python modules** — all changes fit in existing files
- **TOML-first** — detection logic lives in TOML pipelines, not Python
- **Conservative-by-default** — detected values require user confirmation
- **Backward compatible** — existing `.project/darnit.yaml` files work unchanged
- **CEL expressions** — use `!` not `not`, `&&`/`||` not `and`/`or`

## Risks

| Risk | Mitigation |
|------|------------|
| CEL `contains()` not available in celpy | Verified in cel-expressions spec; fallback: use `matches()` regex |
| `os.path.exists()` follows symlinks | Acceptable — symlinked CI configs are still CI configs |
| `git tag --list "v*"` matches non-semver tags | Acceptable — conservative detection means false positives are confirmed by user |
| `load_context()` import in auto_detect creates circular dependency | Use lazy import inside function body |
