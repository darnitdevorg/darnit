# Research: `darnit-harness` End-to-End Audit Driver

**Feature**: 026-darnit-harness
**Date**: 2026-08-05
**Status**: Complete

Phase 0. One Decision / Rationale / Alternatives triplet per open architectural choice.

---

## R1. How does the harness dispatch LLM steps in-band?

**Decision**: The harness invokes `run_sieve_audit(stop_on_llm=True)` to gather initial results, then for each control that returned `PENDING_LLM`, it constructs an `LLMConsultationResponse` by dispatching the request through the injected `LLMStep`, and re-invokes `SieveOrchestrator.verify_with_llm_response(control_spec, context, response)` to get the final result. Iterates until no `PENDING_LLM` remain.

**Rationale**:
- The orchestrator already exposes `verify_with_llm_response` (added pre-Stage-1; verified as of feature 025). It's the exact continuation seam the harness needs.
- `stop_on_llm=True` for the initial pass keeps the pipeline behavior identical to what MCP and CLI paths do (so the same sieve code runs). The harness's added value is doing the LLM dispatch itself between passes.
- Alternative: patch `stop_on_llm=False` semantics inside the orchestrator to mean "call the injected LLMStep directly." Rejected because it couples the sieve (which today knows nothing about the LLMStep injection) to an executor -- violating separation. Two-pass "gather, then dispatch, then continue" keeps the sieve pure.
- Feature 025's authority rule fires in `verify_with_llm_response` regardless (LLM = suggestive; suggestive can't conclude). So SC-008 holds by construction.

**Alternatives considered**:
- **Rewrite the orchestrator's inner loop to accept an optional LLMStep and dispatch inline**: bigger change, muddies the sieve's role, harder to test. Rejected.
- **Have the harness bypass the sieve entirely and drive the ActionPlan protocol via `next_action`/`submit_result`**: possible but Stage 1's `next_action` is at pipeline granularity (audit/collect/remediate), not per-handler. Harness would need to do full audit-level dispatch which duplicates existing `cmd_audit` / `run_sieve_audit`. Rejected; reuse over reinvention.

---

## R2. What is the `AnswerSource` Protocol shape?

**Decision**:

```python
class AnswerSource(Protocol):
    """Read-only accessor for pre-declared context answers.

    Adapters implement one of these per origin: filesystem YAML, env vars,
    GitHub issue reader (future), email inbox (future), Slack bot (future).
    The harness composes multiple sources with a documented precedence.
    """
    name: str  # human-readable identifier for logs / reports

    def get_answer(self, context_key: str) -> str | None:
        """Return the answer for context_key, or None if not present."""
        ...

    def known_keys(self) -> set[str]:
        """Return the set of context_keys this source can answer.

        Used at startup to log 'source X will answer keys A, B, C' so an
        operator can debug precedence mismatches. Sources that can't
        enumerate (future async sources like an email inbox that hasn't
        been polled yet) may return an empty set; get_answer is the
        authoritative lookup.
        """
        ...
```

Composed via a small `AnswerResolver` that iterates a list of `AnswerSource` instances in precedence order, returning the first non-None answer for a given key.

MVP adapters:
- `ProjectYamlAnswerSource(local_path)`: reads `.project/project.yaml` via feature 018's `load_project_config`.
- `FileAnswerSource(path)`: reads a user-supplied YAML/JSON file at the top-level shape `{context_key: answer_string}`.

**Rationale**:
- Small Protocol surface (two methods) keeps future adapters cheap to write.
- `known_keys()` is optional-behavior (empty set is fine) so async adapters (email, GitHub issues) that don't know their key set upfront still satisfy the Protocol.
- Precedence via list ordering rather than adapter-declared priority: keeps operator control explicit ("I added --answers, it wins").

**Alternatives considered**:
- **Fetch-once-load-all interface** (`load_all() -> dict[str, str]`): simpler for file sources, doesn't fit async sources. Rejected because it forces every future adapter to eagerly enumerate.
- **Async Protocol** (`async def get_answer(...)`): would future-proof for network adapters, but MVP file adapters are trivially sync and would need `await` boilerplate. Deferred: add an `AsyncAnswerSource` sibling Protocol when the first async adapter lands.

---

## R3. What is the answer-source precedence order?

**Decision**: Later sources in the list override earlier for the same key. Default composition order for MVP:

1. `ProjectYamlAnswerSource(target_repo/.project/project.yaml)` -- if the file exists.
2. `FileAnswerSource(--answers path)` -- if the flag is passed.

Concretely: the operator's explicit `--answers` file wins over the auto-discovered `.project/`. Rationale: `--answers` is the explicit override; auto-discovery is the default. Operator wants their override to actually override.

Startup logs a summary: "AnswerResolver: [project_yaml(3 keys), --answers(7 keys)] -- --answers wins conflicts."

**Rationale**:
- Explicit-over-implicit is the standard override precedence.
- Logging keeps the resolution transparent so an operator debugging "why isn't my answer being used" can see it.

**Alternatives considered**:
- **Auto-discovery wins**: violates operator expectations for `--answers` overrides.
- **Fail on conflict rather than override**: safer but more friction; a CI script that adds a temporary override to `--answers` shouldn't have to first strip the value from `.project/`. Rejected.

---

## R4. How is confirmation persistence tied to answer sources?

**Decision**: Answers RESOLVED at run-start (from any source) do NOT get re-written back to `.project/`. Reason: the answers were already at their source of truth; writing them back to `.project/` would corrupt precedence on the NEXT run (auto-discovered value would then match `--answers`, silently accepting whatever the operator meant as a one-off override).

New answers gathered DURING a run (currently: none in MVP -- FR-006 says non-interactive default and MVP has no interactive mode) WOULD be persisted via `save_context_values` if such answers ever arrived. This code path is inactive in MVP but the plumbing exists so a future `--interactive` mode requires only wiring the input source.

**Rationale**:
- Idempotence: running the harness twice with the same inputs shouldn't drift the on-disk state.
- Round-tripping between `--answers` and `.project/` should stay lossy in that direction; the file is the source of truth for what's confirmed for the repo, not a caching layer for CLI flags.

**Alternatives considered**:
- **Always persist resolved answers to `.project/`**: convenient for the "run once to bootstrap" case, but breaks the precedence-override contract on the next run. Rejected.
- **Persist only auto-discovered values (not `--answers`)**: this is what happens by default anyway since `--answers` doesn't need to be persisted (it came from a file the operator controls). Simplest to just persist nothing at MVP.

---

## R5. What is the report shape (Markdown and JSON)?

**Decision**:

**Markdown** (default): sections in order: `# Darnit Harness Report`, `## Summary` (per-level compliance table), `## Failed Controls` (list with rationale + evidence excerpt), `## Warned / Pending Controls` (list with the pending feedback keys), `## Passed Controls` (compact list). Every control's line shows its authority in parentheses (e.g., `OSPS-AC-01.01 PASS (dispositive)`).

**JSON**: top-level shape:

```jsonc
{
  "harness_version": "1.0",
  "target": {"local_path": "...", "owner": "...", "repo": "..."},
  "summary": {"total": 42, "pass": 30, "fail": 8, "warn": 4, "n_a": 0, "error": 0},
  "controls": [
    {"id": "OSPS-...", "status": "PASS", "authority": "dispositive", "level": 1, "message": "...", "evidence": {...}},
    ...
  ],
  "pending_feedback": [
    {"control_id": "STAGE1-REF-...", "context_key": "security_contact", "question": "..."},
    ...
  ],
  "answer_sources_used": ["project_yaml", "--answers /path/to/x.yaml"],
  "llm_calls": {"total": 3, "provider": "anthropic:claude-sonnet-4-6"}
}
```

**Rationale**:
- Markdown is designed to be pasted into a GitHub issue or Slack message; hence the "failed first, passed compact" ordering.
- JSON shape mirrors feature 025's `authority`-on-every-result contract (SC-006).
- `answer_sources_used` and `llm_calls` are provenance fields a fleet operator can use for auditability of the audit itself.
- No signing / attestation in the harness itself; that composes later with the existing `darnit-baseline` attestation path.

**Alternatives considered**:
- **SARIF format**: darnit-baseline already emits SARIF via `formatters/sarif.py`. The harness can call the same formatter if `--format=sarif` is added, but SARIF-in-harness is out-of-scope for MVP.
- **Include full pass_history per control in the JSON**: useful for debugging but noisy. Emit under a `--verbose-report` flag later.

---

## R6. Where does the LLM dispatch happen exactly, and how are timeouts handled?

**Decision**: The `HarnessRun.dispatch_llm_step` method takes a `PENDING_LLM` result's `consultation_request` (already assembled by `llm_eval_handler` / `llm_extract_handler` inside the sieve), builds a `ConsultationRequest`, and calls `await llm_step.evaluate(request)`. Wraps the call in `asyncio.wait_for(coro, timeout=per_call_timeout)` (default 60s per FR-014). Total-run wall clock is enforced by a separate `asyncio.wait_for` around the outer audit loop (default 15 minutes).

On per-call timeout or exception:
1. Log a WARNING with control-id + reason.
2. Substitute an `LLMConsultationResponse(status=PassOutcome.INCONCLUSIVE, confidence=0.0, reasoning="LLM call failed: <reason>")`.
3. Feed that response into `verify_with_llm_response`. Given the response is INCONCLUSIVE, the sieve routes it to the manual/inconclusive path (result: WARN with reasoning attached).

This preserves the sieve's semantics for LLM-outage cases: the control ends up WARN with the failure reason recorded as evidence. NOT ERROR -- ERROR would signal "we don't know what the observation was" but we DID know; the LLM outage prevents us from processing what we asked for, which is a Collect-phase problem, not a Check-phase measurement failure.

On total-run timeout: log an ERROR, mark all incomplete controls as ERROR (dispositive-terminal per Stage 1), print the report anyway, exit class 3.

**Rationale**:
- Per-call vs total-run bounds cover the two failure modes (single stuck call vs runaway job).
- INCONCLUSIVE-on-failure is the honest degradation: we tried, we couldn't complete, human review needed.
- ERROR at total-run cutoff is the honest termination: incomplete audit means outputs are provisional.

**Alternatives considered**:
- **Retry with exponential backoff on rate-limit specifically**: `pydantic-ai` may already do this internally; check at implementation time. If it does, we don't add a second retry layer.
- **Terminate the whole audit on first LLM failure**: too fragile; one control's LLM outage shouldn't kill an audit that would otherwise report a mix of PASS/FAIL correctly.

---

## R7. How is the API key handled? Redaction? Storage?

**Decision**:
- Read `ANTHROPIC_API_KEY` from env at startup only.
- Never write it to disk. Never include it in reports (both Markdown and JSON exclude the key).
- Never log its value. Log lines that reference the LLM provider name it as `anthropic:claude-sonnet-4-6` (the model string), not the key.
- Startup credential check: attempt to construct `PydanticAILLMStep()` and call `_build_agent()` -- the check that reads the env var. If missing, exit class 2. Do NOT make a real API call to verify the key's validity; a real check would add latency and could rate-limit CI runs. If the key is invalid, the first LLM call will fail with a 401 and the harness will surface it per R6.
- If a user grep's the process env or memory, the key IS there while the process runs (Python doesn't zero secrets). Not something a security-conscious deploy should worry about beyond standard OS process isolation. Consumers can further isolate via `env -i ANTHROPIC_API_KEY=... darnit harness ...` if they want a minimal env footprint.

**Rationale**:
- Env-var-only aligns with 12-factor deployments and CI-runner secret plumbing (GitHub Actions `env:`, GitLab CI `variables:`).
- No verification round-trip at startup keeps the 2-second fail-fast property of SC-002.
- Redaction discipline in logs / reports is enforced by NEVER passing the key into any string that ends up in output.

**Alternatives considered**:
- **`--key-file <path>` flag**: convenient for local dev, but env var is the CI-idiomatic path. Skip for MVP; add if requested.
- **Prompt for missing key interactively**: violates FR-006 (non-interactive default). Rejected.
- **Do a real API-ping at startup**: rejects invalid keys faster but adds latency and API cost per run. Skip.

---

## R8. What is the exact progress-line format?

**Decision**: One line per control transition, emitted to stderr via Python `logging` at INFO level. Format:

```text
INFO:darnit.harness:[N/M] <control_id> <phase-verb> [<detail>]
```

Where:
- `N/M` = 1-based control index / total controls being audited (from the resolved control list).
- `phase-verb` is one of: `starting`, `dispatching_llm`, `resolved_pass`, `resolved_fail`, `resolved_warn`, `resolved_error`, `resolved_na`, `resolved_pending`.
- `detail` (optional) is a short qualifier (e.g., the LLM model for `dispatching_llm`).

Examples:

```text
INFO:darnit.harness:[1/42] OSPS-AC-01.01 starting
INFO:darnit.harness:[1/42] OSPS-AC-01.01 resolved_pass (dispositive)
INFO:darnit.harness:[2/42] STAGE1-REF-SECURITY-01 starting
INFO:darnit.harness:[2/42] STAGE1-REF-SECURITY-01 dispatching_llm anthropic:claude-sonnet-4-6
INFO:darnit.harness:[2/42] STAGE1-REF-SECURITY-01 resolved_fail (dispositive)
```

The exit-summary line (FR-009) is separately at INFO level with a distinguishable prefix:

```text
INFO:darnit.harness:harness: complete, 30 PASS, 8 FAIL, 4 WARN, 0 pending, exit 1
```

**Rationale**:
- Matches Python stdlib logging convention that darnit already uses (verified via `grep 'INFO:' -r packages/darnit/src/`).
- `[N/M]` counter is what tools like cargo, npm, etc. use; operators recognize it.
- Verbs are past-tense-when-done, present-when-doing so line semantics are unambiguous.
- Machine-parseable via `grep -E "^INFO:darnit.harness:\[[0-9]+/[0-9]+\]"` for progress and `grep "^INFO:darnit.harness:harness:"` for the summary.

**Alternatives considered**:
- **JSON events per line**: overkill for CI logs; humans want to read them. Adding a `--log-format=json` flag is a future opt-in.
- **Bracketed prefixes like `[HARNESS]`**: doesn't compose with existing darnit logging which uses `LEVEL:module:message`. Consistency over invention.

---

## Summary of resolved unknowns

All Technical Context items are concrete. No `NEEDS CLARIFICATION` markers remain. Ready for Phase 1.
