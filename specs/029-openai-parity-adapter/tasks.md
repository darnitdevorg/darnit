---
description: "Tasks for feature 029: OpenAI Tier 2 Parity Adapter -- second provider backend + SkillInvocationBackend Protocol seam"
---

# Tasks: OpenAI Tier 2 Parity Adapter

**Input**: Design documents from `specs/029-openai-parity-adapter/`

**Prerequisites**: plan.md (loaded), spec.md (loaded, 5 clarifications), research.md (loaded, 10 decisions), data-model.md (loaded), contracts/{skill-invocation-backend-protocol,openai-workflow}.md (loaded), quickstart.md (loaded).

**Tests**: Test tasks included. Every FR maps to a concrete pytest module or a workflow-config assertion. Load-bearing SCs: SC-002 (OPENAI_API_KEY exclusive to one workflow), SC-003 (adversarial: skill reclassification caught), SC-005 (Protocol conformance), SC-007 (extensibility: new backend without shared-module edits), SC-010 (pinned versioned model), SC-011 (turn-cap-exhausted outcome).

**Organization**: Tasks grouped by user story. Feature 028 (audit parity tests) is a hard dependency. The refactor of feature 028's `claude_agent_sdk_client.py` into the new Protocol-conforming layout is done under Phase 2 (foundational) so it's a shared prerequisite for both P1 (OpenAI backend) and P2 (extensibility test).

**Branch base**: `028-audit-parity-tests` (PR #370, still open). Rebase to `main` once #370 lands. Do NOT branch from `main` directly -- feature 029 depends on 028's Tier 2 machinery.

**Closes**: #368 on merge.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Parallelizable with other [P] tasks in the same phase
- **[Story]**: Which user story (US1, US2, US3)
- File paths are exact and repository-relative

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the OpenAI SDK to the workspace dev group. Zero product-package changes (SC-006). No new subpackage; the extension lives under `tests/darnit/parity/tier2/backends/`.

- [X] T001 Add `openai>=1.50` to the workspace-level `pyproject.toml`'s `dev` extra, alongside `claude-agent-sdk` from feature 028. MUST NOT modify `packages/darnit/pyproject.toml` or `packages/darnit-baseline/pyproject.toml`. Include a comment identifying it as a Tier 2 test-only dep. Then run `uv sync --extra dev` and confirm `openai` is importable.

- [X] T002 [P] Create the new directory `tests/darnit/parity/tier2/backends/` with an empty `__init__.py` placeholder (will be populated in Phase 2). Ensures test collection doesn't fail when subsequent phases add files.

**Checkpoint**: `openai` is importable; `tests/darnit/parity/tier2/backends/` exists as a Python package.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extract the `SkillInvocationBackend` Protocol. Refactor feature 028's Claude client into a class conforming to the Protocol. Register both existing backends in a factory dict. Preserve backwards-compat via a shim at the old import path so feature 028's existing tests continue to work unchanged.

**CRITICAL**: No user-story tasks can proceed until this phase is complete.

- [X] T003 Create `tests/darnit/parity/tier2/backends/base.py` per data-model.md section 1-3:
    - `SetupError` (RuntimeError subclass; docstring cites B-11..B-13 from `contracts/skill-invocation-backend-protocol.md`)
    - `SkillInvocationResult` frozen dataclass with `final_message: str`, `model: str`, `turn_count: int`, `metadata: dict[str, Any] = field(default_factory=dict)`, `turn_cap_exhausted: bool = False`
    - `SkillInvocationBackend` Protocol -- `@runtime_checkable`, `name: str`, async `invoke(fixture_dir, model, max_turns) -> SkillInvocationResult`, classmethod `check_env() -> None` (contract QR-1..QR-3 shape)
    - `__all__` tuple exporting the four names

- [X] T004 Refactor feature 028's `tests/darnit/parity/tier2/claude_agent_sdk_client.py` into `tests/darnit/parity/tier2/backends/claude_agent_sdk.py` per data-model.md section 5:
    - Rename `invoke_skill` function to a method on new class `ClaudeAgentSdkBackend`
    - `name = "claude_agent_sdk"` class attribute
    - `check_env()` classmethod checking `ANTHROPIC_API_KEY` (raises SetupError from `backends/base.py`)
    - `async def invoke(self, fixture_dir, model, max_turns) -> SkillInvocationResult` -- body is feature 028's existing `invoke_skill` logic, unchanged behavior
    - Import `SetupError`, `SkillInvocationResult` from `backends.base`
    - Preserve `PROMPT_SNAPSHOT_PATH` module constant

- [X] T005 Convert `tests/darnit/parity/tier2/claude_agent_sdk_client.py` into a backwards-compat re-export shim per data-model.md section 5. Body:
    ```python
    """Backwards-compat shim; superseded by
    tests/darnit/parity/tier2/backends/claude_agent_sdk.py."""

    from tests.darnit.parity.tier2.backends.base import (
        SetupError, SkillInvocationResult,
    )
    from tests.darnit.parity.tier2.backends.claude_agent_sdk import (
        ClaudeAgentSdkBackend, PROMPT_SNAPSHOT_PATH,
    )


    async def invoke_skill(fixture_dir, model="anthropic:claude-sonnet-5", max_turns=20):
        """Deprecated: use ClaudeAgentSdkBackend.invoke() directly."""
        return await ClaudeAgentSdkBackend().invoke(fixture_dir, model, max_turns)


    __all__ = ("SetupError", "SkillInvocationResult", "invoke_skill", "PROMPT_SNAPSHOT_PATH")
    ```
    This preserves feature 028's tests that import from the old path.

- [X] T006 [P] Create `tests/darnit/parity/tier2/backends/noop.py` per data-model.md section 7. `NoopBackend` class satisfying the Protocol: `name = "noop"`, `check_env()` returns None, `invoke()` returns a canned `SkillInvocationResult` with `final_message="# noop backend\n\nPassed: 0\nFailed: 0"`, `model=model`, `turn_count=0`, `metadata={"backend": "noop"}`. Docstring documents its role as a test-only fixture (NOT a template).

- [X] T007 [P] Populate `tests/darnit/parity/tier2/backends/__init__.py` with `BACKEND_REGISTRY` dict per data-model.md section 4:
    ```python
    from .base import (
        SetupError, SkillInvocationBackend, SkillInvocationResult,
    )
    from .claude_agent_sdk import ClaudeAgentSdkBackend
    from .openai_backend import OpenAIBackend

    BACKEND_REGISTRY: dict[str, type[SkillInvocationBackend]] = {
        "claude_agent_sdk": ClaudeAgentSdkBackend,
        "openai": OpenAIBackend,
    }

    __all__ = (
        "SetupError", "SkillInvocationBackend", "SkillInvocationResult",
        "ClaudeAgentSdkBackend", "OpenAIBackend", "BACKEND_REGISTRY",
    )
    ```
    NOTE: this task depends on T008's `openai_backend.py` existing; do T008 first OR add a placeholder `OpenAIBackend` stub in `openai_backend.py` before running the import.

- [X] T008 Create `tests/darnit/parity/tier2/backends/openai_backend.py` skeleton (implementation body deferred to Phase 3 T010). Just the class shell:
    ```python
    from tests.darnit.parity.tier2.backends.base import (
        SetupError, SkillInvocationResult,
    )


    class OpenAIBackend:
        name = "openai"

        @classmethod
        def check_env(cls) -> None: ...  # T010 implements

        async def invoke(self, fixture_dir, model, max_turns): ...  # T010 implements
    ```
    Skeleton exists so T007 can import it; T010 fills in the body.

- [X] T009 [P] Run feature 028's existing Tier 2 tests unchanged: `uv run pytest tests/darnit/parity/tier2/ -q`. All 21 must still pass. This is the refactor's canary: if any feature-028 test breaks, the shim (T005) or the class (T004) is wrong. Fix before proceeding. **LC4 pointer**: feature-028 tests most likely to surface a shim regression: `test_diff_adversarial.py::TestFR010MissingApiKey` (imports `SetupError` + `invoke_skill` via the old shim path); `test_workflow_config.py` (adding `parity-tier2-openai.yml` will trigger its cross-file grep -- adjust the assertion if it now counts one extra workflow file); `test_skill_markdown_parser.py` (imports `SkillReport` -- unchanged path). If a rename slips in during #370's review, expect breakage in `test_diff_adversarial.py` first.

- [X] T009a [P] **MC3 fix**: Create `tests/darnit/parity/tier2/test_shim_exports.py` -- a defensive inventory:
    - Import every public name from feature 028's ORIGINAL public surface via the shim path: `from tests.darnit.parity.tier2.claude_agent_sdk_client import SetupError, SkillInvocationResult, invoke_skill, PROMPT_SNAPSHOT_PATH`.
    - Assert each imported name is not None AND matches expected type (SetupError is a class subclass of RuntimeError; SkillInvocationResult is a class; invoke_skill is callable; PROMPT_SNAPSHOT_PATH is a Path).
    - If a future refactor adds a new public name to feature 028's original module, this test catches when the shim silently drops it. Belt-and-suspenders alongside T009's full regression sweep.

**Checkpoint**: Feature 028's Tier 2 tests pass unchanged; `BACKEND_REGISTRY` contains two entries; `ClaudeAgentSdkBackend` and `NoopBackend` satisfy the Protocol via `isinstance` check.

---

## Phase 3: User Story 1 -- Maintainer runs OpenAI Tier 2 parity check (P1) 🎯 MVP

**Goal**: A maintainer dispatches `parity-tier2-openai.yml`, the workflow invokes OpenAI's Chat Completions API with the darnit audit tool registered, captures the final assistant message, and diffs it against the raw MCP tool JSON. Any per-control disagreement is a hard failure with a diff artifact.

**Independent Test**: An authorized maintainer runs `gh workflow run parity-tier2-openai.yml --repo darnitdevorg/darnit -f fixture_glob="all_pass_repo"`. The workflow pauses at the reviewer gate. Once approved, it runs to completion; artifact bundle at `parity-artifacts/all_pass_repo/` contains `mcp_tool_result.json`, `openai_final_message.md`, `diff_report.md`, `metadata.json`.

### Implementation for US1

- [X] T010 [US1] Implement `OpenAIBackend.invoke()` per data-model.md section 6 and research.md R3:
    - Import `openai.AsyncOpenAI`, `openai.APIError` locally inside `invoke()` (delayed import so `check_env()` doesn't need the SDK)
    - Load system prompt from `PROMPT_SNAPSHOT_PATH` (imported from feature 028's snapshot path)
    - Initialize `client = openai.AsyncOpenAI()` (SDK reads `OPENAI_API_KEY` from env automatically)
    - Build `messages = [{"role": "system", ...}, {"role": "user", ...}]` with the user message telling the model to audit `fixture_dir`
    - Loop `for turn in range(max_turns)`:
      - Call `await client.chat.completions.create(model=model, messages=messages, tools=_TOOL_SCHEMAS, tool_choice="auto", temperature=0.0)`
      - If response's `msg.tool_calls`: append the assistant message + dispatch each tool call via `_dispatch_tool_call` (data-model.md section 8), append each result as a `{"role": "tool", ...}` message, continue
      - If `msg.content`: return `SkillInvocationResult(final_message=msg.content, model=model, turn_count=turn+1, metadata={"backend": "openai"})`
    - Fell out of loop: return `SkillInvocationResult(final_message="", model=model, turn_count=max_turns, metadata={"backend": "openai"}, turn_cap_exhausted=True)`
    - Implement `check_env()` classmethod raising `SetupError("Tier 2 OpenAI backend requires OPENAI_API_KEY...")`
    - Implement `_TOOL_SCHEMAS` module constant + `_dispatch_tool_call` helper per data-model.md section 8. `_dispatch_tool_call` forces `local_path=str(fixture_dir)` to prevent the model from wandering outside the fixture (contract B-17).

- [X] T011 [US1] Update `tests/darnit/parity/tier2/run.py`:
    - Add `--backend <name>` argument (default `"claude_agent_sdk"`, choices from `BACKEND_REGISTRY.keys()`).
    - Add `--model <name>` argument (no default -- required in production; the workflow YAML supplies it).
    - Add `--max-turns <int>` argument (default 20).
    - Replace `_run_skill()` per data-model.md section 9: on non-dry-run, look up `BACKEND_REGISTRY[args.backend]`, call `check_env()` (raises SetupError -> exit 3), instantiate, `await backend.invoke(fixture_dir, args.model, args.max_turns)`.
    - Extend exit-code aggregation: if any fixture's outcome is `turn_cap_exhausted`, exit code becomes 5. Preserve existing codes 0/1/2/3/4.
    - Preserve `--dry-run` behavior; dry-run stub does NOT go through the backend registry.

- [X] T012 [US1] Update `tests/darnit/parity/tier2/diff.py`:
    - Recognize `SkillInvocationResult.turn_cap_exhausted=True` in the `diff()` function -- BEFORE the parseability check.
    - When true, return `Tier2DiffReport(outcome="turn_cap_exhausted", diff_markdown=<explanation>)`.
    - Diff markdown text: `"# Tier 2 parity: {fixture_name}\n\nFAIL: model exhausted its turn cap ({max_turns}) without emitting a final message. This is DISTINCT from unparseable output -- the assistant kept calling tools instead of summarizing.\n\nSee `metadata.json` for the turn count. The raw tool-call transcript is NOT captured (privacy + noise; not needed to diagnose 'model didn't converge')."`
    - Add `"turn_cap_exhausted"` to the `Tier2Outcome` IntEnum (value `5`). Update the outcome-to-exit-code mapping in `run.py` accordingly.

- [X] T013 [US1] Update `tests/darnit/parity/tier2/artifact_writer.py` per data-model.md section 10:
    - Add optional `provider: str = "claude"` parameter.
    - Compute final-message filename: `"skill_final_message.md"` when `provider == "claude"`, else `f"{provider}_final_message.md"`.
    - No other behavior change.

- [X] T014 [US1] Update `run.py`'s artifact-writing call site to pass `provider=args.backend` (or a mapped value; `claude_agent_sdk` maps to `"claude"` filename convention; `openai` maps to `"openai"`). The mapping lives in `run.py`; a helper `_provider_filename_prefix(backend_name)` returns the string used for the final-message filename.

- [X] T015 [US1] Create `.github/workflows/parity-tier2-openai.yml` per contract `openai-workflow.md` (OW-1..OW-17):
    - `on: workflow_dispatch:` with inputs `fixture_glob` (default `"*"`) AND `model` (default `gpt-4o-2024-08-06`).
    - Job runs on `ubuntu-latest` with `environment: parity-tier2-openai` and `permissions: contents: read`.
    - Steps: checkout, setup-python, uv sync --extra dev, preflight-log (actor + SHA + timestamp + fixture_glob + model to `$GITHUB_STEP_SUMMARY`), run `uv run python -m tests.darnit.parity.tier2.run --backend openai --fixture-glob "${{ inputs.fixture_glob }}" --model "${{ inputs.model }}"` with `OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}` env, upload `parity-artifacts/` via `actions/upload-artifact@v4` with `if: always()`.
    - Add YAML comments documenting each OW-* rule the line satisfies.

### Tests for US1

- [X] T016 [P] [US1] Create `tests/darnit/parity/tier2/test_openai_backend_adversarial.py` covering SC-003, SC-011, FR-011, FR-014:
    - `test_skill_reclassification_caught` (SC-003): mock `openai.AsyncOpenAI` to return a canned response where the assistant's final message reports a control as PASS while the raw tool output reports WARN. Run `run.py` (or `diff()` directly) and assert exit code / outcome is `per_control_disagree`.
    - `test_suggestive_authority_no_license_to_reinterpret` (FR-011): same setup but the control's authority is `suggestive`. Assert diff STILL returns `per_control_disagree`.
    - `test_turn_cap_exhausted` (SC-011): mock the SDK to return a response emitting a tool_call on EVERY turn (never a text message). With `max_turns=3`, assert the backend returns `SkillInvocationResult(turn_cap_exhausted=True, ...)`; running through `run.py` produces exit code 5.
    - `test_local_path_forced_to_fixture_dir` (B-17): mock the SDK to return a tool_call whose arguments include `local_path="/malicious/path"`. Assert `_dispatch_tool_call` overrides with the fixture_dir and does NOT invoke `audit_openssf_baseline` on the malicious path.
    - **`test_openai_style_markdown_is_parseable_by_shared_parser` (MC2 fix, FR-14)**: feed feature 028's `SkillReport.parse()` a canned Markdown response shaped like an OpenAI final message (e.g., "**OSPS-DO-01.01**: PASS\nSummary: 2 passed, 0 failed" or the shape a real GPT-4o response would emit for the skill's prompt). Assert `parseable == True`, `counts` and `controls` are extracted. Guards against a silent parser fork -- if OpenAI's Markdown format systematically requires different regexes, this test surfaces it as a distinct failure class ("parser needs OpenAI-shape support") rather than a runtime "unparseable" failure per fixture.

- [X] T017 [P] [US1] Add `test_openai_missing_key_fails_fast` to `test_openai_backend_adversarial.py`:
    - With `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`, call `OpenAIBackend.check_env()` and assert `SetupError` with substring "OPENAI_API_KEY".
    - Subprocess test: run `python -m tests.darnit.parity.tier2.run --backend openai --fixture-glob "all_pass_repo"` with env stripped; assert exit code 3.

- [X] T018 [P] [US1] Extend `tests/darnit/parity/tier2/test_workflow_config.py` to cover the OpenAI workflow (contract OW-1..OW-15 + SC-002 + SC-010):
    - `test_openai_only_workflow_dispatch_trigger`: parse `parity-tier2-openai.yml`; assert only `workflow_dispatch` trigger.
    - `test_openai_environment_declared`: assert `environment: parity-tier2-openai`.
    - `test_openai_permissions_read_only`: assert `permissions.contents: read`; no write scopes.
    - `test_openai_key_only_in_openai_workflow` (SC-002): iterate `.github/workflows/*.yml`; assert `OPENAI_API_KEY` appears in `parity-tier2-openai.yml` only. Pure Python file iteration (no `grep`), same pattern as feature 028's SC-005a check.
    - `test_no_anthropic_key_in_openai_workflow` (OW-9): assert `ANTHROPIC_API_KEY` does NOT appear in `parity-tier2-openai.yml`.
    - `test_no_openai_key_in_claude_workflow` (OW-8): assert `OPENAI_API_KEY` does NOT appear in `parity-tier2.yml`.
    - `test_openai_workflow_pins_versioned_model` (SC-010): parse the workflow's `model` input default; assert it matches `^[a-z0-9\-]+-\d{4}-\d{2}-\d{2}$` OR another explicit versioned pattern. `gpt-4o` alone (moving alias) fails.
    - `test_openai_artifact_upload_always` (OW-14): assert `actions/upload-artifact` step has `if: always()`.

**Checkpoint**: The OpenAI workflow is present, its config tests pass, adversarial tests pass. Manual dry-run: `uv run python -m tests.darnit.parity.tier2.run --backend openai --fixture-glob "all_pass_repo" --dry-run` writes artifacts to `parity-artifacts/`. US1 is independently shippable if we stop here.

---

## Phase 4: User Story 2 -- Extensibility for future providers (P2)

**Goal**: A future maintainer adds a Gemini/xAI/self-hosted backend by writing one file + one workflow YAML, no edits to shared modules. Mechanically enforceable.

**Independent Test**: SC-005 (Protocol conformance) + SC-007 (extensibility). Run `test_backend_protocol_conformance.py`; every registered backend + the `NoopBackend` passes `isinstance(x, SkillInvocationBackend)`. Run `test_backend_extensibility.py`; registering a `NoopBackend` (or a temporary in-test mock backend) via the runner's `backends=` override invokes it without touching any shared file.

### Tests for US2

- [X] T019 [P] [US2] Create `tests/darnit/parity/tier2/test_backend_protocol_conformance.py` covering SC-005:
    - For each entry in `BACKEND_REGISTRY`: `assert isinstance(BackendClass(), SkillInvocationBackend)`.
    - Also verify `NoopBackend` satisfies the Protocol (though it's not in `BACKEND_REGISTRY`).
    - Assert every backend has a non-empty `name: str` attribute.
    - Assert every backend has a `check_env` classmethod (via `inspect.ismethod` on the class).

- [X] T020 [P] [US2] Create `tests/darnit/parity/tier2/test_backend_extensibility.py` covering SC-007:
    - Import `NoopBackend` from `backends/noop.py`.
    - Instantiate the runner (or call `_main_async` with a mocked args + injected `backends={"noop": NoopBackend}` dict).
    - Assert the runner invokes `NoopBackend.invoke()` and writes artifacts.
    - Second test: build an ad-hoc `_InlineExtBackend` class inside the test that satisfies the Protocol; inject it via `backends={"inline": _InlineExtBackend}`; assert the runner picks it up.
    - Meta-assertion: with `git diff --name-only <base>...HEAD`, verify no file under `tests/darnit/parity/tier2/` OTHER than the two new test files was modified when adding the ad-hoc backend. Skipped when no base ref reachable (local dev). Guards SC-007's "no shared-module edits" property mechanically.

- [X] T021 [US2] Update the `run.py` module to accept a `backends: dict[str, type[SkillInvocationBackend]] | None = None` parameter on `_main_async` and `main`; if provided, use it instead of `BACKEND_REGISTRY`. This enables T020's test-side backend injection without monkey-patching module globals. Preserve the CLI path -- `backends=None` uses the module-level registry.

**Checkpoint**: A future author writing a new backend can add ONE file (`backends/my_provider.py`), ONE line to `BACKEND_REGISTRY`, and ONE workflow YAML file -- no other edits. Verified by T020.

---

## Phase 5: User Story 3 -- Aggregate provider drift comparison (P3, deferred)

**Goal**: Compare Claude and OpenAI final messages for the same fixture, surfacing provider-specific bias.

**Priority 3 = out of MVP scope.** The spec's US3 says "genuinely useful but not urgent." Fixture-level cross-provider comparison is a maintainer-run local script; not automated in CI.

### Implementation for US3 (optional, may slip)

- [ ] T022 [P] [US3] Create `tests/darnit/parity/tier2/scripts/aggregate_provider_diff.py` (local maintainer script, NOT invoked by any pytest). Reads two artifact bundles (`parity-artifacts-claude/` + `parity-artifacts-openai/`) OR one `parity-artifacts/` directory containing both providers' final messages; for each fixture, parses both providers' summaries; emits a Markdown table `| control_id | claude_status | openai_status | disagreement |`.
    - Not a runnable CI job; documented in `quickstart.md`.
    - Skipped if T022 slips -- US3 is P3.

**Checkpoint**: MVP for feature 029 is Phase 1+2+3+4. Phase 5 is nice-to-have; if it slips, feature 029 ships without it.

---

## Phase 6: Polish & Cross-Cutting

- [X] T023 [P] Update `CLAUDE.md`'s "Recent Changes" section with a one-paragraph 029 entry describing the OpenAI Tier 2 backend + Protocol seam + governance parity, closes #368.

- [X] T024 [P] Run `uv run ruff check tests/darnit/parity/` and `uv run ruff format --check tests/darnit/parity/`. Fix any lint issues.

- [X] T024a [P] **MC1 fix (FR-013 fixture-diff sanity)**: Run `git diff --name-only <base>...HEAD -- tests/darnit/parity/fixtures/` and confirm the output is empty. FR-013 says the fixture corpus is reused from feature 028 unchanged; if this PR modifies a fixture, that's out of scope for feature 029. Manual pre-PR check (not automated as a test because "shouldn't add a fixture" is a soft constraint, not a load-bearing invariant). If a fixture change is genuinely needed, split it into a separate PR.

- [X] T025 [P] Run `uv run python scripts/validate_sync.py --verbose`. Feature 029 doesn't touch product code but keep the check honest.

- [X] T026 [P] Full test sweep: `uv run pytest tests/ -q`. Expected: feature-028 baseline (2589 passed) + Phase-3+4 new tests, all pass, no regressions.

- [X] T027 [P] Local dry-run smoke: `uv run python -m tests.darnit.parity.tier2.run --backend openai --fixture-glob "all_pass_repo" --dry-run --artifact-dir /tmp/parity-openai-dryrun`. Verify artifact layout matches data-model.md section 10 + OW-15.

- [X] T028 [P] Manual grep sanity for SC-002: `grep -r "OPENAI_API_KEY" .github/workflows/` returns matches ONLY in `parity-tier2-openai.yml`. Complements T018's automated test.

- [ ] T029 Write the PR description. Structure per project convention: no Co-Authored-By: Claude trailer, no Generated with Claude Code footer. Include a summary, the two-Environment governance rationale, test plan, links to spec/plan/contracts, cross-links to #368 (close) + #369 (related, for scheduled cadence).

---

## Before-merge maintainer actions (LC3)

These are NOT tasks in the code sense -- they are manual GitHub UI steps a maintainer MUST perform before dispatching Tier 2 OpenAI in production. Automated tests can verify the workflow YAML shape but cannot verify the Environment's UI-side configuration.

- [ ] **M1**: Create GitHub Environment `parity-tier2-openai` under Settings -> Environments in `darnitdevorg/darnit`.
- [ ] **M2**: Configure the Environment with a required-reviewer list (authorized maintainers only).
- [ ] **M3**: Add secret `OPENAI_API_KEY` at the ENVIRONMENT level (NOT repo level). Confirm the secret does not appear under Settings -> Secrets and variables -> Actions at the repository level.
- [ ] **M4**: Verify no other GitHub Environment on the repo also holds `OPENAI_API_KEY` (blast-radius minimization, per OW-8).

Feature 028's `parity-tier2` Environment (for `ANTHROPIC_API_KEY`) is a prerequisite and is documented in feature 028's quickstart -- both Environments coexist independently.

---

## Rebase conflict watch list (MC4)

Feature 029 stacks on feature 028's still-open PR (#370). If reviews on #370 change the Tier 2 machinery, feature 029's rebase will conflict specifically in these files. Order matters: resolve top-down; downstream files depend on upstream shape:

1. **`tests/darnit/parity/tier2/backends/claude_agent_sdk.py`** (new -- feature 029). If #370 rename anything the shim re-exports, update `backends/claude_agent_sdk.py` first.
2. **`tests/darnit/parity/tier2/claude_agent_sdk_client.py`** (converted to shim by feature 029). If #370 adds a new public export to the original module, add a passthrough to the shim.
3. **`tests/darnit/parity/tier2/run.py`** (extended by feature 029). Any #370 change to argument parsing or the outcome-to-exit-code map has to be re-integrated with feature 029's `--backend`, `--model`, `--max-turns`, and exit 5 additions.
4. **`tests/darnit/parity/tier2/diff.py`** (extended by feature 029). Any #370 change to `Tier2Outcome` or `Tier2DiffReport` shape has to be re-integrated with feature 029's `turn_cap_exhausted` outcome.
5. **`tests/darnit/parity/tier2/artifact_writer.py`** (extended by feature 029). Any #370 change to the artifact-shape has to be re-integrated with feature 029's provider parameter.
6. **`.github/workflows/parity-tier2-openai.yml`** (new -- feature 029). Not conflict-prone (new file), but re-verify the workflow-config test in `test_workflow_config.py` still parses the OpenAI workflow after any #370 shape changes to the Claude workflow.

Post-rebase: run `uv run pytest tests/darnit/parity/tier2/ -q` and confirm ALL tests pass. If feature 028's test file names changed during #370's review, T009's "regression check" invocation must be updated.

---

## Dependencies & Story Completion Order

```
Phase 1 (T001-T002)  --setup + openai SDK dep--
        |
        v
Phase 2 (T003-T009)  --foundational: Protocol + refactor + registry + shim + regression check--
        |
        +-----+---------------------+
        v     v                     v
     Phase 3 (T010-T018)     Phase 4 (T019-T021)
     US1 -- MVP OpenAI       US2 -- extensibility tests
        |                      |
        +-----+----------------+
              v
     Phase 5 (T022)   --US3 aggregate script (optional; deferred if it slips)--
              |
              v
     Phase 6 (T023-T029)  --polish--
```

- **Phase 1**: T001 first (openai SDK), T002 [P] parallel.
- **Phase 2**: T003 first (Protocol). T004 depends on T003. T005 depends on T004. T006, T008 depend on T003 -- and **T008 MUST run before T007** (T007 imports `OpenAIBackend` from `openai_backend.py`; T008 creates the skeleton class so the import resolves). T007 also depends on T004. T009 and T009a are regression checks that run after T003-T008. T004/T005 are file-based coordinations on the Claude client; must go in that order.
- **Phase 3**: T010 first (OpenAIBackend body). T011 depends on T010 + T007. T012, T013, T014 depend on T012/T013. T015 depends on T011 (references `run.py`). T016-T018 are [P] tests after their subjects exist.
- **Phase 4**: T019, T020 are [P] tests. T021 (`run.py` accept backends= param) is required for T020's injection test.
- **Phase 5**: T022 [P], optional.
- **Phase 6**: T023-T028 [P]. T026 (full sweep) depends on ALL previous. T029 last.

## Parallel Execution Examples

Once Phase 2 is done, run Phase 3+4 tests in parallel:

```bash
uv run pytest tests/darnit/parity/tier2/test_openai_backend_adversarial.py \
              tests/darnit/parity/tier2/test_workflow_config.py \
              tests/darnit/parity/tier2/test_backend_protocol_conformance.py \
              tests/darnit/parity/tier2/test_backend_extensibility.py \
              -q -n auto
```

## Implementation Strategy

**MVP-first order**: Phase 1 -> Phase 2 -> Phase 3 (US1 delivers issue #368's close). Phase 4 (extensibility guarantees) is P2 -- shipped in the same PR because it's small and the tests need Phase 2's Protocol.

**Two-PR option**: Not recommended for feature 029. The refactor + Protocol + OpenAI adapter form a coherent unit; splitting them creates a middle state where the Protocol exists but no non-Claude backend does. Not worth the review-surface fragmentation.

**Time boxing**: Phase 2 (refactor + Protocol) is the delicate part; Phase 3 (OpenAI adapter) is straightforward once the Protocol is locked. Total estimated size: ~500-700 lines net production + ~400-500 lines tests. Smaller than feature 028 because we're extending existing scaffolding.

## Test coverage matrix

| Success Criterion / FR | Test task(s) |
|---|---|
| SC-001 (workflow produces artifact bundle end to end) | Manual verification (T027 dry-run + one production dispatch after merge) |
| SC-002 (OPENAI_API_KEY exclusive to one workflow) | T018 (workflow config test) + T028 (manual grep sanity) |
| SC-003 (skill reclassification caught, any authority) | T016 (adversarial: PASS-over-WARN with suggestive + dispositive) |
| SC-004 (missing key fail-fast) | T017 (unit + subprocess exit code 3) |
| SC-005 (Protocol conformance across all backends) | T019 (registry-iteration isinstance) |
| SC-006 (no product deps added) | T001 (dev-group only) + feature 028's `test_no_product_changes.py` guard |
| SC-007 (extensibility -- no shared-module edits) | T020 (backend injection + git-diff meta-assertion) |
| SC-008 (issue #368 closed) | T029 (PR desc with `Fixes #368`) |
| SC-009 (30-min corpus wall clock) | Manual verification after first production dispatch |
| SC-010 (pinned versioned model default) | T018 (regex against workflow YAML input default) |
| SC-011 (turn_cap_exhausted outcome) | T016 (mocked infinite-tool-call response; asserts exit code 5) |
| FR-001 (Chat Completions loop) | T010 (implementation) + T016 (adversarial exercises the loop) |
| FR-004 (`--backend` CLI + registry dispatch) | T011 (impl) + T020 (extensibility test proves runtime lookup works) |
| FR-010 (turn cap + exit code 5) | T016 (SC-011 above) |
| FR-013 (fixture corpus reused, no changes) | T024a (manual pre-PR fixture-diff check, MC1 fix) + feature 028's `test_no_product_changes.py` guard |
| FR-014 (parser reused, no fork) | T016 (MC2 fix: `test_openai_style_markdown_is_parseable_by_shared_parser`) |
