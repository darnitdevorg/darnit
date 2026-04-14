# Output Format Contract: Multi-File Threat Model

**Date**: 2026-04-13 | **Spec**: [../spec.md](../spec.md)

## File Layout

All paths are relative to repository root.

```
docs/threatmodel/
├── SUMMARY.md
├── data-flow.md
├── raw-findings.json
└── findings/
    ├── <slug-1>.md
    ├── <slug-2>.md
    └── ...
```

## SUMMARY.md

```markdown
# Threat Model Report

## Executive Summary

| Field | Value |
|-------|-------|
| Repository | `owner/repo` |
| Scan date | `YYYY-MM-DD HH:MM UTC` |
| Languages scanned | `Python, Go, JavaScript` |
| Files scanned | `N` |
| Total findings | `N` |
| Vulnerability classes | `N` |
| Mitigated | `N` |
| Unmitigated | `N` |

## Top Risks

| Class | STRIDE | Instances | Severity | Mitigated | Details |
|-------|--------|-----------|----------|-----------|---------|
| Command Injection via subprocess | Tampering | 27 | CRITICAL | 8/27 | [Details](findings/python-sink-dangerous_attr.md) |
| SSRF via requests | Information Disclosure | 4 | HIGH | 0/4 | [Details](findings/python-sink-ssrf.md) |
| ... | ... | ... | ... | ... | ... |
| *and 17 more classes* | | | | | [All findings](findings/) |

> Table capped at 20 rows by max severity. All classes have detail files regardless of cap.

## Unmitigated Findings

Findings with no sidecar decision or status `unmitigated`:

| Class | Instances | Max Severity | Details |
|-------|-----------|-------------|---------|
| SSRF via requests | 4 | HIGH | [Details](findings/python-sink-ssrf.md) |
| ... | ... | ... | ... |

> This section is NOT capped. Every class with at least one unmitigated instance appears here.

## Data Flow

See [data-flow.md](data-flow.md) for the asset inventory and data-flow diagram.

## Raw Data

See [raw-findings.json](raw-findings.json) for the complete machine-readable export.

## Recommendations

[Tiered action items by severity band — same content as current output]

## Verification Prompts

<!-- darnit:verification-prompt-block -->
[LLM verification instructions — same format as current output]
<!-- /darnit:verification-prompt-block -->

## Limitations

[Scan stats, Opengrep availability, shallow mode note if applicable]
```

## findings/<slug>.md

```markdown
# Command Injection via subprocess

**STRIDE Category**: Tampering
**Rule**: `python.sink.dangerous_attr`
**Max Severity**: CRITICAL (9 × 1.0)

## Mitigation

> Validate and sanitize all inputs before passing to subprocess calls.
> Prefer argument lists over shell=True. Use shlex.quote() for shell
> arguments when shell=True is unavoidable.

## Representative Examples

<details>
<summary>packages/darnit/src/darnit/sieve/builtin_handlers.py:142</summary>

\```python
result = subprocess.run(command, shell=True, capture_output=True)
\```

</details>

[1-3 snippets from the highest-severity instances]

## All Instances

| # | File | Line | Severity | Confidence | Status |
|---|------|------|----------|------------|--------|
| 1 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 142 | 9 | 1.0 | Unmitigated |
| 2 | `packages/darnit-baseline/src/darnit_baseline/remediation/exec_handler.py` | 87 | 9 | 0.9 | Mitigated |
| ... | ... | ... | ... | ... | ... |

> 27 instances total. Status reflects `.project/threatmodel/mitigations.yaml`.
```

## data-flow.md

Same structure as the current `THREAT_MODEL.md` sections for asset inventory and DFD. Extracted verbatim from the existing `_render_asset_inventory()` and `_render_dfd()` output.

```markdown
# Data Flow Analysis

## Asset Inventory

### Entry Points
[Table of entry points — same format as current output]

### Data Stores
[Table of data stores — same format as current output]

### Authentication Mechanisms
[Table of auth mechanisms — same format as current output]

## Data Flow Diagram

\```mermaid
flowchart LR
  ...
\```

## Attack Chains

[Multi-hop paths from entry point to sink — same format as current output]
```

## raw-findings.json

```json
{
  "metadata": {
    "repository": "owner/repo",
    "scan_date": "2026-04-13T12:00:00Z",
    "languages": ["python", "go", "javascript"],
    "files_scanned": 245,
    "opengrep_available": false
  },
  "findings": [
    {
      "query_id": "python.sink.dangerous_attr",
      "category": "TAMPERING",
      "title": "Command Injection via subprocess",
      "severity": 9,
      "confidence": 1.0,
      "file": "packages/darnit/src/darnit/sieve/builtin_handlers.py",
      "line": 142,
      "end_line": 142,
      "snippet": "result = subprocess.run(command, shell=True, capture_output=True)",
      "fingerprint": "sha256:a1b2c3d4e5f6g7h8",
      "mitigation": {
        "status": "mitigated",
        "note": "Input is validated upstream",
        "reviewer": "@alice",
        "reviewed_at": "2026-04-10",
        "stale": false
      }
    },
    {
      "query_id": "python.sink.dangerous_attr",
      "category": "TAMPERING",
      "title": "Command Injection via subprocess",
      "severity": 9,
      "confidence": 0.9,
      "file": "some/other/file.py",
      "line": 55,
      "end_line": 55,
      "snippet": "os.system(user_input)",
      "fingerprint": "sha256:b2c3d4e5f6g7h8i9"
    }
  ],
  "entry_points": [...],
  "data_stores": [...],
  "file_scan_stats": {...}
}
```

**Notes**:
- `mitigation` object is present only when a sidecar entry matches the finding's fingerprint (FR-004).
- `findings` array contains every finding — no cap, no truncation.
- `fingerprint` is always present on every finding.

## Invariants

1. Every `FindingGroup` with ≥1 finding produces exactly one `findings/<slug>.md` file.
2. The sum of instance counts across all detail files equals the length of `raw-findings.json`'s `findings` array.
3. SUMMARY.md's top-risks table rows + the overflow count = total number of groups.
4. SUMMARY.md's Unmitigated section includes every group where at least one finding lacks a sidecar entry with status in {mitigated, accepted, false_positive}.
5. Regeneration with identical inputs produces byte-identical output files (FR-016).
