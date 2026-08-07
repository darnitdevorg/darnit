# Contract: Harness Report Format (Markdown + JSON)

**Feature**: 026-darnit-harness
**Date**: 2026-08-05

Shape of the report the harness emits at completion. Applies to both `--format=markdown` (default) and `--format=json`. Consumers -- CI dashboards, issue-generator scripts, `jq`-based pipelines -- rely on this contract.

---

## Markdown format (default)

Ordered sections that MUST appear in this order:

1. `# Darnit Harness Report`
2. `## Summary` -- table with target, timestamp, per-level compliance
3. `## Failed Controls` -- one bullet per FAIL result, with control id + authority + message
4. `## Warned or Pending Controls` -- one bullet per WARN / PENDING_LLM result
5. `## Passed Controls` -- compact list (id + authority) grouped by level
6. `## Answer Sources` -- one line per source with `name` and `known_keys()` count
7. `## LLM Calls` -- one line with total call count + provider identifier

Every control mention in sections 3-5 MUST include the authority in parentheses (e.g., `OSPS-AC-01.01 PASS (dispositive)`).

## JSON format

Top-level object with these fields (all required):

```jsonc
{
  "harness_version": "1.0",
  "target": {
    "local_path": "/path/to/repo",
    "owner": "acme",       // or null if auto-detect failed
    "repo": "widget"       // or null if auto-detect failed
  },
  "summary": {
    "total": 42,
    "pass": 30,
    "fail": 8,
    "warn": 4,
    "n_a": 0,
    "error": 0
  },
  "controls": [
    {
      "id": "OSPS-AC-01.01",
      "status": "PASS",
      "authority": "dispositive",  // MUST be present per feature 025 SC-006
      "level": 1,
      "message": "gh api reports MFA required",
      "evidence": {...}
    }
    // ... one entry per control ...
  ],
  "pending_feedback": [
    {
      "control_id": "STAGE1-REF-SECURITY-01",
      "context_key": "security_contact",
      "question": "Who is the security contact?"
    }
  ],
  "answer_sources_used": ["project_yaml", "--answers /path/to/x.yaml"],
  "llm_calls": {
    "total": 3,
    "provider": "anthropic:claude-sonnet-4-6"
  }
}
```

## Contract items

- **RF-1**: Both formats MUST include an `authority` value for every result (per feature 025 SC-006 + contract T2). JSON includes it as a per-control field; Markdown includes it in the parenthetical.
- **RF-2**: The JSON shape MUST be schema-stable for MVP: no field renames or removals within `1.0`. Future additions are permitted only under new field names; existing fields MUST NOT change semantics.
- **RF-3**: The JSON `summary.pass` field name is the string `"pass"` (Python-side alias from `pass_`; JSON serialization uses the unaliased name). Consumers can safely reference `.summary.pass` in `jq`.
- **RF-4**: The API key MUST NOT appear anywhere in either format.
- **RF-5**: `answer_sources_used` MUST list every source that was consulted (whether or not it contributed a value), in resolver order.
- **RF-6**: `llm_calls.total` counts successful + failed LLM invocations (both count against the provider). A separate `llm_calls.failed` field MAY be added later without breaking `1.0` compatibility.
- **RF-7**: Empty sections in Markdown (e.g., `## Failed Controls` when there are zero FAIL results) MUST render as the heading followed by "None." on a single line. This preserves the section ordering invariant so a downstream `grep` on section headings always finds them.
- **RF-8**: The `exit_class` (0/1/2/3) is NOT emitted in the JSON body; it lives in the process exit code and the stderr summary line only. Consumers that need to correlate report content with exit class check both.

## Non-contract items (explicitly NOT pinned)

- Exact whitespace / formatting of the Markdown output beyond the section-order + parenthetical-authority rules.
- Ordering of controls within a section (implementation MAY sort by id, by level, by status, or preserve TOML order).
- Timestamp format in the summary section (implementation MAY use ISO 8601 or a human-readable variant).
- Full `evidence` shape within a control entry (that follows the existing `CheckResult.evidence` contract from feature 022).

## Contract-change procedure

Same as feature 024/025: contract update in same PR as code change; matching tests updated; `Contract change:` note in PR description.
