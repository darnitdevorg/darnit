# Contract: `QuestionResolver` Protocol

**Feature**: 027-interactive-resolvers | **Consumers**: third-party resolver authors (A2A, GitHub-issue, Slack, webhook, custom) and the harness driver.

This document is the CONTRACT for the `QuestionResolver` Protocol. External implementers can conform to it to plug into `darnit harness`.

## 1. Shape

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class QuestionResolver(Protocol):
    name: str
    async def resolve(self, question: FeedbackQuestion) -> Answer | None: ...
```

- **QR-1**: A resolver MUST expose a `name: str` attribute (class-level or instance-level). The `name` MUST be stable across a run and unique within the resolver chain.
- **QR-2**: A resolver MUST expose an async method `resolve(question: FeedbackQuestion) -> Answer | None`.
- **QR-3**: A resolver MAY carry additional attributes and methods; the harness ignores them.
- **QR-4**: A resolver MUST pass `isinstance(instance, QuestionResolver)` (verified by the harness at first invocation).

## 2. Return-value semantics

- **QR-5**: Returning `None` means "I have no answer for this question." The question stays pending; the trail entry is `outcome: "skipped"`.
- **QR-6**: Returning `Answer(value="...", origin="...")` with a non-empty, non-whitespace-only `value` means "here is the answer." The question is marked answered; the trail entry is `outcome: "answered"`.
- **QR-7**: Returning `Answer(value="")` or `Answer(value="   ")` (whitespace-only) is EQUIVALENT to returning `None`. The harness collapses these to skip. This is enforced at the driver layer -- resolver authors need not defensively check for empty values.
- **QR-8**: Returning a non-`Answer` non-`None` object is undefined behavior. The harness will treat it as an error (trail entry `outcome: "errored"`, `error_summary` naming the wrong return type).

## 3. Exception semantics

- **QR-9**: A resolver's `resolve()` MAY raise. The harness catches all exceptions except `InteractiveAborted`, logs a warning, produces a trail entry with `outcome: "errored"` and a redacted, 200-char-truncated `error_summary`, and CONTINUES to the next resolver.
- **QR-10**: A resolver MUST NOT catch `KeyboardInterrupt` inside `resolve()` unless it is the interactive terminal resolver (which converts it to `InteractiveAborted`). Programmatic resolvers letting `KeyboardInterrupt` propagate is preferred; the driver's collect loop handles interruption uniformly.
- **QR-11**: A resolver SHOULD strip credential material from any exception it raises before it propagates. The harness's `_redact_secrets` pass is a safety net, not a substitute for resolver-side hygiene.

## 4. Timing semantics

- **QR-12**: A resolver's `resolve()` SHOULD return promptly for programmatic sources; the harness does not impose a per-resolver timeout in the MVP. Third-party resolvers with long-running side effects (GH issue polling, Slack DM wait) SHOULD implement their own internal timeout and return `None` if the source can't answer in time.
- **QR-13**: The interactive terminal resolver has NO timeout by design -- a human may take arbitrary time to respond. Ctrl+C is the operator's abort signal.

## 5. Registration mechanisms

Two mechanisms, both supported (hybrid decision from clarify Q1):

### 5.a Entry point (for third-party packages)

- **QR-14**: A third-party package SHOULD declare a Python entry point in the group `darnit.question_resolvers`. Example `pyproject.toml`:

    ```toml
    [project.entry-points."darnit.question_resolvers"]
    my_gh_issue_resolver = "my_pkg.resolvers:build_gh_issue_resolver"
    ```

- **QR-15**: The referenced callable MUST accept zero arguments and return a `QuestionResolver` instance.
- **QR-16**: Discovery is lazy at CLI startup. Failures during `ep.load()` or the subsequent `isinstance` check log a warning and skip that entry point; other resolvers in the group still register successfully.

### 5.b Direct injection (for tests and library consumers)

- **QR-17**: A library consumer MAY inject resolvers directly via `HarnessRun(question_resolvers=[MyResolver(), ...])`. This bypasses discovery entirely.
- **QR-18**: Test code SHOULD use direct injection with `MockQuestionResolver` fixtures. No wheel or entry-point setup is required for tests.

## 6. Ordering + composition

- **QR-19**: The resolver chain runs AFTER the `AnswerSource` chain from feature 026. Any question resolved by an `AnswerSource` (project.yaml, `--answers` file) never reaches the resolver chain.
- **QR-20**: Resolvers run in the order they appear in `HarnessRun.question_resolvers`. First non-None wins for a given question; subsequent resolvers are not offered that question.
- **QR-21**: The CLI's `--interactive` flag registers `interactive_terminal` at the HEAD of the chain. Other entry-point resolvers follow in `importlib.metadata` discovery order.

## 7. Provenance surfacing

- **QR-22**: Every `Answer` a resolver produces MUST have an `origin` field. The harness does not synthesize one; resolvers set it explicitly. Convention: `origin` starts with the resolver's `name` and may be extended for adapter-specific detail (e.g. `gh_issue_42_comment_3`).
- **QR-23**: The harness records the full trail per question (see `resolution-trail-schema.md`). Resolvers do NOT populate the trail themselves -- the driver does, based on what each resolver returned or raised.

## 8. Constitution IV compatibility

- **QR-24**: Every `Answer` a resolver produces carries `authority: "asserted"` -- fixed as a `Literal["asserted"]` on the `Answer` Pydantic model with a default value. Resolvers do NOT need to set it explicitly; constructing `Answer(value="v", origin="o")` is enough. Attempting to construct `Answer(authority="dispositive")` or any other value raises a Pydantic `ValidationError` at construction time. This makes the FR-009 safety property a physical constraint of the type, not a policy the driver has to remember to apply.
- **QR-25**: A resolver MUST NOT infer values from heuristics and return them as `Answer` objects without an explicit human (or explicit external system) speaking. Detection-only "candidate" behavior belongs in an `AnswerSource` (with `allow_sieve_hints`), not in a `QuestionResolver`. This constraint is not enforceable at the type level; it is a contract obligation on resolver authors.

## 9. Version stability

- **QR-26**: The Protocol shape defined in this contract is v1. Backwards-incompatible changes (removing `name`, renaming `resolve`, changing return type) constitute a new feature-level spec change, not a minor evolution.
- **QR-27**: Additive changes (optional new methods with default behaviors, new fields on `Answer`) MAY happen within v1 as long as third-party resolvers that don't implement them continue to work.
