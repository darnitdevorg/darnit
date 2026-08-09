"""QuestionResolver Protocol + entities for the darnit harness (feature 027).

Introduces an active, async answer producer that sits DOWNSTREAM of feature 026's
`AnswerSource` chain. Semantics:

- `AnswerSource` (feature 026): passive lookup ("here's a preloaded value").
- `QuestionResolver` (this module): active resolution ("get me an answer somehow
  -- ask a human, call an API, open an issue").

The Protocol is `@runtime_checkable` so any class exposing `name: str` and
`async def resolve(question) -> Answer | None` conforms without explicit
inheritance. Registration is hybrid:

  - Python entry points under group `darnit.question_resolvers` (for third-party
    packages, matching the `darnit.frameworks` discovery pattern).
  - Direct injection into `HarnessRun.question_resolvers` (for tests and inline
    library use).

Constitution IV interaction: every `Answer` a resolver produces carries
`authority: "asserted"` -- enforced at the model level via `Literal["asserted"]`
with a fixed default. A resolver author physically cannot construct an `Answer`
with a different authority; Pydantic raises `ValidationError` at construction.

Empty and whitespace-only answer values are treated as skip by the driver (FR-006a);
resolvers need not defensively check for them.

See:
  - `specs/027-interactive-resolvers/spec.md`
  - `specs/027-interactive-resolvers/data-model.md` sections 1-3, 8
  - `specs/027-interactive-resolvers/contracts/question-resolver-protocol.md`
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator


class Answer(BaseModel):
    """Value returned by a `QuestionResolver` for one pending feedback question.

    Fields:
      - value: the string answer. Non-empty / non-whitespace-only invariant is
        enforced at the driver layer, not on the model. See FR-006a.
      - origin: provenance string. Convention: starts with the resolver's `name`.
      - authority: fixed to "asserted" via Literal + default. FR-009 / SC-003.
    """

    model_config = ConfigDict(extra="forbid")

    value: str
    origin: str
    authority: Literal["asserted"] = "asserted"


class ResolutionTrailEntry(BaseModel):
    """One entry in a `PendingFeedbackEntry.resolution_trail` list.

    Records which resolver was offered a question and how it responded. The
    driver appends one entry per resolver visited, in order. See FR-015a.
    """

    model_config = ConfigDict(extra="forbid")

    resolver_name: str
    outcome: Literal["answered", "skipped", "errored"]
    error_summary: str | None = None

    @model_validator(mode="after")
    def _check_error_summary(self) -> ResolutionTrailEntry:
        # RT-6: outcome == "errored" requires error_summary
        if self.outcome == "errored" and not self.error_summary:
            raise ValueError(
                "outcome='errored' requires a non-empty error_summary",
            )
        if self.outcome != "errored" and self.error_summary is not None:
            raise ValueError(
                f"outcome={self.outcome!r} MUST NOT carry an error_summary",
            )
        return self


@runtime_checkable
class QuestionResolver(Protocol):
    """Active answer producer for one pending feedback question.

    Any object exposing:
      - `name: str` (class or instance attribute)
      - `async def resolve(self, question) -> Answer | None`
    conforms to this Protocol. `isinstance(obj, QuestionResolver)` verifies
    the shape at runtime; the async signature is validated on first call.

    Contract summary (see contracts/question-resolver-protocol.md for the full
    list of rules QR-1..QR-27):

      - Return None to skip. Empty / whitespace-only Answer collapses to skip
        at the driver layer.
      - Raise on failure; the driver catches, redacts, and records `errored`
        in the trail. Never crashes the harness.
      - KeyboardInterrupt from within `resolve()` should propagate (except for
        the interactive terminal resolver, which converts it to InteractiveAborted).
    """

    name: str

    async def resolve(self, question: object) -> Answer | None:
        ...


class InteractiveAborted(Exception):
    """Raised by the interactive terminal resolver on Ctrl+C or EOF.

    Signals the driver to stop offering further questions to any resolver
    (not just the interactive one) but PRESERVE answers already collected in
    the current collect phase. Never treated as an internal error; the harness
    still assembles and returns the report.
    """


__all__ = (
    "Answer",
    "ResolutionTrailEntry",
    "QuestionResolver",
    "InteractiveAborted",
)
