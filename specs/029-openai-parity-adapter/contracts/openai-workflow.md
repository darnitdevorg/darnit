# Contract: `parity-tier2-openai.yml` Workflow

**Feature**: 029-openai-parity-adapter | **Consumers**: maintainers configuring the `parity-tier2-openai` Environment; reviewers approving OpenAI dispatches; auditors verifying access-control compliance.

Mirrors feature 028's `parity-tier2.yml` contract (`tier2-workflow.md`) for the OpenAI backend. Governance-critical properties are enforced identically.

## 1. Trigger

- **OW-1**: Triggered EXCLUSIVELY by `workflow_dispatch`. No `push`, no `pull_request`, no `schedule`.
- **OW-2**: Inputs: `fixture_glob` (default `"*"`) AND `model` (default `gpt-4o-2024-08-06` -- SC-010 requires a version-suffixed default).
- **OW-3**: The `model` input's default MUST be a version-suffixed string. A moving alias (e.g., `gpt-4o` alone) fails the `test_openai_workflow_pins_versioned_model` check (SC-010).

## 2. Environment

- **OW-4**: Job MUST declare `environment: parity-tier2-openai`. Distinct from feature 028's `parity-tier2`.
- **OW-5**: GitHub UI (NOT this YAML) MUST configure the `parity-tier2-openai` Environment with:
  - A required-reviewer list of authorized maintainers.
  - `OPENAI_API_KEY` stored at the ENVIRONMENT level.
  - No other secrets in this Environment (blast-radius minimization).

## 3. Permissions

- **OW-6**: `permissions: contents: read` at the job level. No `write` scope granted to any resource.

## 4. Key exclusivity

- **OW-7**: No other workflow references `secrets.OPENAI_API_KEY`. Verifiable by `test_workflow_config.py::test_openai_key_only_in_openai_workflow` (SC-002).
- **OW-8**: `OPENAI_API_KEY` does NOT appear in the `parity-tier2.yml` file (feature 028's Claude workflow).
- **OW-9**: `ANTHROPIC_API_KEY` does NOT appear in `parity-tier2-openai.yml`. The two workflows have exclusive per-provider keys.

## 5. Preflight audit

- **OW-10**: A preflight step MUST log actor + SHA + fixture_glob + selected model to `$GITHUB_STEP_SUMMARY` BEFORE the SDK-invocation step consumes `OPENAI_API_KEY`.

## 6. Runner invocation

- **OW-11**: The SDK step invokes `uv run python -m tests.darnit.parity.tier2.run --backend openai --fixture-glob <glob> --model <model>`.
- **OW-12**: The step's `env:` block sets `OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}`.
- **OW-13**: `ANTHROPIC_API_KEY` is NOT set in the step's `env:` block. This is enforced by an assertion in `test_workflow_config.py` that greps `parity-tier2-openai.yml` for `ANTHROPIC_API_KEY` and asserts the count is zero.

## 7. Artifact upload

- **OW-14**: `actions/upload-artifact@v4` runs with `if: always()` so failure artifacts land on any exit code.
- **OW-15**: Upload path is `parity-artifacts/`, same as feature 028. The OpenAI backend writes `openai_final_message.md` per fixture (distinct filename from feature 028's `skill_final_message.md`) so both providers' artifacts can coexist under the same fixture directory across dispatches.

## 8. Exit codes

- **OW-16**: Runner exit codes for OpenAI backend match the extended set from feature 028 + feature 029:
  - `0` -- success
  - `1` -- per_control_disagree or counts_disagree
  - `2` -- skill_unparseable
  - `3` -- setup (missing `OPENAI_API_KEY`)
  - `4` -- rate limit
  - `5` -- turn_cap_exhausted (NEW in feature 029)

## 9. Rate limit handling

- **OW-17**: The runner MUST NOT retry API calls automatically on rate limit. Same policy as feature 028's Claude workflow.

## 10. Reviewer checklist

Before approving a dispatch of `parity-tier2-openai.yml`, the reviewer verifies:

- The dispatcher (github.actor) is listed on the workflow run and matches an authorized maintainer.
- The `fixture_glob` input matches the intended investigation scope (`"*"` for full-corpus check, a specific fixture name for targeted debugging).
- The `model` input either uses the workflow's pinned default OR is an explicitly overridden version-suffixed string. If a moving alias (e.g., `gpt-4o`) is in the model input, decline the approval and instruct the dispatcher to specify a versioned model.
