# Quickstart: OpenAI Tier 2 Parity Adapter

**Feature**: 029-openai-parity-adapter | **For**: authorized maintainers dispatching an OpenAI Tier 2 parity check, and future authors adding a third-provider backend adapter.

## Dispatching the OpenAI Tier 2 workflow

Tier 2 is manual-dispatch only. An authorized maintainer approves each run.

```bash
gh workflow run parity-tier2-openai.yml \
  --repo darnitdevorg/darnit \
  -f fixture_glob="*" \
  -f model="gpt-4o-2024-08-06"
```

Or via GitHub UI:

1. Actions -> "Parity Tier 2 (OpenAI)" -> Run workflow.
2. Pick fixture glob (default `"*"`).
3. Optionally override the model (default is the pinned version-suffixed default).
4. Click "Run workflow."
5. Wait for the approval-required badge to appear on the run.
6. An authorized reviewer approves the deployment to `parity-tier2-openai`.
7. The workflow proceeds; `OPENAI_API_KEY` is injected only into the SDK-invocation step.

### Reviewer approval checklist

Before clicking Approve:

- Confirm the dispatcher (github.actor) is authorized.
- Confirm the `model` input is a version-suffixed pin, not a moving alias.
- Confirm the `fixture_glob` matches the intended scope.
- Confirm the workflow YAML has not been modified in the same PR as an unrelated feature (governance red flag).

### Interpreting the exit code

| Exit code | Meaning |
|---|---|
| 0 | Success -- OpenAI backend agrees with tool on every control per fixture |
| 1 | Per-control disagreement or count disagreement |
| 2 | Skill output unparseable |
| 3 | Setup error (missing `OPENAI_API_KEY`) |
| 4 | Rate limit exhausted |
| 5 | Turn cap exhausted (model kept calling tools, never summarized) |

### Reviewing artifacts locally

```bash
gh run download --repo darnitdevorg/darnit <run-id>
cd parity-artifacts/mixed_repo/
cat mcp_tool_result.json | jq '.results[] | {id, status}'
cat openai_final_message.md          # OpenAI backend's final message
cat skill_final_message.md           # Claude backend's final message (if a Claude dispatch also ran)
cat diff_report.md
```

## Adding a new backend (Gemini, xAI, self-hosted, etc.)

The Protocol seam is designed so a third-party backend needs only three additions and zero edits to shared modules.

### Step 1: Write the backend class

```python
# tests/darnit/parity/tier2/backends/my_provider.py

from pathlib import Path
from tests.darnit.parity.tier2.backends.base import (
    SetupError,
    SkillInvocationResult,
)


class MyProviderBackend:
    name = "my_provider"

    @classmethod
    def check_env(cls) -> None:
        import os
        if not os.environ.get("MY_PROVIDER_API_KEY"):
            raise SetupError(
                "Tier 2 my_provider backend requires MY_PROVIDER_API_KEY.",
            )

    async def invoke(
        self, fixture_dir: Path, model: str, max_turns: int,
    ) -> SkillInvocationResult:
        # Your provider-specific invocation loop.
        # See backends/openai_backend.py for a reference implementation.
        ...
```

### Step 2: Register in `BACKEND_REGISTRY`

```python
# tests/darnit/parity/tier2/backends/__init__.py

from .my_provider import MyProviderBackend

BACKEND_REGISTRY = {
    "claude_agent_sdk": ClaudeAgentSdkBackend,
    "openai": OpenAIBackend,
    "my_provider": MyProviderBackend,  # <- new line
}
```

### Step 3: Add a workflow file

Copy `.github/workflows/parity-tier2-openai.yml` to `.github/workflows/parity-tier2-my-provider.yml` and:

- Change `environment: parity-tier2-openai` -> `environment: parity-tier2-my-provider`.
- Change `OPENAI_API_KEY` -> `MY_PROVIDER_API_KEY` in the SDK step's `env:` block.
- Change `--backend openai` -> `--backend my_provider` in the runner invocation.
- Pin the model default to a versioned string appropriate for the provider.

Configure the new Environment in GitHub UI with a reviewer list and the provider's API key.

### Step 4: Verify

- `test_backend_protocol_conformance.py` will automatically include your backend on next test run (it iterates `BACKEND_REGISTRY`).
- Add adversarial tests in a new file `tests/darnit/parity/tier2/test_my_provider_backend_adversarial.py` following the shape of `test_openai_backend_adversarial.py`.
- Extend `test_workflow_config.py` with an entry for `parity-tier2-my-provider.yml` mirroring the OpenAI assertions.

**No changes required to**: `run.py`, `diff.py`, `skill_markdown_parser.py`, `artifact_writer.py`, `skill_prompt_snapshot.md`, any fixture. This is SC-007 by construction.

## Local development against the OpenAI backend

```bash
# Dry-run first (no API call; canned response).
uv run python -m tests.darnit.parity.tier2.run \
  --backend openai \
  --fixture-glob "all_pass_repo" \
  --dry-run

# Real run (requires OPENAI_API_KEY export).
export OPENAI_API_KEY="sk-..."
uv run python -m tests.darnit.parity.tier2.run \
  --backend openai \
  --fixture-glob "all_pass_repo" \
  --model gpt-4o-2024-08-06 \
  --max-turns 20 \
  --artifact-dir /tmp/parity-dev
```

Expected artifact layout on success:

```
/tmp/parity-dev/
+-- all_pass_repo/
    +-- mcp_tool_result.json
    +-- openai_final_message.md
    +-- diff_report.md
    +-- metadata.json
```

## Test suite

```bash
# Offline tests only (no API):
uv run pytest tests/darnit/parity/tier2/ -q

# Full Tier 2 workspace:
uv run pytest tests/darnit/parity/ -q
```

Expected test count after feature 029 lands: feature-028 baseline + about 10-15 new tests (Protocol conformance + OpenAI adversarial + turn-cap-exhausted + workflow config).

## Cross-provider drift comparison (US3)

Once both Claude and OpenAI Tier 2 workflows have run against the same commit, a maintainer can locally diff their final messages to see where the two providers agree or disagree.

```bash
# 1. Download both artifact bundles.
gh run download --repo darnitdevorg/darnit <claude-run-id>
mv parity-artifacts parity-artifacts-claude

gh run download --repo darnitdevorg/darnit <openai-run-id>
mv parity-artifacts parity-artifacts-openai

# 2. Run the aggregate script.
uv run python -m tests.darnit.parity.tier2.scripts.aggregate_provider_diff \
    --claude-artifacts parity-artifacts-claude \
    --openai-artifacts parity-artifacts-openai
```

Output is one Markdown table per fixture with columns `control_id | claude_status | openai_status | disagreement`. Exit codes: 0 success, 1 no fixtures found, 2 missing arguments. Not invoked by CI -- a local maintainer runs it when investigating provider drift.

## Related follow-ups

- **Issue #369**: Add scheduled cadence + governance-appropriate key sourcing (applies to Claude AND OpenAI workflows; a single follow-up covers both).
- **Future features** for additional providers: Gemini, xAI, self-hosted -- each is a fresh feature reusing the Protocol.
