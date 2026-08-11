# Contract: `SkillInvocationBackend` Protocol

**Feature**: 029-openai-parity-adapter | **Consumers**: authors of future Tier 2 provider adapters (Gemini, xAI, self-hosted). Also consumed by `run.py` and by Protocol-conformance tests.

## 1. Shape

```python
@runtime_checkable
class SkillInvocationBackend(Protocol):
    name: str

    async def invoke(
        self,
        fixture_dir: Path,
        model: str,
        max_turns: int,
    ) -> SkillInvocationResult:
        ...

    @classmethod
    def check_env(cls) -> None:
        ...
```

- **B-1**: A backend MUST expose a class-level or instance-level `name: str` attribute. Convention: snake_case, provider-name-first (e.g., `claude_agent_sdk`, `openai`, `gemini_generative_ai`).
- **B-2**: A backend MUST expose an async `invoke(fixture_dir, model, max_turns) -> SkillInvocationResult`. Model and max_turns are supplied by the runner (from CLI flags or workflow YAML); backends do NOT default them.
- **B-3**: A backend MUST expose `check_env()` as a classmethod so the runner can fail fast on missing credentials WITHOUT constructing an instance. `check_env()` raises `SetupError` (imported from `backends.base`) with a message identifying the missing environment variable(s).
- **B-4**: A backend MAY expose additional attributes/methods; the runner ignores them.
- **B-5**: `isinstance(instance, SkillInvocationBackend)` MUST return True for any conforming class instance (this is the SC-005 test target).

## 2. `SkillInvocationResult` contract

- **B-6**: `invoke()` returns a `SkillInvocationResult` frozen dataclass with the fields defined in `data-model.md` section 2. All new backends MUST populate `final_message`, `model`, `turn_count`, and `metadata` (may be empty dict).
- **B-7**: `turn_cap_exhausted: bool` MUST be True iff the model exhausted the turn cap without emitting a final text message. Backends where the concept of "turn cap" doesn't apply (e.g., a synchronous single-call backend) always set it False.
- **B-8**: `final_message` MUST be the string the parser will consume. Empty string is a legal value only when `turn_cap_exhausted=True`.

## 3. Registration

- **B-9**: A new backend registers itself in `tests/darnit/parity/tier2/backends/__init__.py` by adding an entry to `BACKEND_REGISTRY`:

    ```python
    BACKEND_REGISTRY = {
        "claude_agent_sdk": ClaudeAgentSdkBackend,
        "openai": OpenAIBackend,
        "my_new_provider": MyNewProviderBackend,  # <- adds here
    }
    ```

- **B-10**: This is a TEST-ONLY registration mechanism. Entry-point-based discovery is EXPLICITLY OUT OF SCOPE for this Protocol (clarify Q2 established this).

## 4. Credentials + env

- **B-11**: `check_env()` MUST NOT make any network call; it only inspects environment variables (or, for a self-hosted backend, whatever local resource identifies "credentials present").
- **B-12**: `check_env()` SHOULD be idempotent -- callable arbitrarily many times.
- **B-13**: If a backend's credentials are ABSENT, `check_env()` MUST raise `SetupError` naming the missing variable(s). The runner catches this and returns exit code 3.

## 5. Turn count + budget

- **B-14**: `max_turns` is the CALLER's contract with the backend. The backend MUST NOT exceed it. Exceeding is a bug (specifically, it would break the "runaway budget" governance property).
- **B-15**: `turn_count` in the returned result MUST equal the number of assistant turns actually taken.

## 6. Tool invocation

- **B-16**: A backend that supports tool calls MUST invoke the darnit MCP tools (specifically `audit_openssf_baseline`) by calling their Python functions directly. The backend does NOT go through an MCP protocol wrapper.
- **B-17**: The backend MUST force `local_path` to the `fixture_dir` argument on every tool call, to prevent a rogue model from wandering outside the fixture.

## 7. Prompt

- **B-18**: All backends consume the same skill prompt snapshot at `tests/darnit/parity/tier2/skill_prompt_snapshot.md`. Backends do NOT fork this file. Provider-specific transformations (e.g., prepending tool-choice guidance for a model that needs it) live in the backend's own module.

## 8. Reproducibility

- **B-19**: Backends SHOULD use `temperature=0.0` or the provider's equivalent low-variance setting when the API exposes it. This isn't strictly enforceable across all providers but is expected behavior.
- **B-20**: Backends MUST NOT introduce random behavior (no `random.random()` calls, no `time`-based seeding). Two invocations against the same fixture with the same model SHOULD produce byte-identical `final_message` output.

## 9. Backwards compatibility

- **B-21**: Feature 029 introduces the Protocol. Feature 028's Claude adapter is refactored to satisfy it; the old import path `tests.darnit.parity.tier2.claude_agent_sdk_client` remains via a shim. Third parties adding a backend after 029 do NOT need to touch feature 028's or feature 029's existing files -- they add a new module and register it in `BACKEND_REGISTRY`.

## 10. Non-goals

- **B-22**: This Protocol is NOT a general-purpose "abstract over LLM providers" abstraction. It's specifically for Tier 2 skill-drift measurement. Product code (harness, MCP tools, etc.) does NOT consume it.
- **B-23**: The Protocol does NOT include streaming, cost tracking, or usage aggregation. Those are backend-internal concerns.
