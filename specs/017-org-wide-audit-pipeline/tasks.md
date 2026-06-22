## 1. Wire .project/ mapper into audit pipeline

- [x] 1.1 In `run_sieve_audit()` (`packages/darnit/src/darnit/tools/audit.py`), add a `.project/` mapper call between `load_context()` (line ~443) and the control loop (line ~460). Create `DotProjectMapper(local_path, owner=owner)`, call `get_context()`, and merge into `project_context` dict. Merge order: auto-detect → mapper → user-confirmed (user wins).
- [x] 1.2 Handle mapper failure gracefully: wrap in try/except, log warning, continue with existing context.
- [x] 1.3 Handle missing owner: when `owner` is None or empty, still call mapper without owner (local `.project/` only, no org resolution).
- [x] 1.4 Add unit tests for pipeline mapper integration: verify mapper context appears in `project_context`, verify user-confirmed values override mapper values, verify mapper failure is non-fatal.

## 2. Org repo enumeration

- [x] 2.1 Create `packages/darnit/src/darnit/tools/audit_org.py` with `enumerate_org_repos(owner, *, include_archived=False, repos=None)` function. Uses `gh repo list {owner} --json name,isArchived --limit 500`. Returns list of repo name strings.
- [x] 2.2 Implement archived repo filtering: skip archived by default, include when `include_archived=True`.
- [x] 2.3 Implement repo name filter: when `repos` list is provided, validate against org's actual repos and warn about missing ones.
- [x] 2.4 Handle `gh` CLI unavailability: return error tuple `([], "gh CLI required for org-wide audits")` instead of raising.
- [x] 2.5 Add unit tests for `enumerate_org_repos`: mock `subprocess.run`, test archived filtering, repo name filtering, gh unavailable, empty org.

## 3. Clone and audit loop

- [x] 3.1 In `audit_org.py`, add `clone_repo(owner, repo, tmpdir)` function using `gh repo clone {owner}/{repo} {tmpdir} -- --depth 1`. Returns success bool.
- [x] 3.2 Add `run_org_audit(owner, *, level=3, tags=None, repos=None, include_archived=False, output_format="markdown")` as the main orchestration function. Enumerates repos, then for each: clone to tempdir → `run_sieve_audit()` → collect results → cleanup tempdir.
- [x] 3.3 Handle per-repo clone failures: log warning, add ERROR entry to results, continue to next repo.
- [x] 3.4 Handle per-repo audit failures: catch exceptions from `run_sieve_audit()`, log warning, add ERROR entry, continue.
- [x] 3.5 Ensure temp directory cleanup: use `tempfile.TemporaryDirectory` context manager so cleanup happens even on exceptions.
- [x] 3.6 Add unit tests for clone and audit loop: mock `subprocess.run` and `run_sieve_audit`, test sequential execution, clone failure handling, audit failure handling, temp cleanup.

## 4. Result aggregation

- [x] 4.1 Add `aggregate_org_results(owner, repo_results, level)` function that builds the org-level summary (per-repo PASS/FAIL/WARN counts, compliance status).
- [x] 4.2 Add markdown formatter for org-wide report: summary table (repo | level | PASS | FAIL | WARN | status) + per-repo detail sections using existing `format_results_markdown()`.
- [x] 4.3 Add JSON formatter for org-wide report: `org_summary` object + `repo_results` array.
- [x] 4.4 Add unit tests for aggregation: all-pass, mixed results, repos with errors.

## 5. Write-back routing classification

- [x] 5.1 Create `packages/darnit-baseline/src/darnit_baseline/remediation/routing.py` with `classify_writeback(remediation_action, org_config)` function. Returns `"org"` or `"repo"` based on whether the field exists in the org `.project` config.
- [x] 5.2 Define the classification rules: security.contact, maintainers, governance → `org` when present in org config; SECURITY.md, CODEOWNERS, repo-specific paths → always `repo`.
- [x] 5.3 Integrate routing into org-wide audit report: add "Write-back Routing" section that labels each remediation suggestion as `[org]` or `[repo]`.
- [x] 5.4 Add unit tests for routing classification: org-level fields, repo-level fields, field not in org config falls back to repo.

## 6. MCP tool handler

- [x] 6.1 Add `audit_org()` tool handler function in `packages/darnit-baseline/src/darnit_baseline/tools.py`. Thin wrapper that calls `run_org_audit()` from the framework.
- [x] 6.2 Add MCP tool registration for `audit_org` in the implementation's TOML config or handler registration.
- [x] 6.3 Add unit test for tool handler: verify it delegates to `run_org_audit()` with correct parameters.

## 7. Pre-commit validation

- [x] 7.1 Run `uv run ruff check .` and fix any lint errors.
- [x] 7.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` and verify all tests pass.
- [x] 7.3 Run `uv run python scripts/validate_sync.py --verbose` and verify spec-implementation sync.
