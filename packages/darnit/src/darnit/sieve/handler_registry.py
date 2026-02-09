"""Sieve handler registry for the confidence gradient pipeline.

Handlers are pluggable units that perform verification, context gathering, or
remediation work within a phase of the confidence gradient:

    deterministic → pattern → llm → manual

Core provides built-in handlers (file_exists, exec, regex, etc.).
Implementations register domain-specific handlers (scorecard, license_analyzer, etc.).

This is distinct from core.handlers.HandlerRegistry, which manages MCP tool handlers.

Example:
    ```python
    from darnit.sieve.handler_registry import get_sieve_handler_registry

    registry = get_sieve_handler_registry()
    registry.register("file_exists", phase="deterministic", handler_fn=file_exists_handler)

    # Look up and invoke
    handler = registry.get("file_exists")
    result = handler.fn(config={"files": ["README.md"]}, context=handler_context)
    ```
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HandlerPhase(str, Enum):
    """Phase affinity for a sieve handler."""

    DETERMINISTIC = "deterministic"
    PATTERN = "pattern"
    LLM = "llm"
    MANUAL = "manual"


class HandlerResultStatus(str, Enum):
    """Outcome of a handler invocation."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


@dataclass
class HandlerResult:
    """Result from a sieve handler invocation.

    Attributes:
        status: Outcome of the handler (pass/fail/inconclusive/error).
        message: Human-readable description of the result.
        confidence: Confidence score (0.0-1.0). Primarily used by pattern/llm handlers.
            Deterministic handlers typically return 1.0 for pass/fail, None for inconclusive.
        evidence: Key-value evidence produced by the handler (e.g., found_file, exit_code).
        details: Additional metadata for debugging or reporting.
    """

    status: HandlerResultStatus
    message: str
    confidence: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HandlerContext:
    """Execution context passed to every sieve handler.

    Provides the handler with everything it needs to do its work without
    reaching into global state.

    Attributes:
        local_path: Path to the repository being audited.
        owner: Repository owner (org or user).
        repo: Repository name.
        default_branch: Default branch name (e.g., "main").
        control_id: ID of the control being verified (empty for context gathering).
        project_context: Flattened .project/project.yaml values.
        gathered_evidence: Evidence accumulated from previous handlers in this control.
        shared_cache: Cache for shared handler results (keyed by shared handler name).
        dependency_results: Results from dependency controls (keyed by control ID).
    """

    local_path: str
    owner: str = ""
    repo: str = ""
    default_branch: str = "main"
    control_id: str = ""
    project_context: dict[str, Any] = field(default_factory=dict)
    gathered_evidence: dict[str, Any] = field(default_factory=dict)
    shared_cache: dict[str, HandlerResult] = field(default_factory=dict)
    dependency_results: dict[str, Any] = field(default_factory=dict)


# Handler callable signature: (config, context) -> HandlerResult
HandlerFn = Callable[[dict[str, Any], HandlerContext], HandlerResult]


@dataclass
class SieveHandlerInfo:
    """Metadata about a registered sieve handler.

    Attributes:
        name: Short name used in TOML (e.g., "file_exists", "exec").
        phase: Recommended phase for this handler.
        fn: The handler callable.
        plugin: Name of the plugin that registered this handler (None for core).
        description: Human-readable description of what the handler does.
    """

    name: str
    phase: HandlerPhase
    fn: HandlerFn
    plugin: str | None = None
    description: str = ""


class SieveHandlerRegistry:
    """Registry for sieve pipeline handlers.

    Handlers are registered by name with a phase affinity. The registry supports:
    - Registration by core and by plugins (with plugin context tracking)
    - Lookup by name
    - Phase affinity validation (warns if handler used in unexpected phase)
    - Plugin override of core handlers (implementation takes precedence)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, SieveHandlerInfo] = {}
        self._plugin_context: str | None = None

    def set_plugin_context(self, plugin: str | None) -> None:
        """Set the current plugin context for registrations.

        All handlers registered while a plugin context is active will be
        associated with that plugin.
        """
        self._plugin_context = plugin

    def register(
        self,
        name: str,
        phase: str | HandlerPhase,
        handler_fn: HandlerFn,
        description: str = "",
    ) -> None:
        """Register a sieve handler.

        Args:
            name: Short name for TOML references (e.g., "file_exists").
            phase: Phase affinity as string or HandlerPhase enum.
            handler_fn: Callable with signature (config, context) -> HandlerResult.
            description: Human-readable description.
        """
        if isinstance(phase, str):
            phase = HandlerPhase(phase)

        existing = self._handlers.get(name)
        if existing:
            if self._plugin_context and not existing.plugin:
                # Implementation overriding core built-in
                logger.debug(
                    "Sieve handler '%s' overridden by plugin '%s'",
                    name,
                    self._plugin_context,
                )
            elif self._plugin_context != existing.plugin:
                logger.warning(
                    "Sieve handler '%s' re-registered by '%s' (was '%s')",
                    name,
                    self._plugin_context or "core",
                    existing.plugin or "core",
                )

        info = SieveHandlerInfo(
            name=name,
            phase=phase,
            fn=handler_fn,
            plugin=self._plugin_context,
            description=description or handler_fn.__doc__ or "",
        )
        self._handlers[name] = info
        logger.debug(
            "Registered sieve handler '%s' (phase=%s, plugin=%s)",
            name,
            phase.value,
            self._plugin_context or "core",
        )

    def get(self, name: str) -> SieveHandlerInfo | None:
        """Look up a handler by name."""
        return self._handlers.get(name)

    def validate_phase(self, name: str, used_in: str | HandlerPhase) -> None:
        """Warn if a handler is used in a phase different from its affinity.

        This is advisory only — the handler will still execute.
        """
        if isinstance(used_in, str):
            used_in = HandlerPhase(used_in)

        info = self._handlers.get(name)
        if info and info.phase != used_in:
            logger.warning(
                "Sieve handler '%s' registered for '%s' phase but used in '%s'",
                name,
                info.phase.value,
                used_in.value,
            )

    def list_handlers(
        self, plugin: str | None = None, phase: str | HandlerPhase | None = None
    ) -> list[SieveHandlerInfo]:
        """List registered handlers, optionally filtered by plugin or phase."""
        if isinstance(phase, str):
            phase = HandlerPhase(phase)

        result = []
        for info in self._handlers.values():
            if plugin is not None and info.plugin != plugin:
                continue
            if phase is not None and info.phase != phase:
                continue
            result.append(info)
        return result

    def clear(self) -> None:
        """Clear all registrations. Used in tests."""
        self._handlers.clear()
        self._plugin_context = None


# Global singleton
_sieve_handler_registry: SieveHandlerRegistry | None = None


def get_sieve_handler_registry() -> SieveHandlerRegistry:
    """Get the global sieve handler registry.

    Auto-registers builtin handlers on first creation.
    """
    global _sieve_handler_registry
    if _sieve_handler_registry is None:
        _sieve_handler_registry = SieveHandlerRegistry()
        # Auto-register builtin handlers
        from darnit.sieve.builtin_handlers import register_builtin_handlers
        register_builtin_handlers()
    return _sieve_handler_registry


def reset_sieve_handler_registry() -> None:
    """Reset the global registry. Used in tests."""
    global _sieve_handler_registry
    if _sieve_handler_registry is not None:
        _sieve_handler_registry.clear()
    _sieve_handler_registry = None
