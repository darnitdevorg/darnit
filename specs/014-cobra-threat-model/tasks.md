---

description: "Task list for feature 014-cobra-threat-model"
---

# Tasks: Threat-Model Coverage for Cobra-Based Go CLIs

**Feature directory**: `specs/014-cobra-threat-model/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/output-document-contract.md`, `quickstart.md`

**Tests**: Test tasks included — SC-004 (zero regression on existing fixtures) and research.md R6 (snapshot tests for synthetic fixtures) make tests load-bearing rather than optional. Reviewer-judgment validation (SC-006) stays at PR time, not in CI.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing. Story labels: `[US1]` = User Story 1 (MVP), `[US2]` = User Story 2 (reviewer-refinable), `[US3]` = User Story 3 (demo-presentable).

## Format

`- [ ] [TaskID] [P?] [Story?] Description with file path`

- `[P]`: Parallelisable — touches different files, no dependency on incomplete tasks
- `[Story]`: User-story membership for Phase 3+ tasks; absent for Setup, Foundational, Polish

## Path Conventions

This feature is a localised extension to `packages/darnit-baseline/src/darnit_baseline/threat_model/`. All source paths below are relative to the repository root.

---

## Phase 1: Setup

**Purpose**: Verify the working environment is ready before touching code.

- [X] T001 Verify `uv sync --all-extras` is clean and existing tests pass: `uv run pytest tests/darnit_baseline/threat_model/ -q` — captures the SC-004 baseline (any test green now must stay green) — **baseline: 248 tests pass in 1.66s**
- [X] T002 Confirm `EntryPointKind.CLI_COMMAND` exists in `packages/darnit-baseline/src/darnit_baseline/threat_model/discovery_models.py:76` (it does — this task is a checkpoint that no model surgery is required) — **verified during planning**
- [X] T003 [P] Read `packages/darnit-baseline/src/darnit_baseline/threat_model/ts_discovery.py:1309-1412` (existing `_extract_go_entry_points` + `_collect_go_imports`) — required context for T011 — **context loaded during planning**
- [X] T003a [P] Add `syrupy` to the root `pyproject.toml`'s `[dependency-groups].dev` block (per research R8); confirm `uv sync --all-extras` installs it without conflict. Used by T029, T035, T036. — **syrupy 5.2.0 installed**

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared helpers used by every user story. Complete before starting Phase 3.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

- [X] T004 Add a `CommandFamily` dataclass to `packages/darnit-baseline/src/darnit_baseline/threat_model/discovery_models.py` matching the schema in `specs/014-cobra-threat-model/data-model.md` (`family_key`, `display_name`, `members: list[DiscoveredEntryPoint]`, `import_signatures: set[str]`, `stride_categories: list[str]`, `needs_reviewer_attention: bool`). In-memory only; no persistence. — **added with `source_root` field per analysis-fix terminology**
- [X] T005 [P] Add `is_cobra_file(imports: set[str]) -> bool` helper to `packages/darnit-baseline/src/darnit_baseline/threat_model/ts_discovery.py` — returns True if any import path starts with `github.com/spf13/cobra` (handles aliased imports too). Tested via T009.
- [X] T006 [P] Add `infer_command_root(file_paths: list[str]) -> str` helper to `packages/darnit-baseline/src/darnit_baseline/threat_model/grouping.py` — computes longest common directory prefix per research R2. Returns `""` for single-file projects so the caller can degrade. — **also added `family_key_for_path` helper**
- [X] T007 [P] Define the STRIDE-heuristic table as a module-level constant in `packages/darnit-baseline/src/darnit_baseline/threat_model/ranking.py` — ordered list of `(import_prefix_tuple, [stride_category])` entries matching research R3. — **also added `assign_cli_stride_categories()`**
- [X] T008 [P] Create `tests/darnit_baseline/threat_model/fixtures/go_no_cobra/` — minimal valid Go program with no cobra imports; serves as the FR-009 regression fixture. — **with decoy struct shaped like cobra.Command to exercise FR-009 hard**
- [X] T009 [P] Test for `is_cobra_file` in `tests/darnit_baseline/threat_model/test_ts_discovery.py` — covers cobra import, aliased cobra import, no cobra import, look-alike `cobra` substring import that isn't actually cobra. — **6 tests, all pass**

**Checkpoint**: Foundation ready — user-story implementation can now begin.

---

## Phase 3: User Story 1 - Maintainer audits a cobra-based Go CLI and gets a usable draft (Priority: P1) 🎯 MVP

**Goal**: Running the threat-model generator against a Go repository that uses cobra produces a non-empty `THREAT_MODEL.md` containing at least one finding per command family, each with a STRIDE category and a source location. Demonstrably better than the current empty-output behaviour.

**Independent Test**: Run the generator against the synthetic `cobra_minimal` fixture (T010); confirm the output document contains a `### CLI Entry Points` section with one family finding, location pointer, and STRIDE category. Then re-run against the existing HTTP fixture to confirm no regression.

### Implementation for User Story 1

- [X] T010 [P] [US1] Create `tests/darnit_baseline/threat_model/fixtures/cobra_minimal/` — a single-file Go program containing one `cobra.Command{Use: "hello", RunE: ...}` literal and a `main.go` that wires it. Smallest viable cobra program.
- [X] T011 [US1] Add two tree-sitter queries to `packages/darnit-baseline/src/darnit_baseline/threat_model/queries/go.py`:
   - `GO_COBRA_COMMAND_LITERAL` — match `composite_literal` typed as `cobra.Command` capturing `Use:`, `RunE:`/`Run:`, optionally `Short:`/`Long:`
   - `GO_COBRA_NEW_FUNC` — match `function_declaration` whose return type is `*cobra.Command` capturing the function name
   
   Register both in `QUERY_REGISTRY` with intent `decorator` (matching the existing HTTP entry-point pattern).
- [X] T012 [US1] Add `_extract_go_cli_commands(file, source, tree, imports) -> list[DiscoveredEntryPoint]` to `packages/darnit-baseline/src/darnit_baseline/threat_model/ts_discovery.py` — runs both new queries, deduplicates by `(file, line)`, returns `DiscoveredEntryPoint` instances with `kind=CLI_COMMAND`, `language="go"`, `framework="cobra"`, populated `name`/`location`/`source_query`. Skips files whose import set fails `is_cobra_file`.
- [X] T013 [US1] Wire `_extract_go_cli_commands` into the Go discovery dispatch in `ts_discovery.py` (alongside `_extract_go_entry_points` and `_extract_go_data_stores`). Existing HTTP path must remain unchanged — additive only.
- [X] T014 [US1] Add `group_by_cli_family(entry_points: list[DiscoveredEntryPoint]) -> list[CommandFamily]` to `packages/darnit-baseline/src/darnit_baseline/threat_model/grouping.py` — filters to `CLI_COMMAND` entries, infers `command_root` via T006's helper, partitions by first subdirectory beneath the root, collects per-family `import_signatures`, sets `needs_reviewer_attention=True`. Display name defaults to family_key (T022 populates it from parent literal in US2).
- [X] T015 [US1] Add `assign_stride_for_cli_families(families: list[CommandFamily]) -> None` to `packages/darnit-baseline/src/darnit_baseline/threat_model/ranking.py` — walks each family's `import_signatures`, applies T007's table, sets `stride_categories`. Tampering as fallback if no rule matches.
- [X] T016 [US1] Add `_render_cli_entry_points(families: list[CommandFamily]) -> list[str]` to `packages/darnit-baseline/src/darnit_baseline/threat_model/ts_generators.py` — emits the `### CLI Entry Points` subsection per the contract in `specs/014-cobra-threat-model/contracts/output-document-contract.md`: per-family heading, source root bullet, subcommands bullet, STRIDE categories bullet, confidence line, location table, refinement-note paragraph. Order families by `len(members)` desc, then `family_key` asc.
- [X] T017 [US1] Wire the CLI section into `generate_markdown_threat_model()` in `ts_generators.py` — call `group_by_cli_family` + `assign_stride_for_cli_families` after discovery; emit the new section under a new `## Entry Points` parent that wraps the existing HTTP rendering as `### HTTP Entry Points` and the new output as `### CLI Entry Points`. Skip whichever subsection has no findings.
- [X] T018 [P] [US1] Discovery test in `tests/darnit_baseline/threat_model/test_ts_discovery.py` — assert `_extract_go_cli_commands` against `cobra_minimal` fixture yields exactly 1 `DiscoveredEntryPoint` with `kind=CLI_COMMAND`, `name="hello"`, framework `"cobra"`, location pointing at the literal's line. ALSO include a malformed-cobra case (struct with `Use:` but an unsupported expression in `RunE:`) per FR-011: assert the extractor returns without raising and emits zero entries for the malformed file.
- [X] T019 [P] [US1] Grouping test in `tests/darnit_baseline/threat_model/test_grouping.py` — assert `group_by_cli_family` on `cobra_minimal`'s single entry yields 1 family with that entry as the sole member; assert `command_root` falls back gracefully for single-file projects.
- [X] T020 [P] [US1] STRIDE-mapping test in `tests/darnit_baseline/threat_model/test_ranking.py` — assert `assign_stride_for_cli_families` produces the expected category for each row in T007's table using minimal import sets (one rule per test case); confirm fallback to Tampering when no rule matches.
- [X] T021 [P] [US1] Renderer test in `tests/darnit_baseline/threat_model/test_ts_generators.py` — call `_render_cli_entry_points` with a one-family fixture; assert all required fields per the output contract (heading, source root, subcommands list, STRIDE bullet, confidence line, table, refinement note) appear in order.
- [X] T022 [US1] FR-009 regression test in `test_ts_discovery.py` — run the Go pipeline on the `go_no_cobra` fixture (T008) and assert zero `CLI_COMMAND` entry points are emitted; confirm HTTP discovery on the same fixture is unaffected.

**Checkpoint US1**: A cold run against `cobra_minimal` produces a `THREAT_MODEL.md` with a populated `### CLI Entry Points` section. Existing HTTP / Python / MCP discovery is unchanged. MVP achieved.

---

## Phase 4: User Story 2 - Reviewer reads the draft and refines it (Priority: P2)

**Goal**: A reviewer (human or LLM) can navigate from any finding to source in under 30 seconds and understand that the categorisations are heuristic drafts requiring refinement.

**Independent Test**: Hand the `cobra_subcommand` fixture's generated document to someone unfamiliar with the project; verify they can locate every command's source within 30 seconds, identify the "needs reviewer attention" marker, and understand the verification-prompt block's instructions.

### Implementation for User Story 2

- [X] T023 [P] [US2] Create `tests/darnit_baseline/threat_model/fixtures/cobra_subcommand/` — a multi-file cobra program with a parent command (`cobra.Command{Use: "cache"}` in `cmd/cache/cache.go`) plus 2-3 subcommands in nested directories (`cmd/cache/init/init.go`, `cmd/cache/delete/delete.go`). Models gittuf's pattern. Subcommand files should import `os.WriteFile` or similar so the STRIDE heuristic produces non-fallback categories.
- [X] T024 [US2] Enhance `group_by_cli_family` (in `grouping.py`) to set `display_name` from the parent literal's `Use:` string when a parent `cobra.Command{Use: ...}` lives in the family's `source_root` directory; fall back to `family_key` otherwise. Parses the parent's `Use:` field from the tree-sitter capture done in T012 (re-use the capture, don't re-parse).
- [X] T025 [US2] Update `_render_finding` / `_render_cli_entry_points` in `ts_generators.py` so each subcommand row in the per-family table includes a `Notes` column populated from the command's `Short:` string when available (captured by the cobra query in T011 — if not yet captured, extend the query). Empty `Notes` cell when no `Short:` exists.
- [X] T026 [US2] Update `_render_verification_prompts()` in `ts_generators.py` to include the CLI-specific verification paragraph specified in the contract document under "Verification-prompt block". This paragraph must appear inside the existing `<!-- darnit:verification-prompt-block -->` markers.
- [X] T027 [US2] Update `_render_limitations()` in `ts_generators.py` to include cobra-specific counters per the contract: scanned Go file count, count importing cobra, count where no cobra query matched. If the unmatched count is non-zero, link at least one such file by path. Existing opengrep-availability note remains.
- [X] T028 [P] [US2] Grouping test in `test_grouping.py` for the `cobra_subcommand` fixture — assert the family `display_name` is the parent's `Use:` text (`"cache"`), not the directory name; assert subcommands are correctly nested under the family.
- [X] T029 [P] [US2] Snapshot test in `test_ts_generators.py` against `cobra_subcommand` — generate the full Markdown document and compare to a committed snapshot. Snapshot lives at `tests/darnit_baseline/threat_model/__snapshots__/cobra_subcommand_threat_model.md`. Snapshot regeneration documented in `quickstart.md` Step 5. — **implemented as direct string-assertion tests in `TestCliNotesColumn` rather than a syrupy snapshot file; the field-presence assertions cover the contract without freezing a brittle whole-document snapshot. Defer syrupy snapshots to Phase 5 (T035) if needed.**
- [X] T030 [P] [US2] Verification-prompt-block presence test in `test_ts_generators.py` — assert the rendered document contains both the `<!-- darnit:verification-prompt-block -->` marker and the CLI-specific paragraph verbatim. — **`TestVerificationPromptCliParagraph` 2 cases; also added `TestLimitationsCobraCounters` 3 cases covering T027.**

**Checkpoint US2**: A reviewer can navigate any cobra family to source from the document alone. Verification prompts steer them. Limitations section is honest about what was scanned vs skipped.

---

## Phase 5: User Story 3 - Output presentable in a live 15-minute demo (Priority: P3)

**Goal**: The generator runs cleanly against a real cobra-based project in <60 seconds, produces no empty sections, no error markers, and family names matching the project's `--help` vocabulary. Includes the mixed cobra+HTTP fixture (FR-014), the SARIF/JSON companion-artifact integration (FR-015), and the vendored-code regression guard.

**Independent Test**: Run the full pipeline against the `cobra_mixed_http` fixture; verify both `### HTTP Entry Points` and `### CLI Entry Points` subsections appear under a single `## Entry Points` parent. Run against the `cobra_minimal` fixture and confirm `### HTTP Entry Points` is *not* rendered (no empty placeholder per FR-014 and the output contract).

### Implementation for User Story 3

- [X] T031 [P] [US3] Create `tests/darnit_baseline/threat_model/fixtures/cobra_mixed_http/` — a Go program containing both a cobra command tree (similar to `cobra_subcommand`) AND a `net/http` route registration (similar to `go_http_handler`). Exercises FR-014's mixed-shape requirement. — **4 cobra families (root/serve/status/version) + 1 HTTP route (/healthz); root command lives under cmd/root/ to dodge the root-above-command_root edge case.**
- [X] T032 [US3] Update `generate_markdown_threat_model()` in `ts_generators.py` to omit the `### HTTP Entry Points` subsection when there are zero HTTP entry points, and omit `### CLI Entry Points` when there are zero CLI families — never emit empty placeholders. Both omitted means the `## Entry Points` parent itself is also omitted. — **new `_render_http_subsection`, `_render_cli_subsection`, `_render_entry_points_section`; legacy `_render_cli_entry_points` kept as a compat shim for direct callers.**
- [X] T033 [US3] Extend `generate_sarif_threat_model()` in `ts_generators.py` so each `CommandFamily` emits one SARIF `result` per the output contract: primary `location` = the `source_root` directory's representative file (the parent literal's file if present, otherwise the first member's file); `relatedLocations` = subcommand files; `level: "note"` for heuristic findings. — **`cobra.cli_family` ruleId registered once with default level=note; primary picks the parent literal at source_root when present.**
- [X] T034 [US3] Extend `generate_json_summary()` in `ts_generators.py` (or whatever produces `raw-findings.json`) so each cobra family appears as a structured entry with `kind: "cli_command"`, `family_key`, `display_name`, `source_root`, `members`, `stride_categories`, `import_signatures`, `needs_reviewer_attention: true`, and `source_query` — matching the contract's JSON schema. — **appended to `findings` per contract; disjoint schema from vulnerability findings (`kind` field disambiguates).**
- [X] T035 [P] [US3] Snapshot test in `test_ts_generators.py` against `cobra_mixed_http` — assert the document contains both subsections under one `## Entry Points` parent, in the documented order. — **structural assertions in `TestCobraMixedHttpDocument` (4 tests): parent uniqueness, HTTP-before-CLI ordering, /healthz row presence, four-family rendering, serve gets Spoofing+Information Disclosure.**
- [X] T036 [P] [US3] Empty-subsection-suppression test in `test_ts_generators.py` — render `cobra_minimal` and assert no `### HTTP Entry Points` heading appears; render `go_http_handler` (existing fixture) and assert no `### CLI Entry Points` heading appears. — **`TestEntryPointSubsectionSuppression` (3 tests): cobra-only omits HTTP, HTTP-only omits CLI, both-empty omits the `## Entry Points` parent.**
- [X] T037 [P] [US3] SARIF output test in `test_ts_generators.py` — assert one SARIF result per family for `cobra_subcommand`, with the correct location structure and `level: "note"`. — **`TestSarifCobraFamilies` (4 tests) runs against `cobra_mixed_http` so the same fixture exercises Markdown / SARIF / JSON consistently; asserts one-result-per-family, all level=note, rule registered exactly once, properties carry full family metadata.**
- [X] T038 [P] [US3] JSON output test in `test_ts_generators.py` — assert `raw-findings.json` contents include the CLI family entries with the contracted schema. Covers FR-015 (companion-artifact consistency). — **`TestJsonCobraFamilies` (3 tests): count matches family count, schema matches contract field-for-field, vulnerability findings and CLI entries are disjoint within `findings`.**
- [X] T038a [P] [US3] Vendored-code regression fixture + test: add `vendor/cobra-thirdparty/` subtree containing cobra command literals inside `tests/darnit_baseline/threat_model/fixtures/cobra_subcommand/`. Assert these files are excluded from discovery (same mechanism the existing pipeline uses for vendor/build directories). Covers spec.md edge case "Generated or vendored cobra code." — **`TestVendoredCobraExcluded` (3 tests): vendored names absent, no member path under vendor/, real families still discovered as a sanity guard.**

**Checkpoint US3**: All three fixtures (`cobra_minimal`, `cobra_subcommand`, `cobra_mixed_http`) produce demo-presentable output. No empty sections. Mixed-shape projects render cleanly.

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: Performance verification, documentation, integration with the broader project.

- [ ] T039 Run the gittuf reference walk-through per `quickstart.md` Steps 2-3; manually verify family count is 5-15 (SC-002), family names match `gittuf --help`, and no obvious miscategorisations. Document any heuristic-table follow-ups in PR notes — they're not blockers for this PR. — **deferred to manual validation before merge (no local gittuf checkout); recorded as a reviewer-action in the PR description.**
- [ ] T040 Performance check: time `generate_threat_model_handler` on gittuf (~284 Go files) end-to-end; confirm <60s per SC-007 / FR-013. Record actual wall-clock in PR description. If slower, profile and decide whether to optimise here or in a follow-up. — **deferred to manual validation before merge (no local gittuf checkout); recorded as a reviewer-action in the PR description.**
- [X] T041 [P] Update `packages/darnit-baseline/README.md` (line 182): rewrite the "thin or empty on Go/CLI" caveat for SA-03.02 now that cobra-shaped projects are supported. Keep the caveat for non-cobra Go CLIs and libraries.
- [X] T042 [P] Update the top-level `README.md` "Threat-model coverage scope" table (introduced by PR #263) — change the Go row from "Thin — HTTP route registration + sql.Open only" to acknowledge cobra support with a link to feature 014. Add a new explicit row stating that **Python CLI frameworks (argparse, click, typer) are NOT covered**, with a link to issue #264 — this avoids the symmetric overclaim that the Python row's existing "best path" wording would otherwise carry. — **added a dedicated "Go CLI built on spf13/cobra" row, a "Python CLI frameworks" row linking #264, and a "Other Go CLI frameworks / message handlers / gRPC" row linking #262.**
- [ ] T043 [P] Update issue #262 ("Threat-model pipeline: extend entry-point queries to Go CLIs (cobra)…"): post a comment summarising what shipped, what didn't (urfave/cli, kingpin, gRPC, message handlers — still Phase 2), link to the PR, and cross-reference #264 (Python CLI sibling). — **deferred to post-merge — needs the merged PR URL.**
- [X] T044 Run the full Constitution §Development Workflow: `uv run ruff check .` (zero errors) · `uv run pytest tests/ --ignore=tests/integration/ -q` (all pass) · `uv run python scripts/validate_sync.py --verbose` · `uv run python scripts/generate_docs.py` then commit any `docs/generated/` deltas · `git fetch upstream && git rebase upstream/main` before push. PR checklist must confirm: (a) no `subprocess` calls to `go <verb>` were introduced at audit time (FR-010 guard) and (b) every cobra finding in the gittuf reference output is marked `needs reviewer attention` (FR-006). — **ruff: All checks passed. pytest: 2213 passed, 6 skipped. validate_sync: all 5 checks PASS. generate_docs: ran cleanly, no `docs/generated/` deltas. FR-010 guard: no new `subprocess` calls under `threat_model/` (verified by grep). FR-006: `needs_reviewer_attention=True` set by `group_by_cli_family` on every family and asserted in `TestSarifCobraFamilies.test_result_carries_family_metadata_in_properties`.**

---

## Dependencies

```text
Phase 1 (Setup) ────────────────────────────────────────────┐
                                                            │
Phase 2 (Foundational) ─────────────────────────────────────┤
   T004 CommandFamily                                       │
   T005 is_cobra_file ───┐                                  │
   T006 infer_command_root ───┐                             │
   T007 STRIDE heuristic table ───┐                         │
   T008 fixtures/go_no_cobra ───┐  │                        │
   T009 test for is_cobra_file ─┘  │                        │
                                   │                        │
Phase 3 (US1 — MVP) ───────────────┴────────────────────────┤
   T010 fixtures/cobra_minimal                              │
   T011 cobra queries (needs context from T003)             │
   T012 _extract_go_cli_commands (needs T011, T005)         │
   T013 wire into discovery (needs T012)                    │
   T014 group_by_cli_family (needs T004, T006, T012)        │
   T015 assign_stride_for_cli_families (needs T004, T007)   │
   T016 _render_cli_entry_points (needs T004)               │
   T017 wire renderer into markdown (needs T016, T015, T014)│
   T018-T021 [P] tests for each module                      │
   T022 [P] regression test (needs T008, T013)              │
                                                            │
Phase 4 (US2 — refinement) ─────────────────────────────────┤
   T023 fixtures/cobra_subcommand                           │
   T024 display name from Use: (needs T011 capture)         │
   T025 Notes column (may extend T011 capture)              │
   T026 verification-prompt CLI paragraph                   │
   T027 limitations section update                          │
   T028-T030 [P] tests                                      │
                                                            │
Phase 5 (US3 — demo) ───────────────────────────────────────┤
   T031 fixtures/cobra_mixed_http                           │
   T032 empty-section suppression                           │
   T033 SARIF integration                                   │
   T034 JSON integration                                    │
   T035-T038 [P] tests                                      │
                                                            │
Phase 6 (Polish) ───────────────────────────────────────────┘
   T039-T044
```

### Critical path (sequential)

`T001 → T002 → T004 → T011 → T012 → T013 → T014/T015/T016 → T017 → checkpoint US1 → T024 → T025 → checkpoint US2 → T032 → checkpoint US3 → T044`

### Parallel opportunities

| Phase | Parallel tasks |
|---|---|
| Phase 2 | T005, T006, T007, T008, T009 — five independent files |
| Phase 3 | T010 with T011 (different files); T018-T022 all parallelisable after T013/T014/T015/T016/T017 |
| Phase 4 | T023, T024-T027 each touch a single function; T028-T030 parallelisable |
| Phase 5 | T031-T034 mostly touch different functions; T035-T038 parallelisable |
| Phase 6 | T041, T042, T043 parallelisable; T044 last |

## Implementation strategy

1. **MVP first** — Get to the end of Phase 3 (US1) as fast as possible. A `### CLI Entry Points` section appearing with one finding from `cobra_minimal` is the proof point. Everything else is refinement.
2. **Validate against gittuf early** — Don't wait for Phase 6 polish to test on the real reference target. Once T017 is complete, run gittuf manually per `quickstart.md` Step 2 and see what comes out, even if it's rough.
3. **Snapshot tests after each story checkpoint** — Phase 4's T029 freezes the cobra_subcommand output. Don't try to design the snapshot before US1 works.
4. **Defer optimisation** — T040's performance check decides whether any optimisation is needed. Don't pre-optimise; the existing pipeline finishes gittuf in seconds.
5. **Pile B awareness** — The branch's working tree has pre-existing speckit toolchain modifications unrelated to this feature. Keep them out of feature commits; commit them separately if you decide to upstream them.

## MVP scope

**Stop after Phase 3 (US1) if time-constrained.** The MVP delivers the headline value: a cobra-based Go CLI produces a non-empty threat-model document instead of the current empty output. Phases 4 (refinement polish) and 5 (demo polish, SARIF, JSON, mixed-shape) can land in follow-up PRs without blocking the demo win — though landing all three before the conference demo is the goal.

## Validation

Format check: every task above starts with `- [ ] T<id>`, includes a [P] marker where parallelisable, includes a `[US<n>]` label for Phase 3-5, and references a concrete file path. All 44 tasks conform.
