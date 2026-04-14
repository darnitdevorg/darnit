# Data Model: Threat Model Output Restructure

**Date**: 2026-04-13 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## New Types

### FindingGroup (frozen dataclass)

Represents a distinct vulnerability class identified by a tree-sitter query ID.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query_id` | `str` | (required) | Tree-sitter query ID, e.g. `python.sink.dangerous_attr` |
| `slug` | `str` | (required) | Filesystem-safe slug: `query_id.replace(".", "-")` |
| `stride_category` | `StrideCategory` | (required) | STRIDE classification from findings |
| `class_name` | `str` | (required) | Human-readable title (from highest-severity finding's `title`) |
| `mitigation_hint` | `str` | `""` | Aggregate mitigation narrative (from query registry's `mitigation_hint`) |
| `findings` | `tuple[CandidateFinding, ...]` | (required) | All instances in this group, sorted by severity×confidence desc |
| `max_severity_score` | `float` | (required) | `max(f.severity * f.confidence for f in findings)` |

**Identity**: Unique by `query_id`.
**Ordering**: Groups are sorted by `max_severity_score` descending for display in summary.
**Validation**: `__post_init__` asserts `len(findings) > 0`, all findings share same `query_id`, slug matches derivation rule.

### MitigationStatus (str Enum)

| Value | Meaning |
|-------|---------|
| `mitigated` | Finding is addressed by an existing control |
| `accepted` | Risk is accepted per a documented decision |
| `false_positive` | Finding is not a real vulnerability |
| `unmitigated` | Explicitly marked as known but not yet addressed |

### MitigationEntry (frozen dataclass)

One reviewer decision about a specific finding instance.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `fingerprint` | `str` | (required) | `"sha256:<16 hex chars>"` |
| `status` | `MitigationStatus` | (required) | Reviewer's classification |
| `note` | `str` | `""` | Free-form explanation |
| `reviewer` | `str` | `""` | Reviewer identifier (e.g. `@alice`) |
| `reviewed_at` | `str` | `""` | ISO 8601 date (e.g. `2026-04-13`) |
| `query_id` | `str` | `""` | For human readability in YAML; not used for matching |
| `file_hint` | `str` | `""` | Last-known file path; not used for matching |
| `stale` | `bool` | `False` | Set by regen when fingerprint no longer matches any finding |

**Identity**: Unique by `fingerprint` within a sidecar.
**Matching**: On regen, each `CandidateFinding` is fingerprinted; the sidecar is searched for a matching `fingerprint`. Match → apply status. No match → finding is unmitigated.
**Staleness**: Sidecar entries whose `fingerprint` is not in the current scan's fingerprint set have `stale` set to `True` and are persisted. Never auto-deleted.

### MitigationSidecar (dataclass, mutable)

Container for all mitigation decisions in a project.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `entries` | `list[MitigationEntry]` | `[]` | All recorded decisions |

**Persistence**: Serialized to `.project/threatmodel/mitigations.yaml`. Loaded at regen start, written back if any `stale` flags changed.

## Modified Types

### CandidateFinding (existing, frozen dataclass in discovery_models.py)

**Added field**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `fingerprint` | `str` | `""` | Computed lazily after discovery; `""` means not yet computed |

The fingerprint is populated by `sidecar.compute_fingerprint()` during the grouping/sidecar-matching phase, not during discovery. It is not set in `__init__` because it depends on the repo root path (for computing relative paths), which is not available at finding construction time.

### PythonQuery / JsQuery / GoQuery / YamlQuery (existing, frozen dataclasses in queries/)

**Added field to all four**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mitigation_hint` | `str` | `""` | One-sentence guidance for this query's vulnerability class. Becomes the group-level mitigation narrative in per-class detail files. Empty means "no guidance available." |

Appended as last field with default — backward-compatible with existing positional construction.

## Existing Types (unchanged)

These types participate in the pipeline but are not modified:

- **`DiscoveryResult`** — input to grouping; its `.findings` list is the raw ungrouped set
- **`TrimmedOverflow`** — repurposed: now represents "classes below SUMMARY display threshold" rather than "dropped findings." Fields unchanged; semantic shift only.
- **`Location`**, **`CodeSnippet`**, **`DataFlowTrace`** — unchanged, carried through to renderers
- **`StrideCategory`** — unchanged, used for STRIDE labels in group headers

## Relationships

```
DiscoveryResult
  └── .findings: list[CandidateFinding]
        │
        ▼  group_by_query_id()
  list[FindingGroup]
        │   each group has .findings: tuple[CandidateFinding, ...]
        │
        ▼  compute_fingerprints() + load_sidecar() + match_findings()
  dict[str, MitigationEntry]   (fingerprint → entry)
        │
        ▼  render
  ┌─────────────────────────────────┐
  │ SUMMARY.md                      │  Uses: list[FindingGroup], sidecar matches, overflow hint
  │ findings/<slug>.md (per group)  │  Uses: FindingGroup, sidecar matches
  │ data-flow.md                    │  Uses: DiscoveryResult (entry points, data stores, call graph)
  │ raw-findings.json               │  Uses: all CandidateFindings + sidecar matches
  └─────────────────────────────────┘
```

## State Transitions

### MitigationEntry lifecycle

```
                     [human creates entry]
                            │
                            ▼
              ┌──────── Active ────────┐
              │  stale=False           │
              │  status=<any>          │
              └────────────────────────┘
                     │            │
          [fingerprint     [fingerprint
           still matches]   no longer matches]
                     │            │
                     ▼            ▼
              ┌──────── Active   ┌──── Stale ────┐
              │  (unchanged)     │  stale=True    │
              └──────────────    │  status=<same> │
                                 └────────────────┘
                                        │
                           [fingerprint reappears
                            in future scan]
                                        │
                                        ▼
                                 ┌──── Active ────┐
                                 │  stale=False    │
                                 │  status=<same>  │
                                 └─────────────────┘

  Note: Only transitions caused by regen. Human can edit any field
  at any time (including deleting an entry entirely).
```

### Finding rendering status (derived, not persisted)

```
  CandidateFinding
       │
       ├─ fingerprint matches sidecar entry
       │    ├─ status in {mitigated, accepted, false_positive}
       │    │    → "Mitigated" in output; excluded from Unmitigated section
       │    └─ status == unmitigated
       │         → "Unmitigated" in output; included in Unmitigated section
       │
       └─ no sidecar match
            → "Unmitigated" in output; included in Unmitigated section
```
