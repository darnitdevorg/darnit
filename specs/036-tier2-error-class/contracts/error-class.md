# Contract: `error_class` on the sieve result envelope

**Feature**: 036-tier2-error-class

Everything a consumer of a darnit result may rely on regarding `error_class`. Anything not stated is unspecified.

## 1. The enum

```python
ErrorClass = Literal["network", "auth", "timeout", "rate_limit", "not_found", "crashed"]

_ERROR_CLASSES: frozenset[ErrorClass] = frozenset((
    "network", "auth", "timeout", "rate_limit", "not_found", "crashed",
))
```

Defined at `packages/darnit/src/darnit/core/error_class.py`.

The `Literal` gives static-analysis coverage; the `frozenset` gives runtime coverage. Both are required -- `Literal` is erased at runtime and enforces nothing on its own, so `HandlerResult.__post_init__` checks membership against the frozenset (FR-002a, section 6 rule 1). Adding a value means editing both.

| Value | Meaning |
|---|---|
| `network` | Host unreachable, DNS failure, TLS error, MCP server unusable, or any non-zero subprocess exit whose stderr matched no more-specific pattern. |
| `auth` | HTTP 401, bad credentials, expired token, "requires authentication", or MCP plugin signature-verification failure. |
| `timeout` | Subprocess exceeded its `timeout` budget, or an MCP tool call exceeded `MCP_DEFAULT_TIMEOUT_SECONDS`. |
| `rate_limit` | GitHub primary or secondary rate limit, or abuse-detection throttle. |
| `not_found` | A required binary or MCP server executable is absent from PATH. |
| `crashed` | A handler raised an unexpected exception, or an MCP tool returned unparseable output. The handler did not complete cleanly. |

**Expansion**: adding a value requires editing the Literal + a new darnit release. No config-driven extension (clarify Q2).

**Semantics**: every value means "the check could not run to completion." None means "the check ran and the repo does not comply."

## 2. Classification decision table

### 2.1 `exec_handler`

Checked in this order; first match wins:

| Condition | `error_class` |
|---|---|
| `subprocess.TimeoutExpired` raised | `timeout` |
| Non-zero exit AND stderr matches `_GH_RATE_LIMIT_PATTERNS` (case-insensitive substring) | `rate_limit` |
| Non-zero exit AND stderr matches `_GH_AUTH_PATTERNS` | `auth` |
| Non-zero exit, no pattern match | `network` |
| Exit code in `pass_exit_codes` (success) | `None` |
| Exit code in `fail_exit_codes` (clean, definitive failure) | `None` -- the check ran; the repo doesn't comply |

**Rate-limit precedence**: GitHub returns 403 for both rate limits and permission failures. Rate-limit patterns are checked BEFORE auth patterns so the more specific signal wins.

**GitHub-only for v0** (clarify Q4). Patterns target `gh` CLI stderr shape. Non-GitHub targets (`git`, `curl`, `syft`, `cosign`) fall to `network` on unclassified failure.

### 2.2 `mcp_handler`

Full mapping for all eight `McpPoolError` subclasses (R-007):

| Exception | `error_class` |
|---|---|
| `McpToolTimeout` | `timeout` |
| `McpServerHandshakeFailed` | `network` |
| `McpServerBinaryMissing` | `not_found` |
| `McpServerVerificationFailed` | `auth` |
| `McpServerUnusable` | `network` |
| `McpToolError` | `crashed` |
| `McpToolResponseNotJson` | `crashed` |
| `McpPoolError` (base / unmatched subclass) | `crashed` |

The first three are named in FR-006. The remaining five are documented extensions -- they exist in `sieve/mcp_pool.py` and the handler's `except` clauses catch them; leaving them unclassified would reintroduce the ambiguity this feature removes.

### 2.3 Orchestrator outer exception catch

Any exception escaping a handler invocation that the orchestrator's outer `try/except` catches produces `error_class = crashed`, `status = ERROR`.

### 2.4 Context auto-detect

Git subprocess failures in `detect_platform` (and structurally similar detectors) produce a WARN log carrying `error_class`, classified per section 2.1's exec rules (timeout -> `timeout`, otherwise `network`).

**Note**: auto-detect produces context values, not `HandlerResult`s. The `error_class` here is a log-line field, not a result-envelope field. FR-008's requirement is the loud log, not a new context-value shape.

## 3. Propagation rule

`SieveResult.error_class` comes from the **RESOLVING pass's** `HandlerResult.error_class` only (FR-009a / clarify Q1).

* Pass 1 times out, pass 2 resolves cleanly -> `SieveResult.error_class is None`. Pass 2's clean conclusion supersedes.
* Pass 1 fails cleanly, pass 2 times out and is the resolving pass -> `SieveResult.error_class == "timeout"`.
* All passes exhausted without resolution, last pass had an `error_class` -> that pass is the resolving pass by definition; its `error_class` propagates.

Earlier passes' `error_class` values are discarded, not aggregated. The `pass_history` field already carries the per-pass trail for anyone who needs it.

## 4. CEL post-step preservation obligation

`_apply_cel_expr` (`sieve/orchestrator.py`) MUST preserve `error_class` across every path that constructs a new `HandlerResult`:

| Handler status | CEL result | Post-step status | `error_class` |
|---|---|---|---|
| PASS | true | PASS | preserved from input |
| PASS | false | INCONCLUSIVE | preserved from input |
| FAIL | true | INCONCLUSIVE | preserved from input |
| FAIL | false | FAIL | preserved from input |
| ERROR / INCONCLUSIVE | (not evaluated) | unchanged (same object returned) | preserved trivially |
| no `expr` configured | (not evaluated) | unchanged (same object returned) | preserved trivially |

This is a known bug class in this exact function: feature 026 hit it with `authority` and fixed it by explicitly threading the field through each constructor call. The same treatment is required here. SC-005 requires a test parameterized over all four constructing transitions because the failure mode is silent field-dropping, not an exception.

## 5. Output surfaces

### 5.1 Markdown (`tools/audit.py`)

Rendered as a conditional line in the same block that already emits "Resolved by:" and "Pass history:". Present only when `error_class` is set. Exact rendering is implementation-refinable; the contract is that `error_class` is visually distinguishable from the verdict (FR-010).

### 5.2 JSON (`darnit-baseline/tools.py`)

`error_class` appears as a top-level key on each result object, at the same nesting depth as `status`. Included in **both** the full JSON shape and the summary shape -- a summary that hides "we couldn't verify" defeats the feature (R-006).

Absent when unset. Not `null`, not `""` (FR-011).

### 5.3 SARIF (`darnit-baseline/formatters/sarif.py`)

`sarif_result["properties"]["errorClass"]`. camelCase to match the file's existing convention (`resolvingPassHandler`, `resolvingPassIndex`, `passHistory`). Conditional emit via the same `if X is not None` guard those fields use.

### 5.4 Attestation predicate (`darnit-baseline/attestation/predicate.py`)

Conditional emit immediately after the existing `authority` block:

```python
if r.get("error_class") is not None:
    control["error_class"] = r["error_class"]
```

Additive within the v1 predicate schema. **No version bump** -- same precedent feature 025 set when it added `authority` (R-005).

## 6. Validation rules (enforced in `HandlerResult.__post_init__`)

Two rules, both enforced in code rather than documentation:

**Rule 1 -- unknown-value rejection (FR-002a)**. `Literal` is erased at
runtime, so without this check a typo'd or future-version `error_class`
would flow silently into an attestation as an uninterpretable failure cause.

**Rule 2 -- unrepresentable shape**. `error_class` alongside `status = PASS`
is a bug: a handler that could not complete cannot produce a real PASS.

```python
def __post_init__(self) -> None:
    if self.error_class is not None:
        if self.error_class not in _ERROR_CLASSES:
            raise ValueError(
                f"error_class={self.error_class!r} is not a known ErrorClass; "
                f"expected one of {sorted(_ERROR_CLASSES)}"
            )
        if self.status == HandlerResultStatus.PASS:
            raise ValueError(
                f"error_class={self.error_class!r} is incompatible with status=PASS; "
                "a handler that could not complete cannot produce a PASS"
            )
```

**Deliberate divergence from the `authority` precedent**: `core/authority.py`
pairs its Literal with `_TERMINAL_AUTHORITIES` and uses it for a *fail-safe*
(`is_terminal_authority()` returns False for unknown strings, so an unknown
authority can never conclude a control). That works because authority has a
safe default -- "cannot conclude" is always the conservative answer. An
unknown `error_class` has no equivalent safe default: it is neither "the
check failed" nor "the check could not run". Rejection is the only
conservative option, hence Rule 1 raises rather than degrading.

## 7. Logging obligation

The four classification sites MUST log at WARN (not DEBUG) when they set an `error_class`. Log line MUST name: the control ID (or context key, for auto-detect), the handler, and the `error_class` value.

Scope is exactly those four sites (clarify Q3 / FR-008a). Other DEBUG-level exception handlers in the codebase are NOT swept in v0.

## 8. Happy-path invariance

An audit run with zero environmental failures MUST produce byte-for-byte identical output to the pre-feature implementation in markdown, JSON, SARIF, and attestation predicate (FR-014).

Guaranteed by: every emit site uses a conditional guard; `error_class` defaults to `None`; no unconditional field additions anywhere.

SC-002 is verified against a baseline captured from unmodified `main` BEFORE any implementation task runs (tasks.md T001a), committed to `tests/darnit/fixtures/error_class_baseline/`. Comparing against goldens generated during implementation would be circular -- it would lock post-feature behavior rather than prove pre-feature equivalence. For the same reason the comparison uses plain file diffing, not `syrupy` snapshots, whose `--snapshot-update` workflow would let a real regression be absorbed into the expected value.

## 9. Test surface

| Guarantee | Test location |
|---|---|
| Classification per site (sections 2.1-2.4) | `tests/darnit/sieve/test_error_class_classification.py` |
| CEL preservation, 4 transitions (section 4) | `tests/darnit/sieve/test_error_class_cel_preservation.py` |
| Validation rules 1 and 2 (section 6) | same as classification module (`TestHandlerResultValidation`) |
| Happy-path byte-for-byte invariance (section 8) | `tests/darnit/test_error_class_happy_path.py`, compared against the pre-feature baseline captured in `tests/darnit/fixtures/error_class_baseline/` |
| JSON / SARIF / predicate shapes (section 5) | `tests/darnit_baseline/test_error_class_output_surfaces.py` |
| No new runtime dep (FR-015 / SC-007) | assertion in the happy-path module |
