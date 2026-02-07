## 1. Upgrade canonical detector in `darnit.core.utils`

- [x] 1.1 Rewrite `detect_repo_from_git()` in `packages/darnit/src/darnit/core/utils.py` to: (a) accept `prefer_upstream`, `owner`, `repo` keyword-only params, (b) short-circuit when both `owner` and `repo` are provided (return with `source: "explicit"`), (c) check remotes in order via `git remote get-url` (upstream then origin, or reversed if `prefer_upstream=False`), (d) parse GitHub URL from remote output, (e) call `gh repo view {owner}/{repo}` with explicit nwo for metadata enrichment, (f) include `source` field in return dict.
- [x] 1.2 Add `detect_owner_repo()` convenience wrapper in the same file that returns `tuple[str, str]` — delegates to `detect_repo_from_git()` and extracts `(owner, repo)`, returning `("", path.name)` on `None`.
- [x] 1.3 Export `detect_owner_repo` from `darnit.core.utils` (add to `__all__` or module-level imports as appropriate).

## 2. Delete duplicate detectors and migrate call sites

- [x] 2.1 Delete `_detect_owner_repo()` from `packages/darnit-baseline/src/darnit_baseline/tools.py` (line 894-938). Replace 7 call sites (lines 69, 234, 287, 422, 588, 662, 725) with `detect_owner_repo()` from `darnit.core.utils`.
- [x] 2.2 Update `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py` (lines 804-808) to import from `darnit.core.utils` instead of `darnit_baseline.tools`.
- [x] 2.3 Delete `_detect_owner_repo()` from `packages/darnit/src/darnit/server/tools/builtin_audit.py` (lines 147-157). Replace call site (line 114) with `detect_owner_repo()` from `darnit.core.utils`.
- [x] 2.4 Delete `_detect_owner_repo()` from `packages/darnit/src/darnit/server/tools/builtin_remediate.py` (lines 185-195). Replace call site (line 115) with `detect_owner_repo()` from `darnit.core.utils`.
- [x] 2.5 Delete `_detect_owner_repo()` from `packages/darnit/src/darnit/cli.py` (lines 498-522). Replace call site (line 191) with `detect_owner_repo()` from `darnit.core.utils`.
- [x] 2.6 Replace inline `detect_repo_from_git()` call in `packages/darnit/src/darnit/config/context_storage.py` (lines 391-397) with `detect_owner_repo()` from `darnit.core.utils`.

## 3. Update framework-design spec

- [x] 3.1 Add `$OWNER`/`$REPO` resolution requirement to `openspec/specs/framework-design/spec.md`: template variables MUST be resolved using canonical `detect_repo_from_git()`, no other module SHALL implement repo identity detection.

## 4. Tests

- [x] 4.1 Add tests for `detect_repo_from_git()`: upstream remote preferred over origin; origin-only fallback; `prefer_upstream=False` reverses order; explicit owner/repo short-circuits; `source` field reflects which remote was used; returns `None` for non-git paths.
- [x] 4.2 Add tests for `detect_owner_repo()`: returns tuple; returns `("", dir_name)` on failure.
- [x] 4.3 Verify existing tests still pass — no regressions from call-site migrations.

## 5. Verify

- [x] 5.1 Run `uv run ruff check .` — all checks pass.
- [x] 5.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — no new failures.
- [x] 5.3 Grep: zero hits for `def _detect_owner_repo` in `packages/` (all copies deleted).
- [x] 5.4 Grep: only `darnit/core/utils.py` contains `git remote get-url` calls for owner/repo detection (level1.py has a separate hosting-platform check which is a different concern).
