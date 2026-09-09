# Phase 1: Data Model -- Distinguishable Side-Effect Failures via `error_class`

**Feature**: 036-tier2-error-class | **Date**: 2026-09-07

No database schema. These are the in-memory types and the wire shapes they serialize into.

## E-001: `ErrorClass` type

New module `packages/darnit/src/darnit/core/error_class.py`, mirroring `core/authority.py:15`.

```python
ErrorClass = Literal[
    "network",     # unreachable, DNS failure, TLS error, generic subprocess failure
    "auth",        # 401, bad credentials, expired token, signature verification failure
    "timeout",     # subprocess or MCP call exceeded its timeout budget
    "rate_limit",  # GitHub primary or secondary rate limit
    "not_found",   # required binary or server absent from PATH
    "crashed",     # unexpected exception; handler did not complete cleanly
]
```

Paired with a runtime-checkable frozenset in the same module:

```python
_ERROR_CLASSES: frozenset[ErrorClass] = frozenset((
    "network", "auth", "timeout", "rate_limit", "not_found", "crashed",
))
```

**Why both** (FR-002a): `typing.Literal` is a static-analysis construct erased at runtime -- assigning `error_class="bogus"` to a field annotated `ErrorClass | None` raises nothing. The frozenset is what `HandlerResult.__post_init__` checks against, and it is therefore the mechanism that actually delivers the rejection guarantee. `core/authority.py` uses the identical Literal+frozenset pairing, but for a fail-safe (`is_terminal_authority()` returns False for unknowns) rather than a rejection; this feature rejects instead because an unknown `error_class` has no safe default -- it is neither "the check failed" nor "the check could not run".

**Expansion rule** (clarify Q2): adding a value requires editing BOTH the Literal and the frozenset, plus a new darnit release. No config-driven extension.

**Semantic distinction**: every value means "the check could not run to completion." None of them mean "the check ran and the repo does not comply" -- that stays a bare `FAIL`/`WARN` with no `error_class`.

## E-002: `HandlerResult.error_class`

`packages/darnit/src/darnit/sieve/handler_registry.py`, existing `@dataclass`.

```python
@dataclass
class HandlerResult:
    status: HandlerResultStatus
    message: str
    confidence: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    authority: Authority | None = None
    error_class: ErrorClass | None = None   # NEW -- last field, keeps positional compat
```

**Set by**: the handler that experienced the environmental failure. `None` on every success path and on every clean FAIL (the check ran, the repo doesn't comply).

**Invariants**, both enforced in `__post_init__` (see contract section 6):

1. `error_class`, when set, must be a member of `_ERROR_CLASSES` (FR-002a).
2. `error_class` is never set alongside `status = PASS`. A handler that could not complete cannot produce a real PASS.

## E-003: `SieveResult.error_class`

`packages/darnit/src/darnit/sieve/models.py`, existing `@dataclass`. The per-control object the orchestrator returns.

```python
error_class: ErrorClass | None = None
```

**Populated from**: the RESOLVING pass's `HandlerResult.error_class` only (FR-009a / clarify Q1). The orchestrator already tracks which pass resolved the control (`resolving_pass_index`, `resolving_pass_handler` fields), so this is a one-line assignment adjacent to where those are set.

**Not populated from**: earlier non-resolving passes. If pass 1 timed out and pass 2 resolved the control on real evidence, the `SieveResult` carries no `error_class` -- pass 2's clean conclusion supersedes pass 1's environmental failure.

## E-004: `CheckResult["error_class"]`

`packages/darnit/src/darnit/sieve/models.py`, existing `TypedDict`. The wire shape.

```python
class CheckResult(TypedDict):
    # ... Required block unchanged ...
    authority: NotRequired[str]
    error_class: NotRequired[str]   # NEW -- adjacent to authority, same rationale
```

**Emitted only when set** (FR-011). Absent, not `null`, not empty string. `SieveResult.to_legacy_dict()` conditionally includes it, matching how `authority` is handled.

**Typed as `str` not `ErrorClass`** because `CheckResult` is the deserialization boundary -- results loaded from a pre-feature serialized state won't have the field, and results from a future darnit version might carry a value this version's Literal doesn't know. `str` at the wire boundary, `ErrorClass` in memory. Same split `authority` uses (`Authority` on the dataclass, `str` in the TypedDict).

## E-005: GitHub stderr classification pattern sets

Module-level constants in `packages/darnit/src/darnit/sieve/builtin_handlers.py`, adjacent to `MCP_DEFAULT_TIMEOUT_SECONDS`.

```python
_GH_RATE_LIMIT_PATTERNS: tuple[str, ...] = (
    "API rate limit exceeded",
    "secondary rate limit",
    "abuse detection mechanism",
)

_GH_AUTH_PATTERNS: tuple[str, ...] = (
    "HTTP 401",
    "Bad credentials",
    "requires authentication",
    "gh auth login",
    "authentication token",
)
```

**Matching**: case-insensitive substring check against the exec handler's captured stderr (already truncated to 500 chars in the existing evidence shape).

**Order matters**: rate-limit patterns are checked FIRST. GitHub returns 403 for both rate limits and permission failures; a rate-limit body is the more specific signal, so it wins when both could match (spec edge case: "403 without rate-limit signal" -> `auth`).

**GitHub-only for v0** (clarify Q4). Non-GitHub exec targets whose stderr matches neither set fall through to `network` (FR-005a).

## Relationships

```
exec_handler / mcp_handler / auto_detect
    -> classifies failure
    -> HandlerResult(status=ERROR|FAIL|INCONCLUSIVE, error_class=<ErrorClass>)
        |
        v
_apply_cel_expr  [orchestrator]
    -> may transition status across 4 paths
    -> MUST thread error_class through every new HandlerResult it constructs
        |
        v
orchestrator pass cascade
    -> picks resolving pass
    -> SieveResult(error_class=<resolving pass's error_class>)   [FR-009a]
        |
        v
SieveResult.to_legacy_dict()
    -> CheckResult{..., "error_class": "<value>"}   [conditional emit]
        |
        +--> markdown formatter    [tools/audit.py]
        +--> JSON formatter        [darnit-baseline/tools.py, full + summary]
        +--> SARIF formatter       [formatters/sarif.py -> properties["errorClass"]]
        `--> attestation predicate [attestation/predicate.py, conditional emit]
```

Orchestrator's outer exception catch is a fifth producer: it constructs a `HandlerResult(status=ERROR, error_class="crashed")` when a handler raises unexpectedly, then flows through the same path.
