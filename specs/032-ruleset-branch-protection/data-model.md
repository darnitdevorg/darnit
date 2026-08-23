# Phase 1 Data Model: Ruleset-aware branch-protection verdict

## Purpose

Enumerate every new type, its fields, its constraints, and its lifecycle. The vocabulary here is what the plan phase locks in for the reader contract, the tasks decomposition, and future reconciliation-style diffs.

## New types

### `ProtectionRequirement` (str Enum in `branch_protection.py`)

The specific protection a control is testing for. Set via TOML `requirement = "..."` on a `handler = "github_branch_protection"` pass.

| Member | TOML value | Classic surface satisfying signal | Ruleset rule type satisfying |
|--------|-----------|-----------------------------------|------------------------------|
| `REQUIRE_PULL_REQUEST` | `"require_pull_request"` | `required_pull_request_reviews` present | rule with `type == "pull_request"` |
| `PREVENT_DELETION` | `"prevent_deletion"` | `allow_deletions.enabled == false` | rule with `type == "deletion"` |
| `REQUIRE_STATUS_CHECKS` | `"require_status_checks"` | `required_status_checks` present | rule with `type == "required_status_checks"` |
| `REQUIRE_APPROVALS` | `"require_approvals"` | `required_pull_request_reviews.required_approving_review_count >= required_approvals_minimum` | rule with `type == "pull_request"` AND `parameters.required_approving_review_count >= required_approvals_minimum` |

Members are stable identifiers; adding a new one is a non-breaking additive change. Renaming or removing a member is a breaking change to the four affected TOML controls' pass definitions and MUST be paired with a same-PR TOML update.

### `VerdictSource` (str Enum in `branch_protection.py`)

The enumerated evidence-source value written into the handler's evidence record. Locked by spec FR-016.

| Member | TOML/evidence value | When emitted |
|--------|--------------------|--------------|
| `CLASSIC` | `"classic"` | Classic protection endpoint returned 200 AND carried the required signal. Rulesets were not consulted. |
| `RULESET` | `"ruleset"` | Rulesets were consulted (classic did not carry the signal) AND at least one active ruleset targeting the branch satisfies the requirement. Evidence includes the matched ruleset's `id` and `name`. |
| `NEITHER_SURFACE_PROVIDED_PROTECTION` | `"neither-surface-provided-protection"` | Both surfaces responded successfully; neither carried the required signal. Verdict is FAIL. |
| `INSUFFICIENT_ACCESS` | `"insufficient-access"` | Either surface returned 401 or 403. Verdict is WARN. |
| `PARTIAL_FETCH` | `"partial-fetch"` | Rulesets list succeeded but a subsequent detail call (or a subsequent list page) failed for any reason. Verdict is WARN. |

### `HandlerConfig` (TOML surface consumed by the handler)

Shape of the dict handed to the handler by the sieve orchestrator. All fields except `requirement` have defaults.

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `handler` | `str` | required, always `"github_branch_protection"` | Set by the TOML `handler = "..."` key. |
| `owner` | `str` | `"$OWNER"` | Substituted via the sieve's variable-substitution pass before the handler runs. |
| `repo` | `str` | `"$REPO"` | Same. |
| `branch` | `str` | `"$BRANCH"` | Same. Defaults to the repository's default branch when the audit does not specify. |
| `requirement` | `str` | required (no default) | Must be one of the `ProtectionRequirement` TOML values. |
| `required_approvals_minimum` | `int` | `1` | Only meaningful when `requirement == "require_approvals"`. Ignored otherwise. Range `1..10`. |
| `timeout` | `int` | `30` | Total time-budget in seconds across both surfaces (including rulesets pagination). Individual `gh api` invocations inherit this budget; the handler slices no lower. |

### Handler evidence record shape

The dict that ends up in `HandlerResult.evidence` after the handler runs. Consumed by the Markdown formatter, JSON output, and SARIF exporter (all of which treat unknown keys as opaque).

```python
{
    "source": "classic" | "ruleset" | "neither-surface-provided-protection" | "insufficient-access" | "partial-fetch",
    "requirement": "require_pull_request" | "prevent_deletion" | "require_status_checks" | "require_approvals",
    "classic_status": 200 | 404 | 401 | 403 | 429 | 500 | 0,  # 0 == unparseable status
    "rulesets_status": 200 | 401 | 403 | 429 | 500 | 0,        # 0 when call was skipped OR unparseable
    "matched_ruleset": {"id": int, "name": str} | None,        # populated only when source == "ruleset"
    "considered_rulesets": [                                    # populated only when source == "neither-surface-provided-protection"
        {"id": int, "name": str, "reason": str},                # reason describes why this ruleset did not satisfy
        ...
    ],
    "considered_rulesets_truncated": int,                       # count of entries elided when the list exceeded 20 (research R-007)
}
```

Field-by-field ownership:

- `source`, `requirement`, `classic_status` are always populated.
- `rulesets_status` is populated when the handler consulted the rulesets endpoint (source `RULESET`, `NEITHER_SURFACE_PROVIDED_PROTECTION`, `INSUFFICIENT_ACCESS` where the classic surface succeeded, or `PARTIAL_FETCH`). Otherwise omitted (or `0`).
- `matched_ruleset` is populated iff `source == "ruleset"`.
- `considered_rulesets` and `considered_rulesets_truncated` are populated iff `source == "neither-surface-provided-protection"` AND at least one active ruleset targeted the branch (rulesets that did not target the branch are NOT enumerated here; that would bloat the evidence with irrelevant entries).

### `RulesetSummary` (runtime TypedDict, private to `branch_protection.py`)

Minimal type for the ruleset-list response items:

```python
class RulesetSummary(TypedDict, total=False):
    id: int
    name: str
    target: Literal["branch", "tag"]
    enforcement: Literal["active", "evaluate", "disabled"]
    source_type: Literal["Repository", "Organization"]
```

`total=False` because we treat unknown fields as opaque; GitHub may add fields without our knowing.

### `RulesetDetail` (runtime TypedDict, private to `branch_protection.py`)

Detail response fields the handler consumes:

```python
class RefNameConditions(TypedDict, total=False):
    include: list[str]
    exclude: list[str]

class RulesetConditions(TypedDict, total=False):
    ref_name: RefNameConditions

class RulesetRule(TypedDict, total=False):
    type: str                    # "pull_request", "deletion", "required_status_checks", etc.
    parameters: dict[str, Any]

class RulesetDetail(TypedDict, total=False):
    id: int
    name: str
    enforcement: Literal["active", "evaluate", "disabled"]
    conditions: RulesetConditions
    rules: list[RulesetRule]
```

## Existing types touched

### `darnit.core.utils.gh_api_with_status` (new)

New module-level function. Signature and contract:

```python
def gh_api_with_status(
    endpoint: str, *, paginate: bool = False
) -> tuple[dict | list | None, int, str]:
    """Execute a GitHub API call via `gh api` and return (body, status, error).

    On 2xx: returns (parsed_json, status_code, "").
    On non-2xx with parseable `HTTP <code>:` prefix in stderr: returns (None, status_code, stderr_message).
    On any other failure (subprocess not found, network failure, invalid JSON on 2xx):
      returns (None, 0, error_message).

    When `paginate=True`, invokes `gh api --paginate ...` and concatenates all pages into
    a single top-level list (matches `gh`'s pagination-flattening behavior).
    """
```

Existing `gh_api()` and `gh_api_safe()` become thin wrappers:

```python
def gh_api(endpoint: str) -> dict[str, Any]:
    body, status, error = gh_api_with_status(endpoint)
    if status == 200 and isinstance(body, dict):
        return body
    raise RuntimeError(f"gh api failed: {error or 'status ' + str(status)}")
```

The new helper is what the branch-protection handler calls directly. Every existing `gh_api`/`gh_api_safe` caller continues to work unchanged.

### Default-branch resolution (no extra API call)

The handler consumes the repository's default branch from `context.default_branch`, which the audit driver already populates at `packages/darnit/src/darnit/tools/audit.py:428`. This feature does NOT introduce a `GET /repos/{owner}/{repo}` call to resolve the default branch -- doing so would violate SC-004's API-call budget without adding value. If `context.default_branch is None` on a partial context, `_ref_name_matches` conservatively treats `~DEFAULT_BRANCH` include entries as non-matching (Constitution II), rather than paying an API call to guess.

### `docs/architecture/framework-design.md` (small edit)

Add `github_branch_protection` to the handler-name registry table so `scripts/validate_sync.py`'s "Handler names in sync" check finds it. One-line addition; no behavior change.

## Constants introduced

- `MAX_CONSIDERED_RULESETS = 20` in `branch_protection.py` — the cap from research R-007.
- `DEFAULT_TIMEOUT_SECONDS = 30` in `branch_protection.py` — the total per-invocation time budget default.
- `SUPPORTED_REF_INCLUDE_LITERALS = frozenset({"~DEFAULT_BRANCH", "~ALL"})` in `branch_protection.py` — the two pseudo-refs the ref-matching helper recognises beyond exact-name and `refs/heads/<name>`.

## State transitions

The handler is stateless: no persistent lifecycle, no session cache, no cross-invocation state. Every audit-run's invocation of the handler for a given control makes fresh API calls. This matches the constitution's Sieve Pipeline Integrity principle (handlers are pure functions of their inputs plus their side-channel API responses).

## Non-model concerns

Everything else about this feature reuses machinery that already exists in the sieve: CEL binding is not used (the handler decides PASS/FAIL/INCONCLUSIVE itself), the `when = { platform = "github" }` guard is preserved on all four controls, and evidence attaches via the standard `HandlerResult.evidence` dict. No new pydantic models, no schema migrations, no persistent state changes.
