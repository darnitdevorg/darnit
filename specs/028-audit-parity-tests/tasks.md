---
description: "Tasks for feature 028: Two-Tier Audit Parity Tests -- MCP tool / harness / coding-agent skill diagnosis"
---

# Tasks: Two-Tier Audit Parity Tests

**Input**: Design documents from `specs/028-audit-parity-tests/`

**Prerequisites**: plan.md (loaded), spec.md (loaded, 5 clarifications), research.md (loaded, 10 decisions), data-model.md (loaded), contracts/{tier1-parity-invariant,tier2-workflow,parity-toml-schema}.md (loaded), quickstart.md (loaded).

**Tests**: Test tasks included. This entire feature IS a test suite; every FR maps to a concrete pytest module or a workflow-config assertion. Load-bearing SCs: SC-001/003 (adversarial-drift detection), SC-002 (Tier 1 <60s), SC-004 (Tier 2 catches skill reclassification), SC-005a (no ANTHROPIC_API_KEY exposure outside gated workflow), SC-006 (zero product deps added), SC-008 (four fixture categories).

**Organization**: Tasks grouped by user story per spec.md. Feature 026 (harness) is a hard dependency. Feature 027 (interactive resolvers) is NOT a dependency; parity tests do not exercise interactive answer collection.

**Branch base**: `026-harness-with-stage1` (PR #365, still open). Rebase to `main` once #365 lands. Do NOT branch from `main` directly -- feature 028 depends on 026's `HarnessRun` and `MockLLMStep`.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Parallelizable with other [P] tasks in the same phase
- **[Story]**: Which user story (US1, US2, US3)
- File paths are exact and repository-relative
- Closes #366 on merge

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the parity-test tree. No product-package changes. The Claude Agent SDK dep goes into a test-only dev group (SC-006).

- [X] T001 Create `tests/darnit/parity/` directory with an empty `__init__.py`. Add `tests/darnit/parity/tier1/__init__.py` and `tests/darnit/parity/tier2/__init__.py`. Add `tests/darnit/parity/fixtures/` (empty container; fixtures added per-user-story).

- [X] T002 [P] Add `claude-agent-sdk` to the workspace-level dev-group `pyproject.toml` at repo root (or the appropriate `uv`-workspace dev-group location; see `packages/darnit/pyproject.toml` for the pattern). MUST NOT modify `packages/darnit/pyproject.toml` or `packages/darnit-baseline/pyproject.toml` -- SC-006 requires zero product dep changes. Include a comment identifying it as a Tier 2 test-only dep.

- [X] T003 [P] Add a top-level `.gitignore` entry for `parity-artifacts/` if not already ignored, so Tier 2's local runs don't accidentally commit skill-invocation transcripts.

**Checkpoint**: Directory scaffolding exists; `uv sync --dev` installs `claude-agent-sdk` for maintainers; product packages are untouched.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared data types + comparator logic + `parity.toml` parser that BOTH Tier 1 and Tier 2 depend on. Each task creates a self-contained module with its own tests.

**CRITICAL**: No user-story tasks can proceed until this phase is complete.

- [X] T004 Create `tests/darnit/parity/tier1/comparator.py` per data-model.md sections 3-5:
    - `Control` (frozen dataclass: `id`, `status` Literal, `authority` Literal | None, `level` int | None)
    - `AuditResult` (frozen dataclass with `controls: tuple[Control, ...]`, `source: Literal["mcp_tool", "harness"]`)
    - `AuditResult.from_mcp_json(payload: dict) -> AuditResult` classmethod parsing the shape returned by `audit_openssf_baseline(output_format="json")`
    - `AuditResult.from_harness_report(report: HarnessReport) -> AuditResult` classmethod
    - `DriftEntry` (frozen dataclass with `fixture_name`, `control_id`, `mcp_status`, `harness_status`; `is_allowed_drift` property per T1-2 canonical table in `tier1-parity-invariant.md`)
    - `ParityReport` (frozen dataclass; `disallowed_drifts` property, `is_green` property, `format_summary_line()`, `format_failure_table()` per FR-004 fixed-width Markdown; no ANSI)
    - `compare(mcp: AuditResult, harness: AuditResult, fixture_name: str) -> ParityReport` function implementing the T1-8 allowed-drift table exactly

- [X] T005 [P] Create `tests/darnit/parity/tier1/fixture_meta.py` per contract `parity-toml-schema.md`:
    - `ParityMetadata` dataclass with fields matching the schema (`category`, `has_pending_llm`, `strict`, `counts`, `controls`)
    - `load_parity_metadata(fixture_dir: Path) -> ParityMetadata | None` -- returns None if `parity.toml` absent (PT-2 optional), raises `ValueError` on malformed TOML (PT-4), warns on unknown keys (PT-9), validates `category` literal + count non-negativity + `has_pending_llm` vs `counts.pending_llm > 0` agreement (PT-5, PT-6, PT-8)
    - Uses stdlib `tomllib.load(...)`; no new dep (PT-3)

- [X] T006 [P] Create `tests/darnit/parity/tier1/test_comparator.py`:
    - Enumerate every (mcp_status, harness_status) pair from the six possible statuses (36 pairs total) and assert `compare()` classifies each per the T1-8 table (T1-9 mechanical enumeration).
    - Test `AuditResult.from_mcp_json` and `from_harness_report` produce equivalent shapes from equivalent inputs.
    - Test `ParityReport.format_failure_table()` output is fixed-width Markdown (no ANSI escapes; verifiable via `assert "\033" not in output`).
    - Test `ParityReport.format_summary_line()` matches the FR-013 evidence-line shape.
    - **Determinism (MC4 fix, FR-15)**: run `compare()` twice with identical inputs and assert byte-identical `format_failure_table()` output AND byte-identical `format_summary_line()` output. Catches dict-iteration-order or time-dependent regressions.

- [X] T007 [P] Create `tests/darnit/parity/tier1/test_fixture_meta.py`:
    - PT-3: parses a valid `parity.toml` via `tomllib`.
    - PT-4: malformed TOML raises with a clear message.
    - PT-5: unknown `category` value fails validation.
    - PT-6: `has_pending_llm=true` with `counts.pending_llm=0` fails.
    - PT-8: negative count fails.
    - PT-9: unknown key produces a warning but does not fail.
    - PT-2: `load_parity_metadata(fixture_with_no_parity_toml)` returns None (not an error).

**Checkpoint**: `uv run pytest tests/darnit/parity/tier1/test_comparator.py tests/darnit/parity/tier1/test_fixture_meta.py -q` passes. Comparator + metadata parser are locked; user-story tests can consume them.

---

## Phase 3: User Story 1 -- Tier 1 MCP-vs-harness parity (P1) 🎯 MVP

**Goal**: Every PR that touches the harness or MCP tool triggers a Tier 1 parity check across the fixture corpus. A regression that makes the harness silently disagree with the MCP tool fails CI within 60 seconds with a human-readable diff table.

**Independent Test**: With the fixture corpus in place, `uv run pytest tests/darnit/parity/tier1/ -q` runs and passes; a scripted regression (adversarial test with a hand-built diverging AuditResult pair) fails the comparator with the expected table.

### Fixtures for US1

- [X] T008 [P] [US1] Create `tests/darnit/parity/fixtures/all_pass_repo/`:
    - `.baseline.toml` selecting a small subset of Level-1 controls this fixture is designed to satisfy (LICENSE presence, SECURITY.md presence, etc. -- pick 4-6 dispositive controls with no LLM step).
    - Repo files satisfying every selected control (LICENSE, SECURITY.md, README, `.github/workflows/ci.yml` if referenced).
    - `.project/project.yaml` with any required context values (security_contact etc.) so nothing is PENDING_LLM.
    - `parity.toml` with `[expected] category="all_pass" has_pending_llm=false` and matching counts.
    - Verify by running `audit_openssf_baseline(local_path=..., level=1, output_format="json")` and confirming every result is `PASS` before committing.

- [X] T009 [P] [US1] Create `tests/darnit/parity/fixtures/all_fail_repo/`:
    - `.baseline.toml` selecting 4-6 dispositive controls (same shape as T008).
    - Deliberately absent repo files -- no LICENSE, no SECURITY.md, no relevant `.github/` -- so every selected control FAILs at its `file_exists` step.
    - `parity.toml` with `[expected] category="all_fail" has_pending_llm=false` and counts.

- [X] T010 [P] [US1] Create `tests/darnit/parity/fixtures/mixed_repo/`:
    - Roughly 6 PASS, 4 FAIL, 2 WARN across the selected controls.
    - `.baseline.toml`, `.project/project.yaml` with partial context (some keys present, some missing so their controls WARN).
    - `parity.toml` with `[expected] category="mixed"` and detailed counts.
    - Include per-control `[[expected.controls]]` entries for at least three controls the test should watch closely.

- [X] T011 [P] [US1] Create `tests/darnit/parity/fixtures/pending_llm_repo/`:
    - Copy or reuse the shape of feature 026's `minimal_llm_repo` (which includes `STAGE1-REF-SECURITY-01`, a control with an `llm_extract` step that produces PENDING_LLM under the MCP tool).
    - `.baseline.toml` selecting `STAGE1-REF-SECURITY-01` plus a few dispositive controls.
    - `parity.toml` with `[expected] category="pending_llm" has_pending_llm=true` and counts.pending_llm >= 1.

### Test infrastructure + tests for US1

- [X] T012 [US1] Create `tests/darnit/parity/tier1/conftest.py` implementing fixture auto-discovery per research.md R1:
    - `pytest_generate_tests` hook that parametrizes `fixture_dir: Path` from directories directly under `tests/darnit/parity/fixtures/` containing `.baseline.toml`. Test IDs are the fixture directory names.
    - **Git-init prerequisite (HC1 fix)**: Both audit paths require the target directory to be a git repository (`prepare_audit` -> `detect_repo_from_git`). Provide a `prepared_fixture(fixture_dir, tmp_path)` fixture that:
      - Copies `fixture_dir` recursively into `tmp_path / fixture_dir.name` via `shutil.copytree`.
      - Runs `git init --initial-branch=main -q` in the copy (via `subprocess.run(check=True, capture_output=True)`).
      - Runs `git -c user.name=test -c user.email=test@example.com commit --allow-empty -q -m init` to create an initial commit.
      - Runs `git remote add origin https://github.com/fake-owner/fake-repo.git` so `detect_repo_from_git` yields deterministic owner/repo values.
      - Yields the copied directory path.
      Mirrors feature 026's `tests/darnit/harness/conftest.py::minimal_llm_repo_tree` fixture pattern verbatim.
    - Provides `mcp_tool_result(prepared_fixture)` -- invokes `audit_openssf_baseline(local_path=str(prepared_fixture), level=3, output_format="json", auto_init_config=False, attest=False, prefer_upstream=False)` and parses JSON into an `AuditResult`.
    - Provides `harness_result(prepared_fixture)` -- constructs `HarnessRun(local_path=str(prepared_fixture), level=3, llm_step=MockLLMStep(LLMJudgment(outcome="inconclusive", confidence=0.0, reasoning="tier1-mock")), per_call_timeout_s=5, total_run_timeout_s=30)` per research.md R3, awaits `run.run()` via `asyncio.new_event_loop().run_until_complete`, returns `AuditResult.from_harness_report(report)`.
    - Env-var isolation autouse: sets `ANTHROPIC_API_KEY="test-key-not-real"` so the harness's credential check passes; tests exercising missing-key paths monkeypatch.delenv explicitly.

- [X] T013 [US1] Create `tests/darnit/parity/tier1/test_mcp_vs_harness.py`:
    - `test_parity(fixture_dir, mcp_tool_result, harness_result, capsys)`: computes `ParityReport = compare(mcp_tool_result, harness_result, fixture_name=fixture_dir.name)`; emits `report.format_summary_line()` via `print` (captured by pytest -s); asserts `report.is_green` with `report.format_failure_table()` as the assertion message (FR-004).
    - **FR-013 evidence assertion (MC2 fix)**: use `capsys.readouterr()` (or `caplog` if the impl routes through logging) to capture the summary line; assert the line matches the pattern `re.compile(r"^\[tier1\] " + fixture_dir.name + r": \d+ controls compared, \d+ agreed, \d+ diverged")`. Emitted on EVERY run (green or red), so a silent no-op is caught here.
    - Full suite MUST run under 60s total; add a `pytest.mark.timeout(60)` at module level as a safety net.

- [X] T014 [P] [US1] Create `tests/darnit/parity/tier1/test_comparator_adversarial.py` per research.md R5:
    - SC-001: `test_comparator_catches_pass_to_fail_divergence` -- hand-built AuditResult pair with a PASS vs FAIL on the same control_id; assert `compare()` returns a `ParityReport` with `is_green=False` and exactly one disallowed drift.
    - SC-003: `test_failure_message_lists_all_drifts` -- seed 5 divergences on 5 different control_ids; assert `format_failure_table()` output contains 5 table rows (count `|` line-starts).
    - Allowed-drift positive cases (LC1 fix -- all three): (a) PENDING_LLM (MCP) -> WARN (harness); (b) PENDING_LLM (MCP) -> PASS (harness); (c) PENDING_LLM (MCP) -> FAIL (harness). For each, assert `is_green=True` and `drift.is_allowed_drift=True`. Documents that the T1-8 table's wildcard resolution really is any non-PENDING_LLM.
    - Disallowed-drift negative case: PENDING_LLM (harness) -> WARN (MCP); assert `is_green=False`.
    - "Missing control" case (T1-3): control appears on one side but not the other; assert this is treated as a hard failure with a "missing control" note.

- [X] T015 [P] [US1] Create `tests/darnit/parity/tier1/test_corpus_inventory.py`:
    - SC-008: iterates fixtures via `load_parity_metadata`, counts fixtures per `category`, asserts every category (`"all_pass"`, `"all_fail"`, `"mixed"`, `"pending_llm"`) has at least one representative.
    - Test collection count sanity: at least 4 fixtures are discovered (guards against accidental fixture deletion during unrelated refactors).

**Checkpoint**: `uv run pytest tests/darnit/parity/tier1/ -q` passes in under 60 seconds. Tier 1 is independently shippable if we stop here. Issue #366's mechanical part is closed by US1.

---

## Phase 4: User Story 2 -- Tier 2 skill drift detection (P2)

**Goal**: An authorized maintainer dispatches the Tier 2 workflow; it invokes the `/darnit-audit` coding-agent skill via the Claude Agent SDK on each fixture, diffs the skill's final assistant message against the raw MCP tool JSON, and either PASSes or FAILs with a per-control diff report as an artifact. Access to the API key is gated behind a required-reviewer approval on the GitHub Environment.

**Independent Test**: `uv run python tests/darnit/parity/tier2/run.py --fixture-glob "*" --dry-run` (a mode that stubs the SDK client with a canned response) runs to completion; the artifact directory contains the expected per-fixture files. Then, once merged, an authorized maintainer runs the workflow via `workflow_dispatch` and sees green.

### Tier 2 machinery (Python)

- [X] T016 [P] [US2] Create `tests/darnit/parity/tier2/skill_markdown_parser.py` per research.md R6 and data-model.md section 6:
    - `SkillReport` frozen dataclass with `parseable`, `raw_markdown`, `counts`, `controls`, `parse_notes` fields.
    - `SkillReport.parse(markdown: str) -> SkillReport` best-effort regex parser:
      - Extract summary counts (`\d+/\d+ pass|fail|warn` patterns).
      - Extract per-control claims (heading-shaped `**OSPS-XX-...**` + explicit status references).
      - Return `parseable=True` when both extractions succeed; `parseable=False` otherwise.
    - Never raises; sets `parseable=False` on any exception.

- [X] T017 [P] [US2] Create `tests/darnit/parity/tier2/test_skill_markdown_parser.py`:
    - Golden-file tests against captured skill outputs (commit at least three: `golden_all_pass.md`, `golden_mixed_drift.md`, `golden_unparseable.md`).
    - `parseable=False` for the unparseable case; `SkillReport.raw_markdown` preserved.
    - Redaction sanity: parsed output does NOT contain any credential-shaped substring (regression guard).

- [X] T018 [P] [US2] Create `tests/darnit/parity/tier2/claude_agent_sdk_client.py` per research.md R7:
    - Thin wrapper: `invoke_skill(fixture_dir, model, max_turns) -> str` returning the final assistant message.
    - Loads system prompt from `tests/darnit/parity/tier2/skill_prompt_snapshot.md` (created in T023).
    - Configures tool allow-list to only the darnit MCP tools referenced by the skill (`audit_openssf_baseline`, `list_available_checks`, `confirm_project_data`).
    - `temperature=0` or lowest available; `model` defaults to `anthropic:claude-sonnet-5`; explicit `max_turns` cap (default 20).
    - Reads `ANTHROPIC_API_KEY` from env; raises `SetupError` if absent (per FR-010).

- [X] T019 [P] [US2] Create `tests/darnit/parity/tier2/artifact_writer.py`:
    - `write_fixture_artifacts(artifact_dir, fixture_name, mcp_json, skill_markdown, diff_md, metadata)` per data-model.md section 7.
    - Creates `parity-artifacts/<fixture_name>/` with `mcp_tool_result.json`, `skill_final_message.md`, `diff_report.md`, `metadata.json`.
    - `metadata.json` includes timestamp, actor (`$GITHUB_ACTOR` if set), SHA (`$GITHUB_SHA` if set), model ID, turn count.

- [X] T020 [US2] Create `tests/darnit/parity/tier2/diff.py`:
    - `diff(mcp_result: AuditResult, skill_report: SkillReport) -> Tier2DiffReport`.
    - Per FR-008 + T2-13: any per-control status disagreement is a hard fail regardless of authority.
    - Distinguish outcomes: `SUCCESS` (agree), `SKILL_UNPARSEABLE` (skill_report.parseable=False), `COUNTS_DISAGREE` (parseable but summary counts differ from raw), `PER_CONTROL_DISAGREE` (parseable but a control's status differs).
    - Generates a Markdown `diff_report.md` for artifact-writer to persist.

- [X] T021 [US2] Create `tests/darnit/parity/tier2/run.py` (entrypoint invoked from workflow_dispatch):
    - CLI: `--fixture-glob <glob>` (default `"*"`), `--dry-run` (stubs SDK client with a canned response for T016/T017 verification without live API).
    - For each matching fixture: capture MCP tool JSON via direct Python call; invoke SDK client; parse skill output; run `diff()`; write artifacts.
    - Aggregate exit codes per contract T2-13: 0 success, 1 disagreement, 2 unparseable, 3 setup, 4 rate-limit.
    - Emit summary line to `GITHUB_STEP_SUMMARY` if the env var is set (T2-14): `"Tier 2 parity check: N fixtures checked, X drifts, Y unparseable, Z rate-limited"`.
    - Preflight audit log per T2-7/T2-8: log actor + SHA + fixture-glob to summary BEFORE consuming `ANTHROPIC_API_KEY`.

### Skill prompt snapshot

- [X] T022 [P] [US2] Snapshot the current `/darnit-audit` skill's system prompt into `tests/darnit/parity/tier2/skill_prompt_snapshot.md`:
    - If `.claude/skills/darnit-audit/` exists in the repo: copy its system-prompt content verbatim.
    - If the skill lives outside the repo (Claude Code user-scope): document the source and commit the snapshot as of the date the parity feature ships.
    - Add a top-of-file comment stating "SNAPSHOT of the /darnit-audit skill prompt as of <date>. If the live skill changes, this snapshot MAY drift; re-capture as a routine maintenance task."

### GitHub Actions workflow + its own tests

- [X] T023 [US2] Create `.github/workflows/parity-tier2.yml` per contract `tier2-workflow.md` (T2-1..T2-16):
    - `on: workflow_dispatch:` with a single `fixture_glob` input (default `"*"`).
    - Job runs on `ubuntu-latest` with `environment: parity-tier2` and `permissions: contents: read` only.
    - Steps: checkout, setup-python, uv sync --dev, preflight-log (actor + SHA + timestamp to $GITHUB_STEP_SUMMARY), run `uv run python tests/darnit/parity/tier2/run.py --fixture-glob "${{ inputs.fixture_glob }}"` with `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}`, upload `parity-artifacts/` via `actions/upload-artifact@v4` with `if: always()` so artifacts land on any exit code.
    - Add YAML comments documenting each T2-* rule this line satisfies for future reviewers.

- [X] T024 [P] [US2] Create `tests/darnit/parity/tier2/test_workflow_config.py` (offline Tier 1-style test enforcing the workflow's governance shape):
    - T2-1: parse `.github/workflows/parity-tier2.yml` as YAML; assert `on` keys are exactly `["workflow_dispatch"]`.
    - T2-2: assert job declares `environment: parity-tier2` (exact case-sensitive string).
    - T2-5: assert job declares `permissions.contents == "read"` and no other permissions are granted.
    - T2-10: assert workflow does NOT accept an `api_key` input (governance regression guard).
    - SC-005a + T2-4 (LC2 fix -- portable, no subprocess `grep`): iterate `Path(".github/workflows").glob("*.yml")` and `.glob("*.yaml")`; for each file, assert either the file's `name == "parity-tier2.yml"` OR the substring `"ANTHROPIC_API_KEY"` is absent from `file.read_text()`. Pure Python; works on Linux, macOS, Windows CI equally.
    - T2-11: assert an `actions/upload-artifact` step with `if: always()`.

### Adversarial-response Tier 2 tests (offline)

- [X] T025 [P] [US2] Create `tests/darnit/parity/tier2/test_diff_adversarial.py`:
    - SC-004: feed `diff()` a hand-built `SkillReport(parseable=True, controls=[Control(id="X", status="PASS", ...)])` and an `AuditResult` with the same control at status `"WARN"`; assert diff returns `PER_CONTROL_DISAGREE` outcome, includes X in the failing controls list.
    - Suggestive-authority case: same setup but the control's authority is `"suggestive"`; assert diff STILL returns `PER_CONTROL_DISAGREE` (T2 has no license to reinterpret regardless of authority; per FR-008).
    - Unparseable case: feed `SkillReport(parseable=False, raw_markdown="...")`; assert diff returns `SKILL_UNPARSEABLE` outcome.
    - Counts-only disagreement: feed a `SkillReport` where the summary counts differ from the tool but per-control claims agree; assert `COUNTS_DISAGREE` outcome.
    - **FR-010 fail-fast (MC1 fix)**: `test_missing_api_key_raises_setup_error` -- with `monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)`, instantiate `ClaudeAgentSdkClient` and call `invoke_skill(...)`; assert `SetupError` (or the equivalent named exception from T018) is raised with the substring `ANTHROPIC_API_KEY` in the message. Additionally: run `python tests/darnit/parity/tier2/run.py --fixture-glob "*" --dry-run=false` in a subprocess with the env var stripped (`env={"PATH": os.environ["PATH"]}`), assert exit code is 3 (SETUP per contract T2-13).

**Checkpoint**: Tier 2 machinery is complete offline. A `--dry-run` invocation of `run.py` writes artifacts against a stubbed SDK response. The GitHub Actions workflow YAML is present and passes its own config tests. Merge unblocks a manual `workflow_dispatch` invocation by an authorized maintainer.

---

## Phase 5: User Story 3 -- Fixture auto-discovery (P3)

**Goal**: A maintainer adds a new fixture directory under `tests/darnit/parity/fixtures/` and the parity tests automatically include it on the next run -- no test file changes required.

**Independent Test**: Add a directory to `tests/darnit/parity/fixtures/`, run pytest, observe the new test IDs.

### Test for US3

- [X] T026 [P] [US3] Create `tests/darnit/parity/tier1/test_auto_discovery.py`:
    - SC-007: Programmatically create a temporary fixture in a subdirectory of `tests/darnit/parity/fixtures/` (using `monkeypatch` or a helper that tracks the addition), rerun collection via `pytest.main(["--collect-only", ...])`, assert the new fixture's test ID appears in the collected tests, then clean up.
    - Alternative shape (if temp-fixture creation is fragile): assert the existing fixture count in `test_mcp_vs_harness.py::test_parity` equals the number of fixture directories that contain `.baseline.toml`, with no manual list to keep in sync.

**Checkpoint**: SC-007 verified. US3 layers cleanly on US1's infrastructure; if T012 (auto-discovery conftest) is done correctly, this test is largely a formality.

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: Docs, CI wiring, final sanity sweep, PR bookkeeping.

- [X] T027 [P] Update `CLAUDE.md`'s "Recent Changes" section (top of list) with a one-paragraph 028 entry describing the two-tier parity suite, closes #366, governance-gated Tier 2.

- [X] T028 [P] Run `uv run ruff check .` and `uv run ruff format --check .` on the new test files. Fix any lint issues.

- [X] T029 [P] Run `uv run python scripts/validate_sync.py --verbose` -- this feature doesn't touch product code but keep the check honest.

- [X] T030 [P] Full test sweep: `uv run pytest tests/ -q`. Expected: previous baseline + ~15-25 new tests (T004-T007 + T013-T015 + T017 + T024-T026), all pass, no regressions.

- [ ] T031 [P] Grep sanity: `grep -r "ANTHROPIC_API_KEY" .github/workflows/` returns matches ONLY in `parity-tier2.yml`. Run manually as pre-PR verification of SC-005a; T024 codifies this as a test but a manual check confirms the CI setup end-to-end.

- [X] T031a [P] **MC3 fix**: Create `tests/darnit/parity/tier1/test_no_product_changes.py` enforcing FR-014 mechanically:
    - Detect base ref via `git rev-parse --verify origin/main 2>/dev/null` (fall back to `main`); on local dev where no base is reachable, skip with `pytest.skip("no base ref -- CI-only check")`.
    - Run `git diff --name-only <base>...HEAD` and collect the file list.
    - Assert NO file in the diff is under `packages/darnit/src/` OR `packages/darnit-baseline/src/`.
    - Exempts test files (`packages/*/tests/`) and package config (`packages/*/pyproject.toml`) so a legitimate build-config touch isn't blocked; SC-006's product-dep check runs separately.
    - If a violation is detected, the assertion message lists the offending files with a note pointing at FR-014.
    - This test guards against future maintainers accidentally adding "a small helper" to `packages/darnit/src/darnit/harness/` from a parity-tests PR.

- [ ] T032 Manual Tier 2 dry-run against the local repo: `ANTHROPIC_API_KEY=... uv run python tests/darnit/parity/tier2/run.py --fixture-glob "all_pass_repo"` on your workstation, then inspect `parity-artifacts/`. Verify the artifact bundle shape matches T2-11 / data-model.md section 7.

- [ ] T033 Write the PR description. Structure per project convention: no Co-Authored-By: Claude trailer, no Generated with Claude Code footer. Include a summary, the governance rationale for Tier 2 manual-only, test plan, links to spec/plan/contracts, cross-links to #366 (close) + #368 + #369 (related).

---

## Dependencies & Story Completion Order

```
Phase 1 (T001-T003)  --setup--
        |
        v
Phase 2 (T004-T007)  --foundational: comparator + fixture_meta--
        |
        +------------+----------------------+
        v            v                      v
     Phase 3 (T008-T015)             Phase 4 (T016-T025)
     US1 -- MVP (Tier 1)             US2 (Tier 2 machinery + workflow)
        |
        v
     Phase 5 (T026)
     US3 -- auto-discovery test
        |
        v
     Phase 6 (T027-T033)  --polish--
```

- **Phase 1**: T001 first (scaffold); T002 [P], T003 [P] parallelizable after T001.
- **Phase 2**: T004 first (comparator module -- others depend on `AuditResult` shape); T005 [P] can start alongside T004 since it doesn't import comparator; T006 and T007 are [P] tests after their subjects exist.
- **Phase 3**: T008-T011 (fixtures) are all [P] with each other. T012 depends on T004 + T005. T013-T015 depend on T012 + at least one fixture.
- **Phase 4**: T016, T017, T018, T019, T022 are all [P] with each other. T020 depends on T016 + T018 (uses SkillReport + SDK client). T021 depends on T020 + T019. T023 depends on T021 (references `run.py`). T024, T025 are [P] tests.
- **Phase 5**: T026 depends on Phase 3 being complete.
- **Phase 6**: T030 depends on ALL previous. T027-T029, T031-T032 are largely [P]. T033 last (needs the full picture).

## Parallel Execution Examples

Within Phase 3, once Phase 2 is done:

```bash
# Fixtures in parallel
mkdir -p tests/darnit/parity/fixtures/{all_pass_repo,all_fail_repo,mixed_repo,pending_llm_repo}
# ... populate each ...

# Then tests in parallel
uv run pytest tests/darnit/parity/tier1/test_mcp_vs_harness.py \
              tests/darnit/parity/tier1/test_comparator_adversarial.py \
              tests/darnit/parity/tier1/test_corpus_inventory.py \
              -q -n auto
```

## Implementation Strategy

**MVP-first order**: Phase 1 -> Phase 2 -> Phase 3 (Tier 1 ships as its own PR increment if we want smaller reviews). Tier 2 (Phase 4) layers on top without changing Tier 1. Phase 5 is a small verification test; Phase 6 is polish.

**Two-PR option**: If the review surface for one PR is too big, split as:
- PR A: Phases 1 + 2 + 3 + 5 + partial polish = "Tier 1 MCP-vs-harness parity"
- PR B: Phase 4 + remaining polish = "Tier 2 skill-vs-tool parity"

Both PRs close #366 partially; the second one carries the actual `Fixes #366` marker.

**Time boxing**: Phase 3 is the largest slice (~8 tasks, ~4 fixtures + ~4 tests). Phase 4 is comparable (~10 tasks, more machinery). Total estimated size: ~600-800 lines net production + ~600-800 lines tests. Comparable to feature 027.

## Test coverage matrix

| Success Criterion / FR | Test task(s) |
|---|---|
| SC-001 (Tier 1 catches adversarial divergence) | T014 (comparator adversarial) |
| SC-002 (Tier 1 <60s) | T013 (`pytest.mark.timeout(60)`) |
| SC-003 (every drift has a row) | T014 (5-divergence assertion) |
| SC-004 (Tier 2 catches skill reclassification, regardless of authority) | T025 (diff adversarial + suggestive-authority case) |
| SC-005 (Tier 2 artifacts have both skill + tool on failure) | T019 (artifact_writer) + T021 (integration) |
| SC-005a (no ANTHROPIC_API_KEY exposure) | T024 (workflow config test, portable Python file iteration per LC2) + T031 (manual grep) |
| SC-006 (no product deps added) | T002 (workspace dev group only) + manual pyproject.toml diff |
| SC-007 (fixture auto-discovery) | T012 (conftest) + T026 (auto-discovery test) |
| SC-008 (four fixture categories) | T015 (corpus inventory) |
| SC-009 (issue #366 closed) | T033 (PR description with `Fixes #366`) |
| FR-010 (missing key fail-fast) | T025 (dedicated subtest -- monkeypatch.delenv + subprocess exit code 3 assertion) |
| FR-013 (green-run evidence emitted) | T013 (capsys assertion on the summary-line pattern) |
| FR-014 (no product code changes) | T031a (git-diff-based mechanical enforcement) |
| FR-015 (Tier 1 deterministic) | T006 (run-twice byte-identical assertion) |
