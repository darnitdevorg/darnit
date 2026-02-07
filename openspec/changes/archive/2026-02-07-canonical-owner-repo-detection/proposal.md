## Why

The audit produces wrong results on forks because 5 of 6 owner/repo detectors resolve to the `origin` remote (the fork) instead of the upstream org repo. This causes false failures — e.g., OSPS-AC-01.01 (MFA) fails because it checks the fork owner's settings instead of the upstream org's.

The root cause is an architectural gap: repo identity detection is not treated as a core framework concern. The framework's `detect_repo_from_git()` was incomplete (no fork awareness), so `darnit-baseline` added its own fork-aware version in `tools.py`. Other modules couldn't import from `darnit-baseline` (separation rule), so they each wrote private wrappers — producing 6 duplicate detectors with inconsistent behavior. There is also no spec requirement defining how `$OWNER`/`$REPO` should be resolved, so every new tool defaults to `origin` and the drift repeats.

**Repo identity is a core framework concern.** It should be solved once in `darnit.core`, be fork-aware by default, and nothing else should ever parse git remotes directly.

## What Changes

- **Make repo identity a first-class framework primitive** by upgrading `detect_repo_from_git()` in `darnit.core.utils` to be fork-aware (upstream-first) by default. This is THE canonical function — all owner/repo detection flows through it.
- **Delete all 5 private `_detect_owner_repo()` copies** across `darnit_baseline/tools.py`, `builtin_audit.py`, `builtin_remediate.py`, `cli.py`, and the inline detection in `context_storage.py`. Replace every call site with the single canonical function.
- **Add a spec requirement** to `framework-design` defining how `$OWNER`/`$REPO` template variables MUST be resolved — upstream-first with explicit override — so coding agents (human or LLM) building new features follow the rule automatically and we never get drift again.

## Capabilities

### New Capabilities
- `repo-identity-resolution`: Canonical owner/repo detection as a core framework primitive — fork-aware upstream-first resolution, single source of truth. No module outside `darnit.core.utils` should ever parse git remotes or call `gh repo view` for owner/repo detection.

### Modified Capabilities
- `framework-design`: Add requirement that `$OWNER`/`$REPO` template variables MUST be resolved using the canonical upstream-first detector. Document the resolution order and the rule that no other code may duplicate this logic.

## Impact

- **`packages/darnit/src/darnit/core/utils.py`**: Upgrade `detect_repo_from_git()` with upstream-first resolution
- **`packages/darnit-baseline/src/darnit_baseline/tools.py`**: Delete `_detect_owner_repo()` (~45 lines), replace 7 call sites
- **`packages/darnit/src/darnit/server/tools/builtin_audit.py`**: Delete `_detect_owner_repo()`, use canonical
- **`packages/darnit/src/darnit/server/tools/builtin_remediate.py`**: Delete `_detect_owner_repo()`, use canonical
- **`packages/darnit/src/darnit/cli.py`**: Delete `_detect_owner_repo()`, use canonical
- **`packages/darnit/src/darnit/config/context_storage.py`**: Replace inline detection with canonical
- **`openspec/specs/framework-design/spec.md`**: Add `$OWNER`/`$REPO` resolution requirement
