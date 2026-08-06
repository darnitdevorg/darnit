# Contract: `AnswerSource` Protocol

**Feature**: 026-darnit-harness
**Date**: 2026-08-05

Public typed Protocol that adapters implement to feed pre-declared context answers into the harness. FR-005a. Designed so future non-file adapters (email inbox, GitHub issue comments, Slack bot, ticketing systems) plug in without modifying `darnit.harness.driver`.

---

## Public API

```python
from darnit.harness.answer_sources import (
    AnswerSource,           # Protocol
    AnswerResolver,         # Composer
    ProjectYamlAnswerSource, # MVP file adapter
    FileAnswerSource,        # MVP file adapter
)
```

## Contract items

- **AS-1**: An `AnswerSource` implementation MUST expose a `name: str` attribute that is non-empty and unique within a single `AnswerResolver` composition.
- **AS-2**: `get_answer(context_key: str) -> str | None` MUST return the answer string for the key, or `None` if this source has no answer for that key. It MUST NOT raise for unknown keys.
- **AS-3**: `known_keys() -> set[str]` MUST return the set of context_keys this source can answer, best-effort. May return an empty set (async sources that haven't been polled). `get_answer` is authoritative; `known_keys` is for logging.
- **AS-4**: An implementation MUST satisfy `isinstance(obj, AnswerSource)` (Protocol is `@runtime_checkable`).
- **AS-5**: An implementation MUST NOT have side effects on `get_answer` (no writes to disk, no network calls beyond a possible initial fetch in `__init__`). Adapters that need network I/O for retrieval MUST do it eagerly in the constructor OR expose a separate `AsyncAnswerSource` Protocol (deferred to a follow-up feature).
- **AS-6**: `AnswerResolver.resolve(context_key) -> (answer, source_name)`: iterates registered sources in list order; the LAST source with a non-None `get_answer` return wins. Returns `(None, None)` if no source has the key.
- **AS-7**: `AnswerResolver.add(source)` MUST reject a source whose `name` collides with an already-registered source's name (raises `ValueError` with both names in the message).
- **AS-8**: `AnswerResolver.summary()` returns a human-readable string listing sources and their `known_keys()` counts, suitable for a one-line log at harness startup.

## Type conformance test (SC-related)

A shipping test in `tests/darnit/harness/test_answer_sources.py` MUST include a `MockAnswerSource` fake implementing the Protocol, added to a resolver, resolved against, and asserted equal to canned expected values. This test proves the Protocol admits a non-file source and closes the FR-005a "future non-file adapter" gap by demonstrating one.

## Non-contract items (explicitly NOT pinned)

- Whether a source's answers are read from the network, disk, an in-memory dict, or an external API is up to the implementation.
- Whether a source persists answers back to its origin (e.g., a GitHub-issue adapter that could mark the issue "resolved" after use) is up to the implementation. MVP file adapters do NOT persist back.
- Ordering of `known_keys()`: any set representation is fine.

## Contract-change procedure

Same as feature 024/025: contract file update in the same PR as code change; matching test edit; `Contract change:` note in PR description.
