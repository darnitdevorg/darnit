# Phase 1 Data Model: OpenAI Tier 2 Parity Adapter

**Feature**: 029-openai-parity-adapter | **Date**: 2026-08-10

All entities are TEST-side only. No product data model changes.

## 1. `SkillInvocationBackend` (Protocol)

Module: `tests/darnit/parity/tier2/backends/base.py`

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
        """Raise SetupError if the provider's credentials are absent."""
        ...
```

**Conformance verified by**: SC-005 test (`test_backend_protocol_conformance.py`) enumerates every entry in `BACKEND_REGISTRY` and asserts `isinstance(instance, SkillInvocationBackend)`.

**Alternative Protocol shape rejected**: an `abc.ABC` subclass was considered but rejected in R1 -- Protocol is more Pythonic for duck-typed adapters.

## 2. `SkillInvocationResult`

Module: `tests/darnit/parity/tier2/backends/base.py`

```python
@dataclass(frozen=True)
class SkillInvocationResult:
    final_message: str
    model: str
    turn_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    turn_cap_exhausted: bool = False  # NEW in feature 029
```

Feature 028's Claude adapter returned this same dataclass minus `turn_cap_exhausted`. Adding the field with a default preserves backwards compat: Claude adapter continues to construct results without setting it; runner treats absence as False.

**Validation rules**: None at the dataclass level. `turn_count` MUST be non-negative but not enforced by validators (test-side; frozen dataclass suffices).

## 3. `SetupError`

Module: `tests/darnit/parity/tier2/backends/base.py`

```python
class SetupError(RuntimeError):
    """Raised when a backend lacks the credentials/env it needs to invoke."""
```

Same class from feature 028's `claude_agent_sdk_client.py`; moved to `backends/base.py` and re-exported at the old path for backwards compat. `check_env()` classmethods raise this. `run.py` catches it and returns exit code 3 (setup).

## 4. `BACKEND_REGISTRY`

Module: `tests/darnit/parity/tier2/backends/__init__.py`

```python
from .base import SkillInvocationBackend, SkillInvocationResult, SetupError
from .claude_agent_sdk import ClaudeAgentSdkBackend
from .openai_backend import OpenAIBackend
from .noop import NoopBackend

BACKEND_REGISTRY: dict[str, type[SkillInvocationBackend]] = {
    "claude_agent_sdk": ClaudeAgentSdkBackend,
    "openai": OpenAIBackend,
    # NoopBackend intentionally not registered here -- tests inject it.
}
```

**Lifecycle**: module-level. Cheap; no lazy loading. `openai` imports its SDK at module load time; if `openai` isn't installed, the registry itself fails to import -- this is fine because Tier 2 is a dev-dep-required test surface.

**Test injection**: `run.py` accepts an optional `backends: dict[str, ...]` parameter that overrides `BACKEND_REGISTRY` for that invocation. Tests use this to inject `NoopBackend` without touching the module dict.

## 5. `ClaudeAgentSdkBackend` (refactored)

Module: `tests/darnit/parity/tier2/backends/claude_agent_sdk.py`

Refactor of feature 028's `claude_agent_sdk_client.py::invoke_skill` into a class:

```python
class ClaudeAgentSdkBackend:
    name = "claude_agent_sdk"

    @classmethod
    def check_env(cls) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SetupError(...)

    async def invoke(
        self, fixture_dir: Path, model: str, max_turns: int,
    ) -> SkillInvocationResult:
        # Body is feature 028's invoke_skill() logic, unchanged.
        ...
```

**Backwards-compat shim** at `tests/darnit/parity/tier2/claude_agent_sdk_client.py`:

```python
"""Backwards-compat re-export shim; superseded by
`tests/darnit/parity/tier2/backends/claude_agent_sdk.py`. Kept as an import
path for one release cycle so existing feature-028 tests continue to work
without an update."""

from tests.darnit.parity.tier2.backends.base import (
    SetupError,
    SkillInvocationResult,
)
from tests.darnit.parity.tier2.backends.claude_agent_sdk import (
    ClaudeAgentSdkBackend,
)


async def invoke_skill(fixture_dir, model="anthropic:claude-sonnet-5", max_turns=20):
    """Deprecated: use ClaudeAgentSdkBackend.invoke() directly."""
    return await ClaudeAgentSdkBackend().invoke(fixture_dir, model, max_turns)


__all__ = ("SetupError", "SkillInvocationResult", "invoke_skill")
```

## 6. `OpenAIBackend` (new)

Module: `tests/darnit/parity/tier2/backends/openai_backend.py`

```python
class OpenAIBackend:
    name = "openai"

    @classmethod
    def check_env(cls) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise SetupError(
                "Tier 2 OpenAI backend requires OPENAI_API_KEY. "
                "Configure the `parity-tier2-openai` GitHub Environment or export "
                "the var for a local run.",
            )

    async def invoke(
        self, fixture_dir: Path, model: str, max_turns: int,
    ) -> SkillInvocationResult:
        # See research.md R3 for the loop shape.
        # See R4 for the tool schema.
        # Uses openai.AsyncOpenAI + client.chat.completions.create(...).
        ...
```

**Model default**: The backend does NOT default the model; the CALLER (`run.py` or the workflow YAML) supplies it. The workflow pins `gpt-4o-2024-08-06`; `run.py --model <name>` can override for local dev.

**Temperature**: `temperature=0.0` for reproducibility.

**Tool schemas**: See section 8.

## 7. `NoopBackend` (test fixture)

Module: `tests/darnit/parity/tier2/backends/noop.py`

```python
class NoopBackend:
    """Test-only backend used by SC-005 (Protocol conformance) and SC-007
    (extensibility). NOT registered in BACKEND_REGISTRY by default; tests
    inject it explicitly.
    """

    name = "noop"

    @classmethod
    def check_env(cls) -> None:
        # No credentials required.
        return None

    async def invoke(
        self, fixture_dir: Path, model: str, max_turns: int,
    ) -> SkillInvocationResult:
        return SkillInvocationResult(
            final_message="# noop backend\n\nPassed: 0\nFailed: 0",
            model=model,
            turn_count=0,
            metadata={"backend": "noop"},
        )
```

**Not shipped as a template**: real backend authors read `contracts/skill-invocation-backend-protocol.md`, not this class.

## 8. Tool schema for `audit_openssf_baseline`

Module: `tests/darnit/parity/tier2/backends/openai_backend.py` (module-level constant)

```python
_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "audit_openssf_baseline",
            "description": (
                "Run darnit's OpenSSF Baseline audit on the repository at the "
                "given local_path. Returns a JSON string with per-control results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "local_path": {
                        "type": "string",
                        "description": "Absolute path to the repository being audited.",
                    },
                    "level": {
                        "type": "integer",
                        "enum": [1, 2, 3],
                        "default": 3,
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["markdown", "json"],
                        "default": "json",
                    },
                },
                "required": ["local_path"],
            },
        },
    },
]
```

**Dispatch**:

```python
def _dispatch_tool_call(call, fixture_dir):
    if call.function.name == "audit_openssf_baseline":
        args = json.loads(call.function.arguments)
        # Force local_path to the fixture_dir; ignore the model's suggestion
        # to prevent it from wandering outside the fixture.
        args["local_path"] = str(fixture_dir)
        return audit_openssf_baseline(**args)
    return f"unknown tool: {call.function.name}"
```

## 9. Runner extension (`run.py` update)

- Add `--backend <name>` argument, default `claude_agent_sdk`.
- Add `--model <name>` argument (both backends accept this; each backend's workflow YAML supplies its provider-appropriate pinned default).
- Add `--max-turns <int>` argument, default 20.
- Handle new outcome `turn_cap_exhausted` in the exit-code aggregation (exit 5).

**`_run_skill()`** replaced by:

```python
async def _run_skill(fixture_dir, backend_name, model, max_turns, dry_run):
    if dry_run:
        return SkillInvocationResult(final_message=_DRY_RUN_STUB, model="dry-run", turn_count=0, metadata={"dry_run": True})
    backend_cls = BACKEND_REGISTRY[backend_name]
    backend_cls.check_env()  # fail fast if credentials absent
    backend = backend_cls()
    return await backend.invoke(fixture_dir, model, max_turns)
```

## 10. `artifact_writer` provider extension

Module: `tests/darnit/parity/tier2/artifact_writer.py`

Add optional `provider` parameter:

```python
def write_fixture_artifacts(
    artifact_root, fixture_name, mcp_json, skill_markdown, diff_md,
    metadata=None, provider: str = "claude",
):
    fixture_dir = artifact_root / fixture_name
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "mcp_tool_result.json").write_text(mcp_json)

    # Provider-specific filename for the final message artifact.
    final_message_name = (
        "skill_final_message.md" if provider == "claude"
        else f"{provider}_final_message.md"
    )
    (fixture_dir / final_message_name).write_text(skill_markdown)
    (fixture_dir / "diff_report.md").write_text(diff_md)
    ...
```

## 11. State transitions

Feature 029 introduces no persistent state. All state is per-run in memory. The `turn_cap_exhausted` bool moves through:

```
Backend loop starts (turn=0)
  |
  v
Turn N (N < max_turns): model returns tool_call -> execute tool, append result, continue
  |
  v
Turn N: model returns text content -> return SkillInvocationResult(turn_cap_exhausted=False)
  |
  v
Turn N == max_turns: loop exits without text -> return SkillInvocationResult(turn_cap_exhausted=True, final_message="")
  |
  v
runner.py sees turn_cap_exhausted=True -> outcome="turn_cap_exhausted" -> exit code 5
```

Nothing persists between runs.
