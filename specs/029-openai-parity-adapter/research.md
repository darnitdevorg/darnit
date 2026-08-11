# Phase 0 Research: OpenAI Tier 2 Parity Adapter

**Feature**: 029-openai-parity-adapter | **Date**: 2026-08-10

The five clarify decisions locked the load-bearing choices (API surface, registry mechanism, turn-cap outcome, model pin, NoopBackend location). This file covers the residual technical decisions Phase 1 design needs to sit on.

## R1. Protocol shape (`SkillInvocationBackend`)

**Decision**: `@runtime_checkable` Protocol in `tests/darnit/parity/tier2/backends/base.py`:

```python
@runtime_checkable
class SkillInvocationBackend(Protocol):
    name: str
    async def invoke(self, fixture_dir: Path, model: str, max_turns: int) -> SkillInvocationResult: ...
    @classmethod
    def check_env(cls) -> None: ...  # raises SetupError if provider credentials absent
```

- `name` is the string key used by `BACKEND_REGISTRY` and by the `--backend` CLI flag.
- `invoke()` takes an explicit `model` and `max_turns` so the runner (or workflow YAML) supplies them, not the adapter's default.
- `check_env()` is a classmethod so the runner can validate credentials WITHOUT constructing a backend instance -- cheap fail-fast.
- `SkillInvocationResult` gets a new optional `turn_cap_exhausted: bool` field alongside the existing `final_message`, `model`, `turn_count`, `metadata` fields.

**Rationale**: Matches feature 028's existing `SkillInvocationResult` shape and its `SetupError` exception with minimal disruption. `@runtime_checkable` enables `isinstance` conformance checks in SC-005 tests.

**Alternatives considered**:
- Abstract base class (`abc.ABC`): rejected -- Protocol is more Pythonic for duck-typed adapters and lets `NoopBackend` be a plain class without explicit inheritance.
- Separate `credentials_check` module: rejected -- keeping the check on the backend class localizes the "how do I know this provider is ready" question.

## R2. Refactoring feature 028's Claude client

**Decision**: Move `claude_agent_sdk_client.py` -> `backends/claude_agent_sdk.py`. Convert `invoke_skill()` function into a class `ClaudeAgentSdkBackend` with `async def invoke(...)` + `classmethod check_env()`. Preserve the existing `invoke_skill()` and `SetupError` exports at the old path via a re-export module (`tests/darnit/parity/tier2/claude_agent_sdk_client.py` becomes a shim: `from tests.darnit.parity.tier2.backends.claude_agent_sdk import ...`). Feature-028 tests continue to work unchanged.

**Rationale**: A refactor that keeps the old import path working is safer for a stacked-PR world where feature 028 is unmerged. If 028 lands first with the current shape, this refactor's diff is minimal.

**Alternatives considered**:
- Delete `claude_agent_sdk_client.py` entirely and update every import: rejected -- requires touching more files; risks a mid-review merge conflict with 028 test edits that could still land.
- Leave feature 028's client as-is and have the OpenAI backend live separately without a shared Protocol: rejected -- forgoes SC-005 (protocol conformance) verification and SC-007 (extensibility).

## R3. OpenAI Chat Completions loop shape

**Decision**: The backend implements a classic Chat Completions tool-call loop:

```python
messages = [{"role": "system", "content": _load_skill_prompt()},
            {"role": "user", "content": f"Audit the repository at {fixture_dir}. Summarize per your usual format."}]

for turn in range(max_turns):
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        tools=_darnit_tool_schemas(),
        tool_choice="auto",
        temperature=0.0,
    )
    msg = response.choices[0].message
    if msg.tool_calls:
        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            result = _dispatch_tool_call(call, fixture_dir)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })
        continue
    if msg.content:
        return SkillInvocationResult(final_message=msg.content, model=model, turn_count=turn+1, ...)
# Fell out of the loop without a final text message:
return SkillInvocationResult(final_message="", turn_cap_exhausted=True, ...)
```

- `temperature=0.0` for reproducibility (matches feature 028's Claude adapter policy).
- `tool_choice="auto"` lets the model decide whether to call tools or answer directly.
- `_darnit_tool_schemas()` produces OpenAI-format function schemas for the audit tools the skill uses (mainly `audit_openssf_baseline`).
- `_dispatch_tool_call()` maps a tool_call to a Python call and JSON-stringifies the result.

**Rationale**: This is the canonical OpenAI tool-loop shape. Stateless per invocation matches Q1's clarify decision. `temperature=0.0` addresses the reproducibility rationale from Q4.

**Alternatives considered**:
- Streaming responses: rejected -- adds complexity; the final message is what the parser reads, not incremental tokens.
- Function-calling with `strict=True` (structured outputs): considered; may not be worth the SDK-version coupling for this MVP. Deferred to a follow-up if the parser routinely mis-extracts.

## R4. Tool schema for `audit_openssf_baseline`

**Decision**: One OpenAI tool schema, matching the MCP tool's signature:

```json
{
  "type": "function",
  "function": {
    "name": "audit_openssf_baseline",
    "description": "Run darnit's OpenSSF Baseline audit on the repository at local_path.",
    "parameters": {
      "type": "object",
      "properties": {
        "local_path": {"type": "string", "description": "Absolute path to the repo"},
        "level": {"type": "integer", "enum": [1, 2, 3], "default": 3},
        "output_format": {"type": "string", "enum": ["markdown", "json"], "default": "json"}
      },
      "required": ["local_path"]
    }
  }
}
```

Additional tools available to Claude via MCP (`list_available_checks`, `confirm_project_data`) are OMITTED for MVP -- the skill's primary path is a single audit call.

**Rationale**: Minimal surface -- the diagnostic value is whether the model faithfully reports what one audit call returned. Adding tools not needed for the primary journey inflates the SDK-call cost per fixture without adding parity signal.

**Alternatives considered**:
- Register every darnit MCP tool: rejected as scope creep.
- Auto-generate schemas from the Python function signatures via `inspect`: rejected -- too much machinery for a two-line hand-authored schema.

## R5. Turn-cap-exhausted outcome semantics

**Decision**: The runner and differ recognize a new `SkillInvocationResult.turn_cap_exhausted: bool = False` field. When True:

- `run.py` reports `outcome = "turn_cap_exhausted"`.
- Aggregate exit code = 5 (per Q3 clarify + FR-010).
- `diff_report.md` explicitly reads: `"FAIL: model exhausted its turn cap ({max_turns}) without emitting a final message. This is DISTINCT from unparseable output -- the assistant kept calling tools instead of summarizing."`
- The final assistant message field is empty; the raw tool-call transcript is NOT captured (privacy + noise; not needed to diagnose "model didn't converge").

Diff outcome ordering (most severe first): `SKILL_UNPARSEABLE` (2) > `TURN_CAP_EXHAUSTED` (5) > `PER_CONTROL_DISAGREE` (1) > `COUNTS_DISAGREE` (1) > `SUCCESS` (0). Exit-code order doesn't have to match severity -- 5 slots in alongside the existing 0-4.

**Rationale**: A distinct outcome makes debugging obvious. Exit code 5 doesn't collide with 4 (rate-limit) so a CI grep for "exit 5" is unambiguous.

**Alternatives considered**:
- Lump into `errored`: rejected in clarify Q3 (option D).
- Include the tool-call transcript in the diff report: rejected -- noise, potential leak surface, and not needed for the runbook.

## R6. Workflow structure + Environment configuration

**Decision**: `.github/workflows/parity-tier2-openai.yml` mirrors feature 028's `parity-tier2.yml`:

- `on: workflow_dispatch:` with inputs `fixture_glob` (default `"*"`) AND `model` (default `gpt-4o-2024-08-06`).
- `environment: parity-tier2-openai` (distinct from feature 028's `parity-tier2`).
- `permissions: contents: read`.
- Preflight audit step logs actor + SHA + fixture_glob + selected model to `$GITHUB_STEP_SUMMARY` BEFORE the SDK step.
- SDK step consumes `OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}` (Environment-scoped secret, NOT repo-level).
- `actions/upload-artifact@v4` with `if: always()` uploads `parity-artifacts/`.

Environment configuration (in GitHub UI, not YAML):
- Required-reviewer list authorized to approve OpenAI-cost runs.
- `OPENAI_API_KEY` stored at the Environment level.
- No other secrets in this Environment (avoids blast radius if compromised).

**Rationale**: Parallel to feature 028; two Environments give per-provider accountability.

**Alternatives considered**:
- One workflow with a `provider` input: rejected -- one Environment would have to hold BOTH keys, or the workflow would have to switch Environments dynamically (which GitHub doesn't support cleanly). Per-provider workflows are cleaner.

## R7. Fixture corpus and artifact path per provider

**Decision**: Both workflows write to `parity-artifacts/<fixture_name>/`. Feature 028's Claude workflow overwrites Claude-specific files; feature 029's OpenAI workflow overwrites OpenAI-specific files. To keep them from stomping, we introduce a `openai_final_message.md` filename for the OpenAI adapter's output vs `skill_final_message.md` for Claude's (feature 028's original name).

Concretely, `artifact_writer.py` is extended to accept a `provider` parameter that determines the filename of the "final message" artifact:

- Claude: `skill_final_message.md` (feature 028's name preserved for backwards compat with any existing analysis scripts).
- OpenAI: `openai_final_message.md`.

Other files (`mcp_tool_result.json`, `diff_report.md`, `metadata.json`) are provider-neutral and are overwritten on subsequent dispatches of the same provider.

**Rationale**: Same fixture path, per-provider filename. A local script diffing across providers reads both filenames from the same directory.

**Alternatives considered**:
- Provider-subdirectory (`parity-artifacts/<fixture>/<provider>/`): cleaner separation but requires updating feature 028's existing artifact-shape docs and might churn analysis scripts. Deferred.
- Two entirely separate artifact roots: rejected -- inflates artifact-storage overhead in CI.

## R8. Model-pin verification (SC-010)

**Decision**: The workflow-config test (extending `test_workflow_config.py` from feature 028) adds an assertion:

```python
def test_openai_workflow_pins_versioned_model():
    workflow = yaml.safe_load(open(".github/workflows/parity-tier2-openai.yml"))
    inputs = _get_dispatch_inputs(workflow)
    default_model = inputs["model"]["default"]
    # Match either date-suffix (gpt-4o-2024-08-06) or explicit version tag (gpt-4o.1)
    assert re.match(r"^[a-z0-9\-]+-\d{4}-\d{2}-\d{2}$", default_model) or \
           re.match(r"^[a-z0-9\-]+\.\d+$", default_model), \
           f"OpenAI model default {default_model!r} must be a versioned pin, not a moving alias"
```

**Rationale**: Two version-shape families cover OpenAI's naming (`gpt-4o-2024-08-06` for date-suffixed models, `gpt-4o.1` if OpenAI later moves to semver-style). A moving alias like `gpt-4o` fails both patterns and thus fails the test.

**Alternatives considered**:
- A hard-coded list of known-valid strings: rejected -- would fail every time OpenAI ships a new dated model.
- Regex against a schema doc: rejected as more machinery than the invariant needs.

## R9. Adversarial-test mocking strategy

**Decision**: The OpenAI backend's tests mock `openai.AsyncOpenAI` at the module level using `unittest.mock.patch`. Test cases construct canned `ChatCompletion`-shaped responses. Because the SDK's response objects are Pydantic models with well-defined fields, the tests use minimal `SimpleNamespace`-style stubs rather than importing the SDK's response types.

For SC-011 (turn-cap exhausted), the mock returns responses that always emit tool_calls, never a text message, so the loop runs for `max_turns` iterations and hits the cap.

**Rationale**: Fine-grained control over API responses; no live network. Tests run in <1 second per case.

**Alternatives considered**:
- `respx` or `vcrpy` for HTTP-level mocking: rejected -- more setup for equivalent outcome; SDK-level mocking is closer to what we care about.
- Use OpenAI's official test helpers (if any): unclear whether they exist; not necessary for the adversarial cases we care about.

## R10. Interaction with feature 028's stacked-PR reality

**Decision**: Feature 029 is stacked on feature 028 (which is stacked on feature 026). Rebase order once ancestors merge:

1. #365 (feature 026 + Stage 1 substrate) merges to `main`.
2. #367 (feature 027, sibling to 028) merges. Order between #367 and #370 (feature 028) doesn't matter; they're independent siblings on 026.
3. #370 (feature 028) merges.
4. This feature's PR (#371, say) rebases to `main` after #370 lands. Its diff collapses to just feature 029.

If reviews on the ancestor PRs surface changes to the Tier 2 machinery (e.g., someone requests a rename of `claude_agent_sdk_client.py`), feature 029's refactor plan absorbs those changes on rebase.

**Rationale**: Documented for clarity. The plan phase can't predict every rebase surprise; the property that matters is that feature 029's refactor of `claude_agent_sdk_client.py` is small and reviewable in isolation.

**Alternatives considered**:
- Wait for #370 to merge before starting 029: rejected by user instruction ("assume it'll get merged").
- Fork 028's client without touching it: rejected -- forgoes the shared Protocol seam that's the whole point of extracting the abstraction.

## Summary of Phase 0 outcome

- Every technical unknown for Phase 1 has a concrete decision above.
- No new production dependencies. `openai>=1.50` is a workspace dev-group addition only.
- Governance property (SC-002) mirrors feature 028's SC-005a for the OpenAI key.
- SC-010 (pinned model) enforceable via a regex-based workflow config test.
- SC-011 (turn cap exhausted) exit code 5 slots into the existing 0-4 exit-code table with no collision.
- Refactor of feature 028's Claude client preserves import compatibility via a shim module.
- Fixture corpus, skill prompt snapshot, and `Tier2DiffReport` shape from feature 028 are reused verbatim (only `provider` filename argument added to `artifact_writer.py`).
