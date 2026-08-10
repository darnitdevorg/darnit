# Contract: `parity.toml` Schema

**Feature**: 028-audit-parity-tests | **Consumers**: fixture authors adding new corpus entries.

## 1. Location

- **PT-1**: `parity.toml` lives at the root of a fixture directory (`tests/darnit/parity/fixtures/<name>/parity.toml`). Never elsewhere.
- **PT-2**: `parity.toml` is OPTIONAL. A fixture without one still participates in inter-path parity assertions.

## 2. Parsing

- **PT-3**: Parsed by stdlib `tomllib.load()`. No custom TOML parser; no code execution at load time.
- **PT-4**: If `parity.toml` exists but is unparseable TOML, the fixture's Tier 1 test FAILS with a "malformed metadata" error. The fixture is not silently skipped.

## 3. Schema

### 3.1 `[expected]` section

Required top-level table when `parity.toml` exists.

```toml
[expected]
category = "mixed"           # required; one of "all_pass" | "all_fail" | "mixed" | "pending_llm"
has_pending_llm = true       # optional; auto-derived from counts.pending_llm > 0 if absent
strict = false               # optional; default false
```

- **PT-5**: `category` MUST be one of the four literal strings. Any other value fails validation.
- **PT-6**: `has_pending_llm`, when explicitly set, MUST agree with `counts.pending_llm > 0` (if `counts` is present). Disagreement is a validation error.
- **PT-7**: `strict` controls whether `counts` mismatches (see below) FAIL or WARN.

### 3.2 `[expected.counts]` sub-section

Optional. When present, provides expected control-status distribution.

```toml
[expected.counts]
pass = 3
fail = 2
warn = 1
error = 0
n_a = 0
pending_llm = 1
```

- **PT-8**: Every key MUST be a non-negative integer.
- **PT-9**: Unrecognized keys log a warning but do not fail validation (forward-compat).
- **PT-10**: When `strict = true`, the actual counts from a live audit MUST equal the declared counts, or the fixture's Tier 1 test FAILS.
- **PT-11**: When `strict = false` (default), a mismatch produces a non-fatal note in the pytest output (informational; useful when a control's status changes due to an upstream `openssf-baseline.toml` update).

### 3.3 `[[expected.controls]]` array

Optional. Per-control expectations for specific controls.

```toml
[[expected.controls]]
id = "OSPS-GV-01.01"
status = "PASS"

[[expected.controls]]
id = "OSPS-BR-06.01"
status = "FAIL"
```

- **PT-12**: `id` MUST match a control the audit produces for this fixture; otherwise validation warns.
- **PT-13**: `status` MUST be one of the six PassOutcome literals. `PENDING_LLM` is allowed here for the pending_llm category.
- **PT-14**: The actual status from BOTH the MCP tool and the harness (modulo the PENDING_LLM allowed drift) MUST equal `status`. Mismatch fails when `strict = true`; notes when `strict = false`.

## 4. Discovery + iteration

- **PT-15**: `tier1/fixture_meta.py` provides `load_parity_metadata(fixture_dir: Path) -> ParityMetadata | None`. Returns `None` if `parity.toml` is absent.
- **PT-16**: `test_corpus_inventory.py` (SC-008) iterates fixtures, calls `load_parity_metadata`, and counts fixtures per `category`. Passes iff at least one fixture is present in each of the four categories.

## 5. Example: all_pass_repo

```toml
[expected]
category = "all_pass"
has_pending_llm = false
strict = false

[expected.counts]
pass = 8
fail = 0
warn = 0
error = 0
n_a = 4
pending_llm = 0
```

## 6. Example: pending_llm_repo

```toml
[expected]
category = "pending_llm"
has_pending_llm = true

[expected.counts]
pass = 4
fail = 2
warn = 1
error = 0
n_a = 5
pending_llm = 1

[[expected.controls]]
id = "STAGE1-REF-SECURITY-01"
status = "PENDING_LLM"
```

## 7. What `parity.toml` MUST NOT be used for

- **PT-17**: MUST NOT declare allowed drift beyond the canonical Tier 1 table (see `tier1-parity-invariant.md`). If a fixture legitimately needs a different drift class, that is a spec change, not a fixture change.
- **PT-18**: MUST NOT influence what controls run. Fixtures use `.baseline.toml` for that; `parity.toml` is test-side metadata only.
- **PT-19**: MUST NOT contain executable content, template placeholders, or references to environment variables.
