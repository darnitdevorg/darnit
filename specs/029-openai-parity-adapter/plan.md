# Implementation Plan: OpenAI Tier 2 Parity Adapter

**Branch**: `029-openai-parity-adapter` | **Date**: 2026-08-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/029-openai-parity-adapter/spec.md` (with 5 clarifications from `/speckit-clarify` on 2026-08-10: OpenAI Chat Completions API with hand-rolled tool loop; factory-dict registry; `turn_cap_exhausted` outcome + exit 5; pinned version-suffixed model default; `NoopBackend` as test-only fixture).

## Summary

Adds a second Tier 2 provider adapter to feature 028's parity test suite. Extracts a `SkillInvocationBackend` Protocol during the refactor so both the existing Claude adapter (from feature 028) and the new OpenAI adapter satisfy the same shape. A backend factory dict + `--backend <name>` CLI flag select which adapter runs per dispatch.

Ships:
- **`SkillInvocationBackend` Protocol** (`tests/darnit/parity/tier2/backends/base.py`): async `invoke(fixture_dir) -> SkillInvocationResult` + `check_env() -> None` + `name: str`. `@runtime_checkable`.
- **Claude adapter refactor**: existing `claude_agent_sdk_client.py` moves to `backends/claude_agent_sdk.py` and is refactored to a class satisfying the Protocol. Zero behavior change; the existing `invoke_skill()` function becomes a class method.
- **OpenAI adapter** (`backends/openai_backend.py`): Chat Completions API loop; darnit MCP tools registered as function-callable `tools=[...]`; caps at 20 turns by default; returns `SkillInvocationResult`.
- **Runner update** (`run.py`): `--backend <name>` flag; looks up `BACKEND_REGISTRY[name]`; unchanged runner behavior for `--backend claude_agent_sdk` (default preserves feature 028).
- **OpenAI-specific workflow** (`.github/workflows/parity-tier2-openai.yml`): manual-dispatch only, `environment: parity-tier2-openai` (separate from feature 028's `parity-tier2`), `OPENAI_API_KEY` at Environment level, pinned model default `gpt-4o-2024-08-06`.
- **New failure class**: `turn_cap_exhausted` outcome + exit code 5.
- **NoopBackend fixture**: `backends/noop.py`; used by conformance and extensibility tests only.

Closes #368. Zero product-package changes -- feature 028's `test_no_product_changes.py` guard already covers `packages/*/src/` and it stays untouched.

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets, unchanged).

**Primary Dependencies (new -- test-side only)**:
- `openai>=1.50` (Anthropic-agnostic OpenAI Python SDK, version pinned to a range that includes the current Chat Completions surface with tool-calling). Added to workspace-level `pyproject.toml` dev group, alongside feature 028's `claude-agent-sdk`. TEST-ONLY per SC-006.
- No new stdlib usage beyond what feature 028 already touched.

**Primary Dependencies (in use)**: `pytest`, `PyYAML` (already a workspace dep for workflow-config tests), `claude-agent-sdk` (from feature 028), feature 028's own modules: `AuditResult`, `SkillReport`, `Tier2DiffReport`, `write_fixture_artifacts`.

**Storage**: Filesystem only. Fixture corpus reused from feature 028 unchanged. Artifact bundles land at `parity-artifacts/<fixture_name>/` per-provider; different workflow dispatches (Claude vs OpenAI) can share the same artifact path (each dispatch overwrites) or write to distinct subdirs -- plan-phase detail below.

**Testing**: pytest for offline tests (Protocol conformance, backend adversarial, workflow config). No live API calls in the test suite. Adversarial cases mock the `openai` client at the module level.

**Target Platform**: `ubuntu-latest` GitHub-hosted runner for the workflow; any host for local development.

**Project Type**: Test-suite addition. No product-package code changes.

**Performance Goals**: SC-009 -- full corpus (4-6 fixtures) in under 30 minutes. Per fixture: capped by 20-turn budget * per-turn latency (5-30s) + audit cost (a few seconds). Realistic upper bound per fixture: ~10 minutes. Corpus: ~40 minutes worst case, ~15 minutes typical.

**Constraints**:
- **SC-006 preservation**: no dep additions to `packages/darnit/pyproject.toml` or `packages/darnit-baseline/pyproject.toml`. Enforced by feature 028's `test_no_product_changes.py`.
- **SC-002 (FR-007)**: `OPENAI_API_KEY` MUST appear only in `parity-tier2-openai.yml`. Verifiable by iterating `.github/workflows/*.yml` and asserting `OPENAI_API_KEY` literal count is exactly 1 (in the OpenAI workflow file). Mirror of feature 028's SC-005a for `ANTHROPIC_API_KEY`.
- **SC-010**: model default in the workflow YAML MUST match a version-suffixed pattern (e.g., `gpt-4o-2024-08-06`). Moving aliases (`gpt-4o` alone) fail the workflow-config test.
- **Stateless per-invocation** (FR-001): no persistent thread/assistant objects.
- **FR-009**: shared skill prompt snapshot with feature 028. No fork; adapter-side transformation for OpenAI's tool-call syntax if the SDK requires it.

**Scale/Scope**: MVP is the Protocol seam + OpenAI adapter + governance-gated workflow + adversarial tests. Expected size: ~600-800 lines net production (backend adapters + Protocol module + runner update) + ~500 lines tests + one workflow YAML + one contract doc.

## Constitution Check

Constitution v1.3.0. Five Core Principles evaluated as gates.

| Principle | Applicable? | Verdict | Rationale |
|-----------|-------------|---------|-----------|
| I. Plugin Separation | Yes | PASS | The Protocol + backends live under `tests/darnit/parity/tier2/backends/`. Zero code added to `packages/darnit-core` or `packages/darnit-baseline`. The runner consumes `audit_openssf_baseline` as a callable (same as feature 028) but doesn't modify it. The OpenAI SDK is a test-only dev-group dep. |
| II. Conservative-by-Default | Yes | PASS + REINFORCED | This feature exists to protect Principle II across a second provider surface. If an OpenAI-backed coding assistant silently reclassifies a WARN as PASS in its summary, this test catches it. Extending the diagnostic surface strengthens the "WARN counts as FAIL" invariant against provider drift. |
| III. TOML-First Architecture | No | N/A | No control definitions. No TOML changes. |
| IV. Never Guess User Values | No (indirect) | PASS | The runner does not fabricate or heuristically fill any context value. Every value the OpenAI assistant might read comes from the fixture repo's own `.project/project.yaml`. The `NoopBackend` similarly has no context inference. Principle IV is preserved by construction. |
| V. Sieve Pipeline Integrity | No | N/A | This feature is downstream of the sieve. |

**No violations.** No Complexity Tracking entries required.

Governance observations (feature-028-lineage):
- Manual-dispatch only for MVP; FR-007 (issue-#369 follow-up) still applies: scheduled cadence + governance-appropriate key sourcing is deferred to a separate feature.
- Two independent Environments (`parity-tier2` for Claude, `parity-tier2-openai` for OpenAI). Each has its own reviewer list; approvals are provider-scoped. That gives per-provider accountability -- an OpenAI-tier reviewer can approve OpenAI runs without being trusted for Anthropic-cost runs, and vice versa.

## Project Structure

### Documentation (this feature)

```text
specs/029-openai-parity-adapter/
+-- spec.md                                                     # /speckit-specify + /speckit-clarify output
+-- plan.md                                                     # this file
+-- research.md                                                 # Phase 0
+-- data-model.md                                               # Phase 1
+-- quickstart.md                                               # Phase 1
+-- contracts/
|   +-- skill-invocation-backend-protocol.md                    # Protocol shape for backend authors
|   +-- openai-workflow.md                                      # workflow_dispatch shape + Environment config
+-- checklists/
|   +-- requirements.md                                         # spec-quality checklist (exists)
+-- tasks.md                                                    # /speckit-tasks output
```

### Source Code (repository root)

Everything ships under `tests/` and `.github/workflows/`. Zero product changes.

```text
tests/darnit/parity/tier2/
+-- backends/                                                   # NEW: the Protocol seam
|   +-- __init__.py                                             # BACKEND_REGISTRY dict + Protocol re-export
|   +-- base.py                                                 # NEW: SkillInvocationBackend Protocol + SkillInvocationResult dataclass + SetupError
|   +-- claude_agent_sdk.py                                     # REFACTORED FROM claude_agent_sdk_client.py -- class satisfying Protocol
|   +-- openai_backend.py                                       # NEW: OpenAIBackend, Chat Completions loop
|   +-- noop.py                                                 # NEW: test-only NoopBackend for conformance/extensibility tests
+-- claude_agent_sdk_client.py                                  # DELETED (superseded by backends/claude_agent_sdk.py; imports re-exported for one release)
+-- run.py                                                      # UPDATED: --backend flag; BACKEND_REGISTRY lookup; new exit code 5
+-- diff.py                                                     # UPDATED: recognize turn_cap_exhausted outcome + emit its diff report shape
+-- test_openai_backend_adversarial.py                          # NEW: adversarial tests for the OpenAI adapter
+-- test_backend_protocol_conformance.py                        # NEW: SC-005 protocol conformance check across all registered backends
+-- test_backend_extensibility.py                               # NEW: SC-007 -- NoopBackend registers/invokes without shared-module edits
+-- test_workflow_config.py                                     # UPDATED: assertions extended to parity-tier2-openai.yml + SC-010 model-pin check + SC-002 OPENAI_API_KEY-exclusive-file check

.github/workflows/
+-- parity-tier2-openai.yml                                     # NEW: manual-dispatch, Environment-gated, pinned model default
+-- parity-tier2.yml                                            # UNCHANGED
```

**Structure Decision**: Additive-only. All feature-028 test files are extended (not forked); the one refactor (moving `claude_agent_sdk_client.py` into `backends/claude_agent_sdk.py`) preserves the module surface via a re-export line in the old path. Existing feature-028 tests are updated to import from the new location, but no test's behavior changes.

## Complexity Tracking

No violations. Section intentionally empty.
