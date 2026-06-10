# Phase 0 Research: Cobra Threat-Model Coverage

**Feature**: 014-cobra-threat-model · **Branch**: `014-cobra-threat-model` · **Date**: 2026-05-18

This document resolves the technical unknowns that the spec's behavior-level requirements do not pin down. Each entry follows the **Decision / Rationale / Alternatives considered** structure.

## R1. Tree-sitter AST patterns for cobra commands

### Decision

Two queries plug into `ts_discovery._extract_go_cli_commands`:

1. **`go.entry.cobra_command_literal`** — match `composite_literal` whose type is `cobra.Command` (or `Command` when the file imports cobra with an alias). Capture the `Use:`, `Short:`, `Long:`, and `RunE:`/`Run:` field assignments where present.
2. **`go.entry.cobra_new_func`** — match `function_declaration` whose return type is `*cobra.Command` (or aliased equivalent). Capture the function name. Used as a coarse fallback to pick up commands defined inside a New-style factory where the literal is one level deep.

The cobra extractor runs only on files whose import set (collected by the existing `_collect_go_imports`) contains `github.com/spf13/cobra`.

### Rationale

- The two-query approach mirrors what `queries/python.py` already does (one query per shape, one extractor that combines results) — it's the established pattern in this module.
- Gittuf uses **both** shapes: top-level `func New() *cobra.Command` constructors plus inline `&cobra.Command{...}` literals returned from them. Either alone misses commands; both together cover gittuf's 42 constructors.
- Filtering by import set keeps false positives away from non-cobra Go projects (FR-009). A struct literal called `Command` in some unrelated package would be ignored.

### Alternatives considered

- **Single broad query** (any composite_literal with `Use:` and `RunE:` fields, no type filter). Rejected because it would match any struct in the Go ecosystem that happens to use those field names — over-broad.
- **AST traversal of `AddCommand` calls to build the parent-child tree statically**. Rejected at this stage because (a) Q1 chose filesystem layout for grouping, so the parent-child tree isn't needed for grouping, and (b) tracing `AddCommand` reliably requires resolving identifiers across files, which is more involved than tree-sitter's local-pattern matching is designed for.
- **Run `go doc` or `go list -f` to enumerate commands**. Rejected — FR-010 forbids invoking Go tooling at audit time.

## R2. `command_root` inference (where does the project's command tree live?)

### Decision

The "command root" is computed at extraction time from the set of files that produced cobra findings:

1. Collect the directory of every file that matched a cobra query.
2. Compute their longest common directory prefix.
3. The "family key" for each finding is the first path component beneath that prefix.

For gittuf this collapses to `internal/cmd/` as the `command_root` and gives families like `cache`, `attest`, `rsl`, `verify`. For cosign it collapses to `cmd/cosign/cli/` and gives equivalent families. If only one cobra file exists, the `command_root` is its containing directory and the single command becomes its own family. The plan's `cmd/` and `internal/cmd/` example values are emergent — outputs of this algorithm running against real projects — not hard-coded inputs.

### Rationale

- Deterministic, fully local (no global config), and matches gittuf and cosign's actual layouts without hard-coding either.
- Q1's clarification said filesystem layout is the grouping key with the parent command's `Use:` text as the display name. This algorithm implements both halves: the layout determines membership; the `Use:` text (where the parent's `cobra.Command{Use: ...}` literal can be located in the family-key directory) determines the display name.

### Alternatives considered

- **Hard-code `internal/cmd/` and `cmd/` as known roots**. Rejected — works for two projects, breaks on the third. Common-prefix inference works for any layout the project chose.
- **Use the file's immediate parent directory as the family**. Rejected — gittuf's `cache/init/init.go` is in `init/`, not `cache/`, so this would mis-group siblings under their leaf directory.
- **AST traversal of AddCommand to derive a true parent-child tree** (revisited from R1). Rejected here for the same reasons — and because Q1 explicitly chose filesystem as the basis.

## R3. STRIDE heuristic table

### Decision

For each cobra-command finding, run the file's import set through this ordered table; the first matching rule wins. Multi-category outcomes (e.g., HTTP) emit both categories.

| File imports any of … | STRIDE category |
|---|---|
| `os.Write*`, `os.Create*`, `path/filepath.Walk*`, `io.Copy` against `os.File` writers | **Tampering** |
| `crypto/*`, `github.com/sigstore/*`, `github.com/in-toto/*`, `gittuf/*` signature/policy paths | **Repudiation** |
| `net/http`, `golang.org/x/net/http2`, `google.golang.org/grpc` (client or server) | **Spoofing**, **Information Disclosure** |
| `os/exec`, `syscall` process-spawning, `golang.org/x/sys/unix.Setuid` | **Elevation of Privilege** |
| **(no match)** | **Tampering** *(fallback)* |

Every cobra finding is rendered with a "needs reviewer attention" marker regardless of which rule fired — the heuristic is plausibility-seeking, not authoritative.

### Rationale

- Q2 explicitly chose the import-based heuristic with Tampering as the fallback. The table here turns that into an ordered set of rules covering the most common cases an opaque cobra command might land in.
- Repudiation for crypto / sig-ops matches gittuf's domain (it's a policy / attestation tool); for cosign and slsa-verifier, the same rule applies.
- The HTTP rule emits two categories deliberately — the same call site is both a Spoofing surface (forged client identity) and an Information Disclosure surface (leaked data in responses). Splitting them would lose one threat.
- All findings are draft-marked. Per Constitution principle IV, the system surfaces uncertainty.

### Alternatives considered

- **A single default category for everything opaque (Tampering)**. Rejected during Q2 — produces templated-looking output that fails SC-006's "plausible" bar for files that obviously do something different (e.g., crypto operations defaulted to Tampering reads as careless).
- **All six STRIDE categories with confidence scores**. Rejected during Q2 — too noisy for a draft a reviewer should be able to scan in 10 minutes.
- **Defer STRIDE assignment entirely, emit "category needs reviewer attention" with no letter**. Rejected during Q2 — violates SC-005's "every finding fully populated" requirement.

## R4. Cobra-detection trigger

### Decision

A Go source file enters the cobra extractor only if its import set contains `github.com/spf13/cobra` (or any alias of that import). Files that don't import cobra are skipped without query evaluation.

### Rationale

- Cheapest reliable signal that the file participates in a cobra command tree.
- Eliminates the false-positive risk of look-alike struct literals in unrelated packages.
- Symmetric with how the existing HTTP discovery filters by routing imports (`net/http`, chi, gorilla).
- Imports are already collected by `_collect_go_imports`; no new pass over the AST.

### Alternatives considered

- **Always run the query, post-filter by import**. Equivalent semantics but burns query work on every Go file regardless. Marginally slower; not chosen.
- **Require at least N command literals before treating the project as cobra-based**. Rejected — even single-command projects deserve a non-empty draft (SC-001).

## R5. Output document layout (CLI Entry Points section)

### Decision

The Markdown rendering layer adds a new top-level section, **"CLI Entry Points"**, that mirrors the existing **"HTTP Entry Points"** section in structure. Both sections coexist as siblings under a common "Entry Points" parent in the document if both contain findings; the existing executive-summary table at the top of the document tallies each shape separately.

Section structure for CLI:

```markdown
## CLI Entry Points

### Family: cache

**Source root**: `internal/cmd/cache/`
**Subcommands**: 4 (init, delete, populate, prune)
**STRIDE categories**: Tampering, Elevation of Privilege
**Confidence**: heuristic — needs reviewer attention

| Subcommand | Location | Notes |
|---|---|---|
| cache (parent) | `internal/cmd/cache/cache.go:13` | Dispatch only |
| cache init | `internal/cmd/cache/init/init.go:26` | Reads filesystem, creates state |
| cache delete | `internal/cmd/cache/delete/delete.go:23` | Deletes cached state |
| … | | |

Refinement notes: This family was categorised by import-based heuristic; categories may need recategorisation per the project's threat model.
```

If a project has *only* cobra entry points (no HTTP), the HTTP section is omitted entirely (no empty placeholder per FR-014).

### Rationale

- Q3 chose separate top-level sections. This is the materialised form of that choice.
- Mirrors the existing HTTP layout pattern, so a reviewer familiar with the current output can scan the new section without learning a new format.
- Family-level summary plus a table of subcommands keeps the output readable for ~10–15 families without forcing per-command STRIDE assignments (which would over-categorise).

### Alternatives considered

- **Per-subcommand findings** (each leaf command gets its own STRIDE-categorised entry). Rejected — would produce 42 findings for gittuf, well over SC-002's 15-finding upper target, and most subcommands inherit the parent's threat profile anyway.
- **Family-only findings with subcommands hidden** (just "cache: Tampering"). Rejected — reviewers need the per-subcommand locations to navigate the source, per User Story 2.

## R6. SC-006 validation in CI

### Decision

CI verifies SC-006's "70% plausible" indirectly via two layers:

1. **Snapshot tests** on synthetic fixtures (`fixtures/cobra_minimal/`, `fixtures/cobra_subcommand/`, `fixtures/cobra_mixed_http/`) where the expected STRIDE mapping is deterministic. Any change to the heuristic that breaks a snapshot must be acknowledged with a snapshot regeneration in the same PR.
2. **PR-time human review** against the gittuf reference output for any change that touches the heuristic table. A "Reviewer plausibility check" line is added to the PR template for this feature area.

No LLM-judge step in CI — LLM output is non-deterministic and would make the test suite flaky.

### Rationale

- Snapshot tests give a fast, deterministic regression guard for the heuristic.
- The "plausibility" judgment is intrinsically reviewer work — automating it would replace one form of human-in-the-loop with another more brittle one.
- This matches the user's framing: "humans refine."

### Alternatives considered

- **LLM-judge in CI**. Rejected for flakiness.
- **No CI gate at all**. Rejected — snapshot tests catch silent heuristic regressions cheaply.
- **A rule-of-thumb checklist in CI** (e.g., "every Repudiation finding's file imports crypto/something"). Considered worth doing in a follow-up if the snapshot suite gets unwieldy; not in scope for this feature.

## R7. Observability of skipped patterns

### Decision

When the cobra extractor encounters a pattern it doesn't recognise (e.g., a builder-style construction, a factory function returning a `cobra.Command` through indirection), the skip is recorded in the existing `DiscoveryResult.skipped_patterns` list (or equivalent — name confirmed in implementation). The Limitations section of the rendered document enumerates these skip categories with a short note ("3 files use unrecognised cobra construction patterns — see `<path>` for examples").

Runtime debug logging is **not** added in this feature. If a user reports a project where many patterns are skipped, instrumenting at that point is straightforward; building it speculatively is not.

### Rationale

- Reviewer-facing visibility (Limitations section) is in scope per FR-007 and satisfies the spec's transparency requirement.
- Avoids YAGNI on debug-logging plumbing that may never be needed in production.

### Alternatives considered

- **Always emit a structured log record per skipped pattern**. Considered useful for debugging but premature. Defer.
- **Suppress skipped patterns entirely**. Rejected — the spec explicitly requires the Limitations section to list them.

## R8. Snapshot library choice

### Decision

Use **`syrupy`** (pytest plugin) for the snapshot tests on synthetic fixtures (T029, T035, T036). Snapshot files live under `tests/darnit_baseline/threat_model/__snapshots__/` (syrupy's default location, configurable). Added as a `[dependency-groups].dev` entry in the root `pyproject.toml`.

### Rationale

- Industry-standard for Python pytest snapshot testing — well-maintained, integrates cleanly with the existing `uv run pytest` flow.
- Native diff display (unified-diff format) makes "what changed" obvious during a heuristic-table edit, which is the workflow we expect to use it for.
- Dev-only dependency; no impact on published wheels.
- The alternative — an in-repo manual diff helper — is doable in ~30 lines but reinvents what syrupy already does, and inferior diff output makes reviewer triage harder.

### Alternatives considered

- **`pytest-snapshot`**. Mature but less actively maintained than syrupy; assertion API is less ergonomic.
- **In-repo manual diff helper** (`Path.read_text() == ...` with a `--snapshot-update` env-var). Zero new deps; loses diff display quality. Acceptable if dev-dep growth becomes a concern, but not the default choice.
- **No snapshot tests; only structural assertions on rendered output** (e.g., "contains `### CLI Entry Points`"). Rejected — wouldn't catch heuristic regressions where category assignments drift silently.

### Implementation note

A new Phase 1 task (T002a or similar) adds `syrupy` to dev deps. Test tasks T029, T035, T036 use the syrupy `snapshot` fixture. Snapshot regeneration: `uv run pytest <path> --snapshot-update`.
