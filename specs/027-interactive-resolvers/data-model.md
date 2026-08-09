# Phase 1 Data Model: Interactive Question Resolvers

**Feature**: 027-interactive-resolvers | **Date**: 2026-08-08

## 1. `QuestionResolver` (Protocol)

Module: `packages/darnit/src/darnit/harness/question_resolvers.py`

```python
@runtime_checkable
class QuestionResolver(Protocol):
    name: str
    async def resolve(self, question: FeedbackQuestion) -> Answer | None: ...
```

**Fields / methods**:

- `name: str` -- stable identifier for the resolver. Used in log lines, `Answer.origin`, and `ResolutionTrailEntry.resolver_name`. Convention: snake_case, matches the resolver's entry-point name where applicable (e.g. `interactive_terminal`, `gh_issue_comment`).
- `resolve(question) -> Answer | None` (async) -- given one pending feedback question, produce an answer or return None. Empty and whitespace-only `Answer` values are collapsed to skip by the driver per FR-006a; resolver authors need not defensively check for them.

**Validation rules**: none at Protocol level -- `@runtime_checkable` only checks method / attribute presence. Actual conformance (async signature, return type) is validated at first invocation by the driver.

**Lifecycle**: resolvers are constructed once at CLI startup (or once at test time), then reused for the whole run. Resolvers MAY hold internal state across `resolve()` calls but MUST NOT rely on question ordering.

**Test conformance**: `MockQuestionResolver(name="mock", answer=Answer(value="v", origin="mock"))` is provided in the test fixtures; passes `isinstance(mock, QuestionResolver)`.

## 2. `Answer`

Module: `packages/darnit/src/darnit/harness/question_resolvers.py`

```python
class Answer(BaseModel):
    value: str
    origin: str
    authority: Literal["asserted"] = "asserted"
```

**Fields**:

- `value: str` -- the string value the resolver produces. Non-empty, non-whitespace-only invariant is enforced at the driver layer, not on the model itself (see below).
- `origin: str` -- provenance string, typically the resolver's `name`. May be more specific for adapters (e.g. `gh_issue_42_comment_3` instead of just `gh_issue_comment`).
- `authority: Literal["asserted"] = "asserted"` -- fixed to `"asserted"` at the model level. FR-009 says every answer produced by a resolver carries `authority: "asserted"`; enforcing this via a `Literal` type with a fixed default means a resolver author physically cannot construct an `Answer` with a different authority. Consistent with feature 025's authority model where `asserted` denotes "a human said so."

**Validation rules**: Pydantic `BaseModel` with `extra="forbid"`. No `min_length` on `value` at the model level -- the driver collapses empty/whitespace-only to skip so the corner is handled once, in one place, symmetric across all resolvers (interactive, programmatic, future). The `authority` field's `Literal["asserted"]` constraint makes any attempt to set another value a Pydantic validation error at construction time.

**Why not `min_length=1`?**: We considered making empty `Answer` a construction-time error. Rejected in Q4 of clarify: a resolver author might legitimately want to log "I tried" via a trail-visible skip; forcing them into `None` vs. `Answer("")` at the Protocol level makes their code more error-prone, not less. The driver layer is the single choke point.

## 3. `ResolutionTrailEntry`

Module: `packages/darnit/src/darnit/harness/question_resolvers.py`

```python
class ResolutionTrailEntry(BaseModel):
    resolver_name: str
    outcome: Literal["answered", "skipped", "errored"]
    error_summary: str | None = None
```

**Fields**:

- `resolver_name: str` -- the `name` attribute of the resolver that produced this entry.
- `outcome: Literal["answered", "skipped", "errored"]` -- closed set (FR-015a). No other values permitted.
- `error_summary: str | None` -- present iff `outcome == "errored"`. Contains the exception `str(exc)` after passing through feature 026's `_redact_secrets`, truncated to 200 characters. `None` for `answered` and `skipped`.

**Validation rules**: Pydantic `BaseModel` with `extra="forbid"`. Cross-field: `error_summary` is required when `outcome == "errored"` and forbidden otherwise (Pydantic model validator).

**Ordering**: In the final `PendingFeedbackEntry.resolution_trail: list[ResolutionTrailEntry]`, entries appear in the order the resolvers were offered the question. A reader iterates the list to reconstruct the chain.

## 4. `FeedbackQuestion` (reused, no changes)

Reused from feature 026's `HarnessReport.pending_feedback[*]`. Fields as-is: `control_id`, `context_key`, `question`, `answered`, and (after this feature) an optional `resolution_trail` field.

**No schema changes** to `FeedbackQuestion` itself in this feature. The `resolution_trail` lives at the report level attached to each pending entry, not on the `FeedbackQuestion` sieve-side type.

## 5. `PendingFeedbackEntry` (updated)

Module: `packages/darnit/src/darnit/harness/report.py`

**Additions**:

```python
class PendingFeedbackEntry(BaseModel):
    # ... existing fields from feature 026 ...
    resolution_trail: list[ResolutionTrailEntry] = Field(default_factory=list)
    answer_authority: Literal["asserted"] | None = None
```

- `resolution_trail: list[ResolutionTrailEntry]` -- default empty list. Populated only when the question was offered to at least one resolver.
- `answer_authority: Literal["asserted"] | None` -- present iff `answered == true`. Set to `"asserted"` whenever an answer originates from a `QuestionResolver` (this feature) OR from an `AnswerSource` (feature 026 -- both flavors are human assertions). Absent (`None`) when the question is still pending. Downstream consumers can filter for `answer_authority == "asserted"` to identify human-provided values without inspecting the trail.

**Validation rules**: `extra="forbid"` retained from feature 026. Both new fields are additive; existing 026-era tests continue to pass because the new fields default sensibly (empty list, `None`). Cross-field: `answer_authority` is required to be `"asserted"` when `answered == true`; forbidden otherwise (Pydantic model validator).

## 6. `HarnessReport` (updated)

Module: `packages/darnit/src/darnit/harness/report.py`

**Additions**:

```python
class HarnessReport(BaseModel):
    # ... existing fields from feature 026 ...
    resolvers_used: list[str] = Field(default_factory=list)
```

- `resolvers_used: list[str]` -- the `name` of every resolver that was CONFIGURED for this run, in the order they appeared in the chain. Includes resolvers that never received a question (e.g., the terminal resolver was configured but no questions were pending). Empty list for non-interactive runs with no third-party resolvers registered.

**Serialization**: `to_json()` emits `resolvers_used` unconditionally (empty array when unused). `to_markdown()` emits a "Resolvers used" section immediately after "Answer sources used" when the list is non-empty.

## 7. `HarnessRun` (updated)

Module: `packages/darnit/src/darnit/harness/driver.py`

**Additions**:

```python
@dataclass
class HarnessRun:
    # ... existing fields from feature 026 ...
    question_resolvers: list[QuestionResolver] = field(default_factory=list)
    per_resolver_timeout_s: float | None = None
```

- `question_resolvers: list[QuestionResolver]` -- ordered list of resolvers to try after the AnswerSource chain is exhausted. Default empty list preserves feature 026 behavior (batch-only collection).
- `per_resolver_timeout_s: float | None` -- per-resolver `resolve()` timeout in seconds. Default `None` means no timeout (matches the interactive resolver's documented behavior -- a human may take arbitrary time). When set to a positive float, each `resolver.resolve(question)` call is wrapped in `asyncio.wait_for(..., timeout=per_resolver_timeout_s)`; a timeout is captured as a `ResolutionTrailEntry(outcome="errored", error_summary="resolver timed out after Ns")` and the driver moves on to the next resolver. Fleet operators MAY set this via a CLI flag; the interactive resolver documents that setting it globally is usually inappropriate (an operator at a terminal can't be timed out on the same clock as a webhook resolver). Enforces FR-011.

**New classmethod**:

```python
@classmethod
def build_default_resolver_chain(cls, interactive: bool) -> list[QuestionResolver]:
    """Factory for the CLI wiring. See research.md R7."""
```

Returns the CLI's canonical chain: interactive terminal first (if `interactive=True`), then every other entry point in `darnit.question_resolvers` in discovery order.

**Behavior in `_collect_unanswered`**: after the existing AnswerSource-based pass, iterate `question_resolvers` for each remaining pending question per research.md R6. Populate `resolution_trail` on each `PendingFeedbackEntry` (whether or not it ended up answered).

**No re-audit invariant**: unchanged from feature 026. An interactively supplied answer is captured in the report but does NOT trigger re-evaluation of the associated control's status. Verified by the existing invariant test.

## 8. `InteractiveAborted` (new exception)

Module: `packages/darnit/src/darnit/harness/question_resolvers.py`

```python
class InteractiveAborted(Exception):
    """Raised by InteractiveTerminalResolver on Ctrl+C or EOF.

    Signals the driver to stop offering further questions to any resolver
    but preserve answers already collected in this collect phase.
    """
```

**Behavior**: caught specifically by `_collect_unanswered`; produces a trail entry with `outcome="skipped"` for the currently-being-asked question and terminates the collection loop. Not treated as an internal error; the harness still assembles and returns the report.

## 9. `InteractiveTerminalResolver` (concrete implementation)

Module: `packages/darnit/src/darnit/harness/interactive_resolver.py`

**Shape** (not a data model per se; the concrete class implementing `QuestionResolver`):

```python
class InteractiveTerminalResolver:
    name = "interactive_terminal"

    def __init__(
        self,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None: ...

    async def resolve(self, question: FeedbackQuestion) -> Answer | None: ...

    def _open_tty(self) -> tuple[TextIO, TextIO]: ...  # opens /dev/tty when streams are None
    def _format_prompt(self, question, position, total) -> str: ...
    def close(self) -> None: ...  # releases /dev/tty handle after collect
```

**Stream contract**:

- Constructor with default `input_stream=None, output_stream=None` opens `/dev/tty` on first call (or raises `HarnessSetupError` on failure).
- Constructor with explicit streams uses them verbatim (test path).

**Position indicator**: the resolver receives `question` only; the "N of M" position is passed as an out-of-band argument from the driver's collect loop, threaded into `_format_prompt`.

## 10. State transitions

Feature 027 introduces no persistent state. All state is per-run in memory:

```
question pending  --resolver.resolve() returns Answer(non-empty)--> answered
                  --resolver.resolve() returns None or empty Answer--> pending (try next resolver)
                  --resolver.resolve() raises--> pending (try next resolver; error captured in trail)
                  --resolvers exhausted--> pending (in the report; caller may re-run with --answers)

driver           --Ctrl+C or EOF from interactive--> collection loop terminates, remaining questions stay pending
```

Nothing persists between runs. A subsequent audit with the value written to `.project/project.yaml` re-evaluates the associated control.
