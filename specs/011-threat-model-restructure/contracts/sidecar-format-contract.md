# Sidecar Format Contract: Mitigation Decisions

**Date**: 2026-04-13 | **Spec**: [../spec.md](../spec.md)

## File Location

`.project/threatmodel/mitigations.yaml` — committed to version control.

## Schema

```yaml
# .project/threatmodel/mitigations.yaml
#
# Mitigation decisions for threat model findings.
# This file is hand-edited by reviewers and read by the threat model generator.
# The generator NEVER creates or deletes entries — only sets the `stale` flag.
#
# Fingerprints include the file path. Renaming a file will make its entries stale.
# Re-record decisions against the new path after a deliberate rename.

version: "1"

entries:
  - fingerprint: "sha256:a1b2c3d4e5f6g7h8"
    status: mitigated              # mitigated | accepted | false_positive | unmitigated
    note: "Input is validated upstream at api/validators.py:42"
    reviewer: "@alice"
    reviewed_at: "2026-04-10"
    # Below fields are informational (for human readability). Not used for matching.
    query_id: "python.sink.dangerous_attr"
    file_hint: "packages/darnit/src/darnit/sieve/builtin_handlers.py"
    stale: false                   # Set to true by generator when fingerprint no longer matches
```

## Field Definitions

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `version` | yes | string | Schema version. Always `"1"` for this contract. |
| `entries` | yes | list | Array of mitigation decision entries. May be empty. |
| `entries[].fingerprint` | yes | string | `sha256:<16 hex chars>`. Stable hash of (query_id, repo-relative file path, whitespace-normalized snippet). |
| `entries[].status` | yes | string | One of: `mitigated`, `accepted`, `false_positive`, `unmitigated`. |
| `entries[].note` | no | string | Free-form explanation. Empty string if omitted. |
| `entries[].reviewer` | no | string | Who made the decision (e.g. `@alice`). Empty if omitted. |
| `entries[].reviewed_at` | no | string | ISO 8601 date (e.g. `2026-04-13`). Empty if omitted. |
| `entries[].query_id` | no | string | Rule identifier for human context. Not used for matching. |
| `entries[].file_hint` | no | string | Last-known file path for human context. Not used for matching. |
| `entries[].stale` | no | bool | `true` if fingerprint no longer matches any current finding. Default `false`. |

## Behaviors

### On load (start of regen)

1. Read `.project/threatmodel/mitigations.yaml`.
2. If file does not exist → no sidecar; all findings treated as unmitigated. Not an error.
3. If file exists but is malformed (unparseable YAML, missing `version`, invalid `status` value) → **fail with a clear error** (FR-018). Do not silently ignore.
4. If file exists and is valid → parse all entries into `MitigationSidecar`.

### On match (during regen)

1. Compute `fingerprint` for every `CandidateFinding` in the scan.
2. Build a lookup: `dict[fingerprint, MitigationEntry]`.
3. For each finding: if its fingerprint is in the lookup, the entry's `status` is applied to the finding's rendered output.
4. Matching is exact (full 16-char hex comparison). No fuzzy or partial matching.

### On stale detection (end of regen)

1. Compute the set of all fingerprints from the current scan.
2. For each sidecar entry: if `fingerprint` is NOT in the current set, set `stale = true`.
3. For each sidecar entry: if `fingerprint` IS in the current set and `stale` was previously `true`, set `stale = false` (finding reappeared).
4. If any `stale` flag changed → write the updated sidecar file back to disk.
5. Never delete entries. Never create entries. Only mutation is the `stale` flag.

### On write (end of regen, only if stale flags changed)

1. Serialize `MitigationSidecar` back to YAML.
2. Preserve the header comment block (lines starting with `#` before `version:`).
3. Write atomically (write to temp file + rename, or overwrite in place — implementation choice).
4. Preserve entry ordering: entries are written in the same order as they were loaded, with no resorting. This ensures `git diff` shows only meaningful changes.

## Validation Rules

- `version` must be `"1"`. Future versions may change the schema; the loader should reject unknown versions with a clear error.
- `fingerprint` must match the pattern `sha256:[0-9a-f]{16}`.
- `status` must be one of the four allowed values (case-sensitive).
- Duplicate fingerprints within a single file are an error (fail loudly, not silently deduplicate).
- `reviewed_at`, if present and non-empty, should be a valid ISO 8601 date. Invalid dates produce a warning, not an error (human-edited field; strict parsing would be fragile).
