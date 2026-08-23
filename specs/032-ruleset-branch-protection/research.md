# Phase 0 Research: Ruleset-aware branch-protection verdict

## Purpose

Resolve every unknown surfaced by the plan's Technical Context section and the spec's Assumptions/Edge Cases. Each entry records the decision, rationale, and rejected alternatives so future maintainers can pick up the thread.

## Decisions

### R-001: Parse HTTP status from `gh`'s stderr on non-zero exit

**Decision**: Introduce `gh_api_with_status(endpoint: str) -> tuple[body | None, status: int, error: str]` in `darnit.core.utils` alongside the existing `gh_api` and `gh_api_safe`. Parse `gh`'s stderr on non-zero exit with the regex `^HTTP (\d{3}):` to extract the HTTP status code. Absent the pattern, return `status=0` and surface the raw stderr as the error message.

**Rationale**: The `gh` CLI's stderr format on HTTP-error non-zero exits follows the stable pattern `HTTP <code>: <message> (<url>)` — for example `HTTP 404: Not Found (https://api.github.com/repos/octocat/hello-world/branches/nonexistent/protection)`. The prefix is emitted by `gh`'s core error handler and predates the CLI 2.x release; the format is stable enough to key on. Non-HTTP failures (network before the request completed, `FileNotFoundError` for the `gh` binary itself) do not carry the prefix and fall through to `status=0` — the caller MUST treat this as ambiguous per FR-006 (WARN, not FAIL).

**Alternatives considered**:

- **Raise a typed exception carrying the status code.** Rejected because it would require touching every existing `gh_api` caller to catch the new exception class or add `contextlib.suppress` guards, expanding the change surface unnecessarily.
- **Enhance `gh_api` in place to return a tuple.** Rejected because ~30 existing callers rely on the current dict-or-raise contract; changing it would either break all of them or force adapter shims.
- **Use `gh api --include` to surface HTTP headers.** Considered attractive because it produces machine-parseable status information without stderr scraping. Rejected for v0 because the flag changes the response body format (prepends the response headers as text before the JSON), forcing extra parsing on the success path too. Worth revisiting if the stderr-prefix pattern ever changes.
- **Bypass `gh` and use `urllib.request` directly.** Rejected: reintroduces the auth-token-resolution problem the existing helper already solves, and fragments the darnit transport surface across two GitHub clients.

**References**: Existing helper at `packages/darnit/src/darnit/core/utils.py:20-53`. The `HTTP <code>:` stderr prefix is documented at cli/cli issue #4200 (historical) and confirmed by hand-testing `gh api /repos/nonexistent/nonexistent 2>&1` locally.

---

### R-002: Ruleset list is a summary; detail-fetch is required per ruleset

**Decision**: The handler fetches the ruleset list via `gh api --paginate /repos/{owner}/{repo}/rulesets` (returns a JSON array top-level), then for each entry fetches the detail via `gh api /repos/{owner}/{repo}/rulesets/{id}` to obtain `conditions` and `rules`. We do not filter by summary-level `enforcement` before the detail fetch: a maintainer could re-enable a ruleset between the list and the detail call, and paying the extra detail call is cheaper than an incorrect FAIL.

**Rationale**: GitHub's REST v3 rulesets list endpoint returns a summary schema that does NOT include the `rules` array or the `conditions` object; both are required to determine whether a ruleset satisfies a given protection requirement. Per-ruleset detail is therefore load-bearing. The rulesets endpoint respects `?per_page=` and `Link` header pagination the same way other list endpoints do; `gh api --paginate` handles this transparently.

**Alternatives considered**:

- **Use GitHub's GraphQL API to fetch rulesets + rules in a single call.** Rejected for v0 because darnit's existing GitHub transport is the `gh` CLI REST path; introducing a GraphQL query would fragment the transport surface. Worth revisiting if the per-ruleset detail cost becomes a real fleet-wide bottleneck.
- **Skip the detail call when the summary's `enforcement` is not `active`.** Rejected because the summary's `enforcement` field reflects state at list-fetch time; a TOCTOU-like race could produce inconsistent verdicts. The saved API call is not worth the flakiness.

**References**: `GET /repos/{owner}/{repo}/rulesets` and `GET /repos/{owner}/{repo}/rulesets/{id}` at [docs.github.com/en/rest/repos/rules](https://docs.github.com/en/rest/repos/rules).

---

### R-003: `conditions.ref_name.include` matching rules

**Decision**: A ruleset is considered to cover the audited branch iff its `conditions.ref_name.include` contains at least one entry that matches AND its `conditions.ref_name.exclude` contains no entry that matches. Matching semantics:

- `~DEFAULT_BRANCH` matches iff the audited branch equals the repository's default branch.
- `~ALL` matches every branch.
- Exact bare branch name (e.g., `main`) matches iff equal to the audited branch.
- `refs/heads/<name>` matches iff `<name>` equals the audited branch.
- Any pattern containing a glob metacharacter (`*`, `?`, `[`) is TREATED AS NOT MATCHING for v0 and reported in the evidence's `considered_rulesets` list. A future v0.1 can extend to glob matching using `fnmatch` semantics (git-ref globbing is more complex than POSIX fnmatch, so v0 conservatively excludes).

**Rationale**: The four spec'd values cover every real-world configuration we have seen (default-branch pseudo-ref, exact-name, git-ref, all-refs). Glob patterns are legal on GitHub's side but rare in practice for branch-protection use cases (they're more common for tag rulesets). Excluding them in v0 is the conservative-by-default posture — if a ruleset uses a glob to cover the default branch, the framework will fall back to "considered but did not match" and the audit produces FAIL (assuming no other satisfying ruleset). That is the wrong direction versus the constitution's "false FAIL better than false PASS" rule but the RIGHT direction versus this feature's premise: we do not silently PASS on a glob we didn't evaluate.

**Alternatives considered**:

- **Implement glob matching in v0 using `fnmatch.fnmatchcase`.** Rejected because git ref-name pattern syntax has documented differences from `fnmatch` (multi-segment `**`, character-class semantics). Getting this right requires more thought than a v0 warrants; documented for v0.1.
- **Warn (WARN) instead of "not match" when the include list contains only glob patterns.** Considered but rejected: a ruleset whose sole `include` is a glob and the audited branch does not fall inside it should be a clear "not applicable to this branch," not an ambiguity. The WARN would misuse the semantic. The `considered_rulesets` evidence field surfaces the glob for the human, which is enough for a user to escalate.

---

### R-004: Handler name registration

**Decision**: Register the sieve handler under the short name `github_branch_protection` via `darnit-baseline`'s `register_handlers()`. Handler function name: `github_branch_protection_handler` (matches existing `generate_threat_model_handler` naming).

**Rationale**: Matches darnit's existing handler-naming pattern (verb-noun-underscore, e.g., `file_exists`, `api_call`, `manual_steps`). The `github_` prefix leaves room for a future `gitlab_branch_protection` if we ever extend to GitLab, and the `_branch_protection` suffix is more specific than a generic `branch_check` would be. Baseline is the correct package for it: this handler is domain-specific to the OSPS Baseline's four branch-protection controls, not a general framework primitive.

**Alternatives considered**:

- **`branch_protection` (no `github_` prefix).** Rejected because it implies platform-neutrality that this handler does not provide. Better to keep the platform in the name.
- **`gh_branch_protection`.** Considered; rejected because the framework has other handlers that use spelled-out product names (`sigstore`, `github`) rather than CLI abbreviations, and consistency wins.
- **Register in `packages/darnit/` core instead of baseline.** Rejected: Layer 1 built-ins in core are the platform-neutral primitives (`file_exists`, `exec`, `pattern`, `manual`). Domain-specific handlers belong to their implementation package.

---

### R-005: `gh_api_with_status` return type accommodates both dict and list bodies

**Decision**: The helper's return type is `tuple[dict | list | None, int, str]`. The rulesets list endpoint returns a JSON array at the top level (unlike most other REST endpoints, which return a dict). The helper does not coerce; the caller inspects the type. The existing `gh_api()` wrapper narrows to `dict` when its typed contract requires it and raises when the response is a list (this narrowing is done in the tiny thin-wrapper implementation, preserving backward compatibility with today's callers).

**Rationale**: The alternative — always coercing to dict via `{"data": [...]}` for list responses — would leak wrapper semantics into the caller and require every rulesets-endpoint consumer to unwrap. The union return type is honest.

**Alternatives considered**:

- **Two separate helpers, `gh_api_with_status_dict` and `gh_api_with_status_list`.** Rejected: two names for the same operation invites drift in error handling and pagination logic. One helper, one contract.

---

### R-006: Test isolation via module-level function substitution

**Decision**: The handler tests mock at `darnit_baseline.branch_protection.gh_api_with_status` (module-level substitution via `monkeypatch.setattr`). A small helper class `_GhResponseSequencer` in the test module encapsulates the "return this response for the Nth call matching this endpoint pattern" pattern, so each test case reads as a small script of expected exchanges.

**Rationale**: Mocking at the helper level, not at `subprocess.run`, keeps the tests independent of the `gh` CLI's installed version, its stderr format changes, and its argv layout. It also lets us assert on the exact endpoints and order of API calls, which is load-bearing for spec SC-004 (API call budget) and SC-005 (zero cost when the four controls are excluded).

**Alternatives considered**:

- **Mock `subprocess.run` directly.** Rejected: forces every test to construct `subprocess.CompletedProcess` objects with the right stderr format; couples tests to `gh` behavior we already parsed once in the helper.
- **Use a real HTTP mock server (like `responses` or `pytest-httpx`).** Rejected: the transport is `gh` (subprocess), not HTTP; a HTTP mock would not exercise the helper's stderr parsing. Would also introduce a test-only dependency.
- **Full integration tests against `github.com` with a fixture repo.** Considered valuable but out of CI scope. Documented in `quickstart.md` for manual smoke-testing.

---

### R-007: Cap on `considered_rulesets` in evidence record

**Decision**: On a FAIL verdict, the evidence record's `considered_rulesets` field enumerates every active ruleset that targeted the audited branch but did not satisfy the requirement, capped at 20 entries with a `truncated: N` suffix indicating how many more were seen. On PASS via ruleset, only the matched ruleset appears (no list). On WARN, the field is omitted entirely (source enum values `INSUFFICIENT_ACCESS` and `PARTIAL_FETCH` are self-explanatory).

**Rationale**: This closes the clarification-session deferral about evidence-record shape on FAIL. Twenty is a generous cap: repos with more than 20 active branch-targeting rulesets that all fail the same requirement are pathological and the excess entries would not add operator value. The `truncated: N` suffix preserves the count for the audit report so a maintainer can see there's more to inspect and know to run `gh api` manually.

**Alternatives considered**:

- **No cap.** Rejected: risks bloating audit report file sizes for pathological repos.
- **Log all, evidence-record-summarize as count only.** Considered; rejected because the handler tests want to assert on which rulesets were considered by name, not just count. A capped list preserves testability.
- **20 is arbitrary; parameterize.** Rejected for v0. Add a knob only if a real deployment needs one.

## Consolidated output

All NEEDS CLARIFICATION unknowns from Technical Context are resolved. Proceeding to Phase 1.
