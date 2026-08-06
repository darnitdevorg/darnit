# Data Model: `darnit-harness`

**Feature**: 026-darnit-harness
**Date**: 2026-08-05

New types and Protocols introduced by this feature. Existing entities from features 018/022/024/025 are reused unchanged unless explicitly noted.

---

## New Protocols

### 1. `AnswerSource`

**Location**: `packages/darnit/src/darnit/harness/answer_sources.py`

**Definition**:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class AnswerSource(Protocol):
    """Read-only accessor for pre-declared context answers.

    Adapters implement one per origin (filesystem YAML, GitHub issue reader,
    email inbox, Slack bot, ticketing system). The harness composes multiple
    sources via AnswerResolver with a documented precedence.
    """

    name: str

    def get_answer(self, context_key: str) -> str | None: ...

    def known_keys(self) -> set[str]: ...
```

**Semantics**:
- `name`: human-readable identifier used in progress logs and the JSON report's `answer_sources_used` field.
- `get_answer(key)`: returns the answer string or None if this source doesn't have one.
- `known_keys()`: enumeration of keys this source can answer. May return an empty set (e.g., an async adapter that hasn't been polled yet). `get_answer` is authoritative.

**Validation rules**:
- Every adapter's `name` must be non-empty and unique within a run (guarded at `AnswerResolver` construction time).
- `get_answer` must return `None` (not raise) for unknown keys.

---

## New Types

### 2. `AnswerResolver`

**Location**: `packages/darnit/src/darnit/harness/answer_sources.py`

**Definition**:

```python
from dataclasses import dataclass, field

@dataclass
class AnswerResolver:
    """Composes multiple AnswerSource instances with precedence.

    Later sources override earlier for the same context_key. Precedence
    is explicit via list order.
    """

    sources: list[AnswerSource] = field(default_factory=list)

    def add(self, source: AnswerSource) -> None: ...

    def resolve(self, context_key: str) -> tuple[str | None, str | None]:
        """Return (answer, source_name). Iterates sources in order; later
        overrides earlier. Returns (None, None) if no source has the key."""

    def summary(self) -> str:
        """Return a human-readable summary of the composition for logging."""
```

**Invariants**:
- Sources are checked in order; the LAST source with a match wins (later = override).
- If two sources have the same `name`, `add()` raises `ValueError` (guarded uniqueness).

### 3. `HarnessRun`

**Location**: `packages/darnit/src/darnit/harness/driver.py`

**Definition** (skeleton):

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class HarnessRun:
    """One end-to-end audit invocation.

    Owns the AnswerResolver, the LLMStep, and the audit-level state.

    Construction is EXPLICIT: caller passes an already-composed
    ``answer_resolver``. There is no auto-discovery magic inside
    ``__post_init__``; the classmethod ``build_default_resolver`` is the
    documented factory for the standard file-based composition. This keeps
    the class testable without filesystem dependencies and makes the
    resolver's composition auditable at the call site.
    """

    local_path: str
    framework_name: str | None = None
    level: int = 3
    # NO default_factory here: caller MUST supply. Passing an empty
    # AnswerResolver() is valid (an audit with no context answers); passing
    # None is invalid (would silently drop the source composition contract).
    answer_resolver: AnswerResolver = field(default_factory=AnswerResolver)
    llm_step: LLMStep = field(default_factory=PydanticAILLMStep)
    per_call_timeout_s: int = 60
    total_run_timeout_s: int = 15 * 60

    async def run(self) -> "HarnessReport": ...

    @classmethod
    def build_default_resolver(
        cls, local_path: str, answers_path: str | None = None,
    ) -> AnswerResolver:
        """Factory: default composition per research.md R3.

        1. ProjectYamlAnswerSource(local_path) -- if the file exists.
        2. FileAnswerSource(answers_path) -- if the path is provided.

        Later sources override earlier (contract AS-6). This method exists
        so cmd_harness (T034) and any programmatic caller can share the
        same default composition without duplicating the wiring, but
        callers with non-file adapters MUST compose the resolver
        themselves.
        """
        resolver = AnswerResolver()
        # ProjectYamlAnswerSource silently skips a missing file (adapter
        # returns an empty known_keys() and None from get_answer).
        resolver.add(ProjectYamlAnswerSource(local_path))
        if answers_path:
            resolver.add(FileAnswerSource(answers_path))
        return resolver
```

`HarnessRun.run()` orchestrates: startup credential check -> initial audit -> LLM continuation loop -> unanswered collection -> report assembly. Returns a `HarnessReport`. Does NOT touch `answer_resolver` composition at run time; the caller's composition is used verbatim.

**Contract:** `answer_resolver` MUST be a valid `AnswerResolver` instance at construction time (empty is fine). Callers wanting the standard file composition call `HarnessRun.build_default_resolver(local_path, answers_path)` and pass the result. This is what `cmd_harness` (T034) does.

### 4. `HarnessReport`

**Location**: `packages/darnit/src/darnit/harness/report.py`

**Definition**:

```python
from typing import Literal
from pydantic import BaseModel

class HarnessSummary(BaseModel):
    total: int
    pass_: int  # aliased to "pass" in JSON
    fail: int
    warn: int
    n_a: int
    error: int

class PendingFeedbackEntry(BaseModel):
    control_id: str
    context_key: str
    question: str

class HarnessReport(BaseModel):
    """Result of a HarnessRun; serializable to Markdown and JSON."""

    harness_version: str = "1.0"
    target: dict  # {local_path, owner, repo}
    summary: HarnessSummary
    controls: list[dict]  # from CheckResult.model_dump()
    pending_feedback: list[PendingFeedbackEntry]
    answer_sources_used: list[str]
    llm_calls: dict  # {total: int, provider: str}
    exit_class: Literal[0, 1, 2, 3]

    def to_markdown(self) -> str: ...

    def to_json(self) -> str: ...
```

### 5. `HarnessExitCode`

**Location**: `packages/darnit/src/darnit/harness/exit_codes.py`

**Definition**:

```python
from enum import IntEnum

class HarnessExitCode(IntEnum):
    """Documented exit-code contract for `darnit harness`.

    Per FR-008. A CI script uses these to distinguish "audit ran and found
    issues" (1) from "audit couldn't run at all" (2 or 3).
    """
    SUCCESS = 0                # all applicable controls PASS or N/A
    AUDIT_FAILURES = 1         # audit completed; at least one FAIL
    SETUP_ERROR = 2            # missing credentials, missing repo, unparseable answers file
    INTERNAL_ERROR = 3         # unhandled exception, invariant violation, total-run timeout
```

---

## Existing types reused

- **`HarnessState`** (feature 025 `darnit.core.action_plan`): NOT used by MVP harness (the harness invokes `run_sieve_audit` + `verify_with_llm_response` directly rather than driving the pipeline via `next_action`/`submit_result`). Kept out of scope to minimize surface. Future refactor can migrate the harness to the ActionPlan loop if a per-handler ActionPlan surface emerges (Stage 2 territory).
- **`LLMStep`, `PydanticAILLMStep`, `MockLLMStep`, `ConsultationRequest`, `LLMJudgment`** (feature 025 `darnit.core.llm_step`): consumed directly.
- **`SieveOrchestrator`, `run_sieve_audit`, `verify_with_llm_response`** (feature 025 sieve): the harness's audit executor.
- **`CheckResult`** (feature 022 `darnit.sieve.models`): the per-control result shape; `authority` field per feature 025 is what the report surfaces.
- **`save_context_values`** (feature 018 `darnit.config.context_storage`): NOT called in MVP (see R4); the plumbing exists for a future `--interactive` mode.
- **`load_project_config`** (feature 018 `darnit.config.loader`): consumed by `ProjectYamlAnswerSource`.

---

## State transitions

### `HarnessRun.run()` lifecycle

```
STARTUP
  -> credentials_check (missing key -> exit SETUP_ERROR)
  -> answer_resolver_init (log summary of sources)
  -> INITIAL_AUDIT
     -> run_sieve_audit(stop_on_llm=True) -> list[CheckResult]
     -> pending_llm_controls = [c for c in results if c.status == PENDING_LLM]
  -> LLM_CONTINUATION_LOOP (bounded by total_run_timeout_s)
     for each pending_llm control:
       -> dispatch_llm_step(control) -> LLMConsultationResponse (with per-call timeout)
       -> verify_with_llm_response(control, response) -> updated CheckResult
     -> pending_llm_controls = still-pending after loop iteration (should be empty
        after one pass; loop guards against future orchestrator changes that
        chain PENDING_LLM -> new PENDING_LLM)
  -> COLLECT_UNANSWERED
     for each control with feedback_questions:
       for each question:
         answer, source_name = answer_resolver.resolve(question.context_key)
         if answer:
           question.answer = answer
           question.answered = True
           context_values[question.context_key] = answer
     #
     # Explicit policy: MVP does NOT re-audit after applying answers.
     # A control whose verdict depends on the newly-answered context_key
     # RETAINS its pre-Collect status (e.g., FAIL/WARN). The answer is
     # captured in the report for the operator's awareness but does NOT
     # retroactively change the verdict.
     #
     # Rationale: re-audit-on-answer requires re-running the sieve, which
     # doubles wall-clock cost for what is a small MVP fraction of runs.
     # An operator wanting a re-audited state invokes the harness AGAIN;
     # if the operator persisted the answer (e.g., by editing
     # .project/project.yaml), the second run picks it up cleanly.
     #
     # Stage 2 territory: add an `--auto-reaudit-after-collect` flag when
     # the demand is concrete. Deferred so MVP wall-clock stays bounded.
     #
  -> ASSEMBLE_REPORT
  -> EXIT
     failures = count(c.status == "FAIL" for c in report.controls)
     exit_code = AUDIT_FAILURES if failures > 0 else SUCCESS
```

### Error paths

- Missing credentials at startup: exit SETUP_ERROR immediately; no audit runs.
- Malformed `--answers` file: exit SETUP_ERROR; report explains parse error.
- Target repo path doesn't exist / has no `.baseline.toml`: exit SETUP_ERROR; message points at `darnit init`.
- LLM call timeout or error: log WARNING; substitute an INCONCLUSIVE response; control resolves as WARN with failure reason in evidence. Does NOT abort the audit.
- Total-run timeout: log ERROR; mark incomplete controls as ERROR; assemble partial report; exit INTERNAL_ERROR.
- Unhandled exception in the driver: log ERROR with traceback; attempt to write a minimal report; exit INTERNAL_ERROR.

---

## Non-entities (things this feature does NOT introduce)

- No new TOML schema fields.
- No new persistent state layer. `.project/project.yaml` is read; nothing new is written by MVP.
- No new packages. Everything ships in `darnit-core`.
- No new PyPI dependencies. `pydantic-ai-slim[anthropic]` from feature 025 is reused.
- No new attestation predicate. Feature 025's per-result `authority` already lands in the baseline attestation.
- No signing pipeline changes.
- No new CI workflow files.
