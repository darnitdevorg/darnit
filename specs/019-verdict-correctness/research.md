# Research: verdict correctness (issues #342 and #343)

## R1: Current CEL post-step semantics

**Decision:** The framework's CEL post-step at `packages/darnit/src/darnit/sieve/orchestrator.py:60-75` is the direct cause of #343. It reads:

```python
if cel_result.value:
    return HandlerResult(status=HandlerResultStatus.PASS, ...)
else:
    return HandlerResult(status=HandlerResultStatus.INCONCLUSIVE, ...)
```

This maps CEL true -> PASS and CEL false -> INCONCLUSIVE regardless of what the handler originally returned. For the branch-protection controls, the exec handler returns FAIL (exit code 1 matches `fail_exit_codes = [1]`), then the CEL expression `has(output.json.required_pull_request_reviews)` returns false on the 404 body, and the FAIL is demoted to INCONCLUSIVE. The pipeline then falls through to the `manual` handler, which yields "needs verification" -> WARN.

**Rationale for changing this vs a per-control CEL workaround:** the current behavior treats CEL as overriding the handler entirely, which is not what §V of the constitution intends ("orchestrator stops at first conclusive result"). A per-control CEL rewrite would be fragile (CEL cannot easily express "keep the handler's FAIL") and would not fix similar bugs in the other 11 controls that combine `fail_exit_codes` + `expr` (see R5).

**Alternatives considered:** (a) TOML-only CEL workaround per control — rejected as fragile and localized; (b) new TOML config knob `expr_semantics` — rejected as unnecessary surface area; the semantics we want are the correct default.

## R2: exec handler exit-code classification

**Decision:** Confirmed at `packages/darnit/src/darnit/sieve/builtin_handlers.py:247-266`:

```python
if proc.returncode in pass_exit_codes:
    return PASS
elif fail_exit_codes and proc.returncode in fail_exit_codes:
    return FAIL
else:
    return INCONCLUSIVE
```

No change needed to the exec handler. The classification is correct; the downstream CEL post-step is what corrupts the verdict.

## R3: `gh api` behavior for unprotected branch

**Decision:** For a branch with no protection, `gh api /repos/{owner}/{repo}/branches/{branch}/protection` returns HTTP 404 with body:

```json
{
  "message": "Branch not protected",
  "documentation_url": "https://docs.github.com/rest/branches/branch-protection#get-branch-protection",
  "status": "404"
}
```

`gh api` exit code is `1`. The exec handler's `output_format = "json"` parses the body into `output.json`, so `output.json.message == "Branch not protected"` is available inside CEL if needed for a per-control expression. Tests should include a fixture with exactly this response shape (status 404, JSON body, exit code 1).

**Rationale:** the message string is stable and appears in official GitHub REST docs. Matching on `output.json.message == "Branch not protected"` is a stronger signal than matching on exit code 1 alone (which could also mean network failure, auth failure, or other 4xx).

**Alternatives considered:** exit-code-only matching (too broad — 404 for other reasons like nonexistent branch also produces exit 1); status-only matching (`output.json.status == "404"` — same issue).

## R4: Regression-test source of truth for per-level counts

**Decision:** Vendor the upstream OSPS Baseline YAML files under `tests/darnit_baseline/fixtures/osps-baseline/` (or reuse an existing fixture location if one already holds them for the drift check), and parse them at test time to derive expected per-level counts for the pinned `spec_version`. The test is marked `unit` (no network) and runs on every PR.

**Rationale:** three options were considered:
- **Fetch at test time.** Rejected: introduces network dependency in unit tests; fragile against upstream outages.
- **Hard-code the expected counts (24/18/20).** Rejected: the test would silently drift out of correctness if upstream changes; the whole point is to detect drift.
- **Vendor + parse.** Accepted: the vendored copy is the source of truth for the pinned spec version; a spec bump becomes an explicit, reviewable diff (vendor bump + expected-counts update) rather than a silent drift.

**Existing infrastructure:** the repo already has an `upstream` pytest mark on a CNCF spec-drift check (`tests/` — search for `mark.upstream`). That check runs nightly and does not block PRs by design (see `.github/workflows/ci.yml` mark exclusion). The per-level counts test is *different* — it must block PRs. Do not conflate the two marks.

## R5: Regression audit for orchestrator change

**Decision:** Twelve controls combine `fail_exit_codes` + `expr` in the same pass and are affected by the orchestrator change:

```
OSPS-AC-01.01, OSPS-AC-02.01, OSPS-AC-03.01, OSPS-AC-03.02, OSPS-BR-03.01,
OSPS-GV-02.01, OSPS-LE-02.01, OSPS-QA-01.01, OSPS-QA-03.01, OSPS-QA-07.01,
OSPS-VM-03.01, OSPS-VM-04.01
```

For all twelve, the exec handler returns FAIL only when `proc.returncode == 1` (matches `fail_exit_codes`). In that state:

- **Old:** CEL true -> PASS, CEL false -> INCONCLUSIVE. Both are wrong: a handler-conclusive FAIL should not become PASS just because CEL evaluates truthily on an incomplete evidence dict, and it should not become INCONCLUSIVE when CEL agrees the pass condition is unmet.
- **New:** CEL true -> INCONCLUSIVE (handler and CEL disagree; ambiguous, safer to be inconclusive), CEL false -> FAIL (both agree; conclusive). This aligns with §II (conservative-by-default) and §V (respect handler conclusion).

**Regression risk:** low. A test that today expects PASS from an `fail_exit_codes`+`expr` combo would be exercising the "handler said fail but CEL said pass" ambiguity, which is not a coherent PASS signal. Such a test's assertion likely reflects the bug, not a real user requirement. The plan's tasks include auditing the existing test suite for such assertions.

**Rationale:** the alternative — leave the orchestrator alone and paper over #343 per-control — would leave 11 other controls in the same broken state.

## R6: LE-01.01 semantic content vs upstream (out of scope, noted)

**Observation:** darnit's `openssf-baseline.toml` defines `OSPS-LE-01.01` with `name = "HasLicense"`, `description = "Repository has a license file"`, and a `file_exists` + regex-content check against `LICENSE` / `LICENSE.md` / `COPYING`. OSPS Baseline v2025.10.10 defines `OSPS-LE-01.01` as a legal-contribution track (DCO or CLA) at maturity 2/3. These are not the same control.

**Decision:** Out of scope for this spec. This spec fixes only the level tag; the content misalignment (darnit's implementation checks license file, not contribution track) is a separate issue that should be filed after this ships. Fixing the tag first still improves correctness because it stops over-scoping the Level 1 audit; fixing the content later is an independent change that would replace the pass definitions and remediation.

**Follow-up:** file an issue after this feature ships noting the semantic drift and pointing at upstream `baseline/OSPS-LE.yaml`.

## Consolidated per-level counts (target)

For OSPS Baseline v2025.10.10, after this fix:

| Level | Count | Notes |
|-------|-------|-------|
| 1     | 24    | LE-01.01 removed from L1 |
| 2     | 18    | LE-01.01 added to L2 |
| 3     | 20    | Unchanged |

These match `docs/USAGE_GUIDE.md:137-139` and the upstream OSPS applicability.
