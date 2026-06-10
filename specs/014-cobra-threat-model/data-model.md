# Data Model: Cobra Threat-Model Coverage

**Feature**: 014-cobra-threat-model

## Existing types this feature reuses

### `EntryPointKind.CLI_COMMAND`

Defined at `packages/darnit-baseline/src/darnit_baseline/threat_model/discovery_models.py:76`. Already exists; this feature is the first consumer.

### `DiscoveredEntryPoint`

Defined in the same file. No schema change required. New cobra findings populate:

| Field | Value for cobra |
|---|---|
| `kind` | `EntryPointKind.CLI_COMMAND` |
| `name` | The command's `Use:` string (e.g., `"cache init"`) |
| `location` | File + line of the matched `cobra.Command{...}` literal or `func New() *cobra.Command` |
| `language` | `"go"` |
| `framework` | `"cobra"` (the existing `_ENTRY_POINT_KINDS_REQUIRING_FRAMEWORK` set does **not** include `CLI_COMMAND`, so this field is optional; setting it explicitly lets downstream code distinguish cobra from a future urfave/cli) |
| `route_path` | `None` |
| `http_method` | `None` |
| `has_auth_decorator` | `False` |
| `source_query` | `"go.entry.cobra_command_literal"` or `"go.entry.cobra_new_func"` |

### `DiscoveryResult` (existing)

Carries the list of discovered entry points downstream to grouping + rendering. No new fields required for cobra; the family information is computed downstream rather than persisted on the entry point.

## New conceptual entity (in-memory only, not persisted)

### `CommandFamily`

Produced by `group_by_cli_family()` (new in `grouping.py`) from a flat list of `DiscoveredEntryPoint` with `kind == CLI_COMMAND`. Lives between extraction and rendering; not part of the persisted output structure.

| Field | Type | Source |
|---|---|---|
| `family_key` | `str` | First path component beneath the inferred `command_root` (e.g., `"cache"`). |
| `source_root` | `str` | The per-family directory shown to reviewers in the rendered output. Computed as `command_root + "/" + family_key`. Always a relative path under the repository root. |
| `display_name` | `str` | The parent command's `Use:` text if a parent literal is found in the `source_root` directory; otherwise the `family_key`. |
| `members` | `list[DiscoveredEntryPoint]` | All cobra entry points whose file path falls under `source_root/...`. |
| `import_signatures` | `set[str]` | Union of imports across member files — drives the STRIDE heuristic at rendering time. |
| `stride_categories` | `list[str]` | One or more STRIDE labels derived from `import_signatures` per the table in `research.md`. |
| `needs_reviewer_attention` | `bool` | Always `True` for cobra (heuristic categorisation). |

**Terminology**: `command_root` is project-scoped (one per audit run, the inferred top-level prefix above all cobra files). `source_root` is family-scoped (one per `CommandFamily`, the per-family directory). The rendered Markdown bullet `**Source root**: <path>` shows the family's `source_root` value verbatim.

### Validation rules

- `family_key` MUST NOT contain path separators. If the `command_root` inference yields a single-file project, the `family_key` is the filename's directory or the project root's name as a degenerate-but-valid value.
- `source_root` MUST be a valid relative path beneath the repository root and MUST exist on disk at audit time.
- `members` MUST contain at least one entry point. Empty families are filtered out before rendering.
- `display_name` MUST be human-readable; if the parent literal's `Use:` is multi-line or contains placeholders, the renderer trims to the first word.
- `stride_categories` MUST contain at least one STRIDE label (Tampering fallback per the heuristic table).

### Relationships

- `CommandFamily` ←(many-to-one)— `DiscoveredEntryPoint`: each entry point belongs to exactly one family.
- The set of families is partitioned by `family_key`; no entry point appears in two families.
- Sibling-family ordering in the rendered output: sorted by `len(members)` descending (so the project's largest command tree appears first), with `family_key` as a tiebreaker for deterministic snapshots.

## Discovery flow (state changes)

```text
Go source file
   │
   ▼  if imports github.com/spf13/cobra
ts_discovery._extract_go_cli_commands()
   │  runs go.entry.cobra_command_literal  →  N×DiscoveredEntryPoint(kind=CLI_COMMAND)
   │  runs go.entry.cobra_new_func         →  M×DiscoveredEntryPoint(kind=CLI_COMMAND)
   │  dedup by (file, line) so a New-func wrapping a literal counts once
   ▼
grouping.group_by_cli_family(entry_points)
   │  computes command_root via longest common directory prefix
   │  partitions entries by first subdirectory beneath command_root
   │  collects import_signatures per family
   │  produces list[CommandFamily]
   ▼
ranking.assign_stride_for_cli_families(families)
   │  applies the heuristic table (research.md R3) per family
   │  every family gets needs_reviewer_attention = True
   ▼
ts_generators._render_cli_entry_points(families)
   │  emits the new "## CLI Entry Points" Markdown section
   │  one finding per family with subcommand-location table
   ▼
THREAT_MODEL.md
```

## State transitions

There are no persistent state transitions — the entire flow is one-shot per audit invocation. The output file is the only persisted artifact, and it is replaced (not merged) when the handler runs with `overwrite=true`. Conservative-by-default: existing files are not overwritten unless the user opts in.
