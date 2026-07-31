# Data Model: verdict correctness (issues #342 and #343)

No new entities. This spec touches the existing framework and implementation types listed below.

## Existing entities used

### `PassOutcome` (framework, `packages/darnit/src/darnit/sieve/models.py`)

Four-valued enum representing the result of a single sieve pass.

- `PASS` — verified compliant.
- `FAIL` — verified non-compliant.
- `INCONCLUSIVE` — cannot determine; pipeline continues to next pass.
- `ERROR` — handler or framework failure.

No schema change. The CEL post-step transition table is what changes; see [`contracts/cel-post-step.md`](contracts/cel-post-step.md).

### `HandlerResult` (framework, `packages/darnit/src/darnit/sieve/models.py`)

Handler return value carrying `status: PassOutcome`, `message: str`, `confidence: float`, and `evidence: dict[str, Any]`.

The `evidence` dict is what CEL evaluates against. For exec handlers with `output_format = "json"`, the shape is:

```python
evidence = {
    "stdout": str,
    "stderr": str,
    "exit_code": int,
    "json": dict | list,   # parsed body, absent if JSON decode fails
}
```

No schema change.

### `ControlSpec` (framework, `packages/darnit/src/darnit/core/plugin.py`)

Control definition parsed from TOML. Carries `id`, `name`, `description`, `tags` (including `level: int`), `passes: list[PassSpec]`, `remediation: RemediationSpec`, etc.

**Change:** `OSPS-LE-01.01.tags.level` transitions from `1` to `2` in `packages/darnit-baseline/openssf-baseline.toml`. No structural change to `ControlSpec` itself.

### Upstream OSPS Baseline YAML (external, vendored fixture)

Files: `baseline/OSPS-<domain>.yaml` in `ossf/security-baseline` (pinned to release v2025.10.10). Per-control shape (subset relevant to the regression test):

```yaml
- id: OSPS-LE-01.01
  applicability:
    - maturity-2
    - maturity-3
```

Loaded at test time by `tests/darnit_baseline/test_level_counts.py`; the applicability lists derive the expected per-level control set. Fixture vendored under `tests/darnit_baseline/fixtures/osps-baseline/` (or wherever the existing drift check already keeps a copy — to be reused rather than duplicated).

## Relationships

```
Upstream OSPS YAML (source of truth for pinned spec version)
        |
        | (parsed by test)
        v
Expected per-level control set (24 / 18 / 20)
        =========
Actual per-level control set (from openssf-baseline.toml, via framework config load)
```

Test asserts equality between the two sets and fails with a symmetric diff listing misclassified controls when they diverge.

## State transitions

No new states. The one behavioral change is the CEL post-step transition, documented as a contract in `contracts/cel-post-step.md`.
