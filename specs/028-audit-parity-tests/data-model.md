# Phase 1 Data Model: Two-Tier Audit Parity Tests

**Feature**: 028-audit-parity-tests | **Date**: 2026-08-09

All entities in this feature are TEST-side only. No production data model changes.

## 1. `Fixture`

Location on disk: `tests/darnit/parity/fixtures/<name>/`

Not a Python class; represented by a filesystem directory. A directory is "a fixture" iff it satisfies:

- Contains a `.baseline.toml` at its root (required).
- Optionally contains `.project/project.yaml` for context values.
- Optionally contains a `parity.toml` at its root declaring expected shape (see section 2).
- May contain any other repo files the controls reference (LICENSE, README, `.github/`, etc.).

**Identity**: the directory name (e.g. `all_pass_repo`). Used as the pytest test ID.

**Discovery**: `tests/darnit/parity/tier1/conftest.py` iterates `tests/darnit/parity/fixtures/` and yields each directory that contains `.baseline.toml`.

## 2. `parity.toml` schema (fixture metadata)

Location: `tests/darnit/parity/fixtures/<name>/parity.toml`

Optional per-fixture file. Absence is allowed; a fixture without `parity.toml` still participates in inter-path parity assertions but is excluded from corpus-inventory checks (SC-008).

```toml
[expected]
# One of "all_pass", "all_fail", "mixed", "pending_llm".
# Used by SC-008 corpus-inventory check.
category = "mixed"

# Expected control-status distribution when running the audit via EITHER
# the MCP tool or the harness (they must agree modulo the PENDING_LLM
# allowed drift). Purely informational for regression clarity; not
# enforced against runtime counts unless `strict = true`.
[expected.counts]
pass = 3
fail = 2
warn = 1
error = 0
n_a = 0
# Number of controls the MCP tool leaves PENDING_LLM. The harness
# resolves these; harness's `warn` may be higher than tool's by this many.
pending_llm = 1

# Optional flags
[expected]
has_pending_llm = true   # true if pending_llm > 0
strict = false           # if true, counts are enforced (mismatch fails);
                         # if false, counts are advisory (mismatch logs a note)

# Optional per-control expectations. Rarely used; when present, overrides
# aggregate count checks for the named controls.
[[expected.controls]]
id = "OSPS-GV-01.01"
status = "PASS"           # what BOTH paths must report
```

**Validation** (`tier1/fixture_meta.py`):

- Parses via stdlib `tomllib`.
- `category` MUST be one of the four literals.
- `counts.*` must be non-negative integers.
- `has_pending_llm` MUST match `counts.pending_llm > 0`.
- Unknown keys log a warning but do not fail (forward-compatibility).

## 3. `AuditResult` (normalized comparison target)

Module: `tests/darnit/parity/tier1/comparator.py`

```python
@dataclass(frozen=True)
class Control:
    id: str
    status: Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM"]
    authority: Literal["dispositive", "suggestive", "asserted"] | None
    level: int | None

@dataclass(frozen=True)
class AuditResult:
    """Normalized shape both the MCP tool JSON and the harness report
    reduce to for comparison."""

    controls: tuple[Control, ...]
    source: Literal["mcp_tool", "harness"]

    @classmethod
    def from_mcp_json(cls, payload: dict) -> AuditResult:
        """Parse the JSON output of audit_openssf_baseline(output_format='json')."""
        ...

    @classmethod
    def from_harness_report(cls, report: HarnessReport) -> AuditResult:
        """Reduce a HarnessReport (feature 026 model) to the same shape."""
        ...
```

**Notes**:

- The MCP tool returns a JSON string with a top-level `results` list; each result has `id`, `status`, `authority`, `level` at minimum. `from_mcp_json` picks those four fields.
- The harness's `HarnessReport.controls` is a list of dicts with the same shape. `from_harness_report` picks the same four.
- Frozen dataclass so `AuditResult` instances are hashable + immutable across the comparator's iterations.

## 4. `DriftEntry` (one comparison row)

Module: `tests/darnit/parity/tier1/comparator.py`

```python
@dataclass(frozen=True)
class DriftEntry:
    fixture_name: str
    control_id: str
    mcp_status: str
    harness_status: str

    @property
    def is_allowed_drift(self) -> bool:
        """PENDING_LLM -> any non-PENDING_LLM is allowed (R2).
        Any other status difference is disallowed.
        Statuses that agree don't produce DriftEntry at all."""
        if self.mcp_status == "PENDING_LLM" and self.harness_status != "PENDING_LLM":
            return True
        return False
```

## 5. `ParityReport` (comparator output)

Module: `tests/darnit/parity/tier1/comparator.py`

```python
@dataclass(frozen=True)
class ParityReport:
    fixture_name: str
    total_controls: int
    agreements: int
    drifts: tuple[DriftEntry, ...]

    @property
    def disallowed_drifts(self) -> tuple[DriftEntry, ...]:
        return tuple(d for d in self.drifts if not d.is_allowed_drift)

    @property
    def is_green(self) -> bool:
        return len(self.disallowed_drifts) == 0

    def format_summary_line(self) -> str:
        """FR-013 evidence line, emitted on every run."""
        allowed = sum(1 for d in self.drifts if d.is_allowed_drift)
        return (
            f"[tier1] {self.fixture_name}: "
            f"{self.total_controls} controls compared, "
            f"{self.agreements} agreed, "
            f"{len(self.disallowed_drifts)} diverged, "
            f"{allowed} allowed-drift"
        )

    def format_failure_table(self) -> str:
        """Only called when there are disallowed drifts. Produces a
        fixed-width Markdown table (no ANSI) for pytest assertion messages."""
        ...
```

**FR-004 shape**: `format_failure_table` produces something like:

```
| control_id            | mcp_status | harness_status |
|-----------------------|------------|----------------|
| OSPS-GV-01.01         | PASS       | FAIL           |
| OSPS-BR-06.01         | FAIL       | WARN           |
```

## 6. `SkillReport` (Tier 2 parsed skill output)

Module: `tests/darnit/parity/tier2/skill_markdown_parser.py`

```python
@dataclass(frozen=True)
class SkillReport:
    parseable: bool
    raw_markdown: str            # always populated
    counts: dict[str, int] | None    # {"pass": 51, "fail": 5, ...} or None if unparseable
    controls: tuple[Control, ...] | None  # per-control claims or None if unparseable
    parse_notes: tuple[str, ...] # human-readable notes on best-effort extractions

    @classmethod
    def parse(cls, markdown: str) -> SkillReport:
        """Best-effort regex parser. Never raises; sets parseable=False
        instead of failing."""
        ...
```

**Failure classification**:

- `parseable == False` -> Tier 2 emits "skill output unparseable" verdict; NOT "skill and tool disagree." Distinct failure class per FR-006a.
- `parseable == True` but counts differ from tool -> "counts disagree" verdict.
- `parseable == True` and per-control claims differ from tool -> "per-control disagree" verdict (strongest, includes the offending control IDs in the failure artifact).

## 7. Tier 2 artifact bundle

For every fixture Tier 2 exercises (whether pass or fail), the workflow writes:

```
parity-artifacts/
+-- <fixture_name>/
    +-- mcp_tool_result.json     # Raw stringified JSON from audit_openssf_baseline
    +-- skill_final_message.md   # The final assistant message from the Agent SDK invocation
    +-- diff_report.md           # Human-readable diff (pass or fail); FR-009 requirement
    +-- metadata.json            # invocation timestamp, actor, git SHA, model ID, turn count
```

`parity-artifacts/` is uploaded via `actions/upload-artifact` at end of job. Retention: 30 days by default (a GitHub setting; not spec-controlled).

## 8. Relationship to existing product entities

- **Consumer of `darnit_baseline.tools.audit_openssf_baseline`**: Tier 1 imports and calls; Tier 2 imports and calls before invoking the SDK.
- **Consumer of `darnit.harness.driver.HarnessRun`**: Tier 1 constructs with `MockLLMStep`; never Tier 2.
- **Consumer of `darnit.core.llm_step.MockLLMStep`**: Tier 1 only.
- **No modification of `HarnessRun`, `HarnessReport`, `audit_openssf_baseline`, or any product model.** SC-006 hard rule.
