# Contract: Rendered Threat-Model Document — CLI Entry Points

**Feature**: 014-cobra-threat-model

This contract defines the user-facing shape of the Markdown threat-model document for projects that contain cobra-based Go CLI commands. It is the consumable artifact downstream tools (LLM reviewers, human reviewers, snapshot tests) depend on.

## Document-level structure

The rendered `THREAT_MODEL.md` (and the JSON / SARIF companions) MUST contain these top-level sections in order:

1. `# Threat Model Report`
2. `## Executive Summary` — tally of findings by category (existing; CLI entries counted here)
3. `## Top Risks` — existing
4. `## Unmitigated Findings` — existing
5. `## Entry Points`
   - `### HTTP Entry Points` — rendered only if HTTP findings exist
   - `### CLI Entry Points` — rendered only if cobra findings exist
   - **At least one** subsection MUST be present if any entry points were discovered. Both MAY be present (mixed projects). Neither MUST appear if no entry points were discovered.
6. `## Companion Artefacts` — existing (links to data-flow.md, raw-findings.json)
7. `## Recommendations Summary` — existing
8. `## Verification Prompts` — existing
9. `## Limitations` — existing

When a project contains **only** cobra commands (no HTTP), the `### HTTP Entry Points` subsection MUST be omitted entirely (no empty placeholder, no "no findings" stub).

## `### CLI Entry Points` section schema

Per-family. Each family appears as a level-4 heading and a structured block.

### Required fields per family

- **Heading**: `#### Family: <display_name>`
- **Bullet line** `**Source root**: \`<path>\`` — value of the family's `source_root` field; relative to the repository root.
- **Bullet line** `**Subcommands**: N (cmd1, cmd2, ...)` — comma-separated names from the family's `members`, ordered as encountered in the filesystem walk.
- **Bullet line** `**STRIDE categories**: <Category1>[, <Category2>, …]` — one or more STRIDE labels from R3 of `research.md`.
- **Bullet line** `**Confidence**: heuristic — needs reviewer attention` — literal, exact wording. Required for snapshot tests.
- **Table** — header row `| Subcommand | Location | Notes |`. Each row maps to one `DiscoveredEntryPoint` in the family's `members`. The `Notes` column may be empty for findings where the source provides no `Short:` description.
- **Refinement note** (final paragraph) — literal sentence: `_Refinement notes: This family was categorised by import-based heuristic; categories may need recategorisation per the project's threat model._`

### Ordering

Families MUST be ordered by `len(members)` descending, with `family_key` ascending as the tiebreaker. This makes the document deterministic for snapshot testing while keeping the largest command surfaces visible first.

### Empty / degenerate cases

- A project with **zero** cobra commands MUST NOT emit a `### CLI Entry Points` subsection.
- A project with **one** cobra command MUST emit a single family containing that command. The family's `display_name` defaults to the file's containing directory name if no parent literal is found.
- A project where the cobra extractor's queries all match but every match's import set fails *all* heuristic rules MUST still render every family with the fallback Tampering category — never an empty `STRIDE categories:` line.

## Companion artefact deltas

### `raw-findings.json`

Add an entry per cobra family in the existing `findings` array, with the schema (subset):

```json
{
  "kind": "cli_command",
  "family_key": "cache",
  "display_name": "cache",
  "source_root": "internal/cmd/cache/",
  "members": [
    { "name": "cache", "location": { "file": "internal/cmd/cache/cache.go", "line": 13 } },
    { "name": "cache init", "location": { "file": "internal/cmd/cache/init/init.go", "line": 26 } }
  ],
  "stride_categories": ["Tampering", "Elevation of Privilege"],
  "import_signatures": ["os.WriteFile", "os.MkdirAll"],
  "needs_reviewer_attention": true,
  "source_query": "go.entry.cobra_command_literal"
}
```

### `data-flow.md`

Unchanged. CLI commands are not data-flow nodes (no data store, no network sink); they remain absent from the DFD. A reviewer reading the DFD will not see them — that is expected.

### SARIF output

Each cobra family emits one SARIF `result` (not one per subcommand). The `result.locations` array carries the family's `source_root` representative file (parent literal's file if present, otherwise first member's file) as the primary location; the `result.relatedLocations` array carries the subcommand-file locations. SARIF level mirrors confidence: heuristic findings get `level: "note"` (not `warning` or `error`), so they don't trip strict-mode SARIF consumers.

## Verification-prompt block

The existing `<!-- darnit:verification-prompt-block -->` marker MUST remain in the document. The block's content is extended with one new paragraph specific to CLI findings:

```markdown
For the CLI Entry Points section: this section was produced by an
import-based heuristic, not a STRIDE analysis. Open each family's
representative file. For each STRIDE category listed: does the
file's actual behaviour match? If not, replace the category and
remove this paragraph's note. If the family was over- or
under-grouped (subcommands missing, or unrelated commands lumped
together), restructure the table and edit the `family_key`
identifier in `raw-findings.json` to match.
```

The block is a literal contract — snapshot tests assert its presence verbatim.

## Limitations section schema

The Limitations section MUST list, when present:

- Total scanned Go files and how many imported cobra.
- Number of cobra-importing files where **no** query matched (i.e., files using an unrecognised pattern). If non-zero, the section MUST link to at least one such file by path.
- Whether opengrep / semgrep taint analysis was available (existing behaviour, applied to cobra findings the same way it applies to HTTP findings).

## Non-goals (explicitly out of contract)

- Recommending fixes for individual CLI findings. The output is descriptive; recommendations stay in the existing recommendations section, which remains generic.
- Per-subcommand STRIDE categorisation. The family is the unit of categorisation.
- Cross-cutting findings (e.g., "all `cache *` subcommands write to disk → one Tampering finding spanning the family"). The family-level finding already captures this; no further consolidation.
