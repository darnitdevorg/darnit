"""Pluggable answer-source Protocol + MVP file adapters.

Read-only accessors for pre-declared context answers. Adapters implement
one per origin (filesystem YAML, GitHub issue reader, email inbox, Slack
bot, ticketing system). The harness composes multiple sources via
AnswerResolver with a documented precedence.

See:
- specs/026-darnit-harness/contracts/answer-source-protocol.md
- specs/026-darnit-harness/data-model.md sections 1-2
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from darnit.core.logging import get_logger

logger = get_logger("harness.answer_sources")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AnswerSource(Protocol):
    """Read-only accessor for pre-declared context answers.

    Contract items AS-1..AS-5 (see contracts/answer-source-protocol.md):
    - ``name`` must be non-empty and unique within a resolver composition
    - ``get_answer(key)`` returns the answer or None; must not raise
    - ``known_keys()`` returns best-effort key enumeration; empty set OK for
      adapters that can't enumerate (e.g. async sources not yet polled)
    - Runtime-checkable so ``isinstance(obj, AnswerSource)`` works
    - No side effects on read; adapters do any I/O at construction time
    """

    name: str

    def get_answer(self, context_key: str) -> str | None: ...

    def known_keys(self) -> set[str]: ...


# ---------------------------------------------------------------------------
# AnswerResolver -- composes multiple sources with precedence
# ---------------------------------------------------------------------------


@dataclass
class AnswerResolver:
    """Composes multiple AnswerSource instances with explicit precedence.

    Later sources in the list OVERRIDE earlier for the same context_key
    (contract AS-6). Precedence is via list order, not adapter-declared
    priority -- keeps operator control explicit.
    """

    sources: list[AnswerSource] = field(default_factory=list)

    def add(self, source: AnswerSource) -> None:
        """Append a source. Raises ValueError on ``name`` collision (AS-7)."""
        for existing in self.sources:
            if existing.name == source.name:
                raise ValueError(
                    f"AnswerResolver: duplicate source name {source.name!r} "
                    f"(existing sources: {[s.name for s in self.sources]})"
                )
        self.sources.append(source)

    def resolve(self, context_key: str) -> tuple[str | None, str | None]:
        """Return (answer, source_name). LAST source with a match wins.

        Returns (None, None) if no source has the key.
        """
        winner_answer: str | None = None
        winner_name: str | None = None
        for source in self.sources:
            answer = source.get_answer(context_key)
            if answer is not None:
                winner_answer = answer
                winner_name = source.name
        return winner_answer, winner_name

    def summary(self) -> str:
        """One-line human-readable summary of the composition (AS-8)."""
        if not self.sources:
            return "AnswerResolver: (no sources)"
        parts = [f"{s.name}({len(s.known_keys())} keys)" for s in self.sources]
        return "AnswerResolver: [" + ", ".join(parts) + "] -- later wins conflicts"

    def sources_used(self) -> list[str]:
        """Return the ordered list of source names (for report provenance)."""
        return [s.name for s in self.sources]


# ---------------------------------------------------------------------------
# MVP file adapters
# ---------------------------------------------------------------------------


class ProjectYamlAnswerSource:
    """MVP file adapter: reads ``.project/project.yaml`` via feature 018.

    Flattens the loaded ProjectConfig into ``{context_key: str_value}`` using
    the same schema mapping ``darnit.config.context_storage.load_context``
    already uses. A missing or unparseable file yields an empty source (no
    exception; adapter returns None from every ``get_answer``).
    """

    name = "project_yaml"

    def __init__(self, local_path: str) -> None:
        self._local_path = local_path
        self._answers: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Attempt to load .project/project.yaml. Silent on failure."""
        try:
            from darnit.config.context_storage import load_context

            context_by_category = load_context(self._local_path)
        except Exception as exc:
            logger.debug(
                "ProjectYamlAnswerSource(%s): load_context failed: %s",
                self._local_path,
                exc,
            )
            return

        # Flatten category -> {key -> ContextValue} into a single {key: str}
        # dict. Feature 018's load_context returns per-category namespaces;
        # we accept ANY category's key (last write wins across categories,
        # which is a documented edge case since context_keys are meant to
        # be globally unique).
        for _category, keyed in context_by_category.items():
            for key, ctx_val in keyed.items():
                # ContextValue.value can be any type; coerce to str for the
                # AnswerSource shape which promises str | None.
                if ctx_val.value is None:
                    continue
                self._answers[key] = str(ctx_val.value)

    def get_answer(self, context_key: str) -> str | None:
        return self._answers.get(context_key)

    def known_keys(self) -> set[str]:
        return set(self._answers.keys())


class FileAnswerSource:
    """MVP file adapter: reads a user-supplied YAML or JSON file.

    Shape: top-level object with ``{context_key: str_value}`` entries.
    Auto-detects format by extension (``.json`` -> json, otherwise yaml).

    On parse error, raises ``AnswerSourceLoadError`` at construction time
    (fail-fast per CLI-4). The harness's fail-fast startup catches this
    and exits SETUP_ERROR.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self.name = f"--answers {self._path}"
        self._answers: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            raise AnswerSourceLoadError(
                f"--answers file not found: {self._path}",
                self._path,
            )
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AnswerSourceLoadError(
                f"--answers file unreadable ({self._path}): {exc}",
                self._path,
            ) from exc

        try:
            if self._path.suffix.lower() == ".json":
                data: Any = json.loads(text)
            else:
                data = yaml.safe_load(text)
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            raise AnswerSourceLoadError(
                f"--answers file parse error ({self._path}): {exc}",
                self._path,
            ) from exc

        if data is None:
            return
        if not isinstance(data, dict):
            raise AnswerSourceLoadError(
                f"--answers file top-level must be a mapping ({self._path}): got {type(data).__name__}",
                self._path,
            )

        for key, value in data.items():
            if not isinstance(key, str):
                raise AnswerSourceLoadError(
                    f"--answers file has non-string key {key!r} ({self._path})",
                    self._path,
                )
            if value is None:
                continue
            self._answers[key] = str(value)

    def get_answer(self, context_key: str) -> str | None:
        return self._answers.get(context_key)

    def known_keys(self) -> set[str]:
        return set(self._answers.keys())


class AnswerSourceLoadError(ValueError):
    """Raised at AnswerSource construction on unparseable input.

    Subclass of ValueError so callers can catch either specifically or
    broadly. Carries the offending path for error reporting.
    """

    def __init__(self, message: str, path: Path) -> None:
        self.path = path
        super().__init__(message)


__all__ = [
    "AnswerSource",
    "AnswerResolver",
    "ProjectYamlAnswerSource",
    "FileAnswerSource",
    "AnswerSourceLoadError",
]
