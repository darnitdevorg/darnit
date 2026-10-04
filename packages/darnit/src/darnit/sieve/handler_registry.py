"""Sieve handler registry for the confidence gradient pipeline.

Handlers are pluggable units that perform verification, data gathering, or
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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from darnit.core.authority import Authority
from darnit.core.error_class import ERROR_CLASSES, ErrorClass

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
    # Feature 037 (FR-016). The handler reached a conclusion, and the
    # conclusion is that the evidence is insufficient to pass.
    #
    # WARN differs from INCONCLUSIVE in kind, not in degree:
    #   INCONCLUSIVE -- the handler determined nothing; another pass may still
    #                   determine something, so the pipeline continues.
    #   WARN         -- the handler determined something, and what it
    #                   determined is not a pass.
    #
    # Do NOT return WARN to mean "I am unsure". That is INCONCLUSIVE. WARN is
    # for the case where the evidence was read, understood, and found short --
    # a requirements.txt that pins direct dependencies while its transitive
    # dependencies float, for instance.
    #
    # A WARN concludes the control only when the step may conclude FAIL
    # (feature 041); see resolve_step_result. A WARN counts as FAIL for
    # compliance (Constitution Principle II).
    WARN = "warn"
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
        authority: RFC-0001 Stage 1 (feature 025). Optional per-call
            narrowing: ``"suggestive"`` makes this result evidence only, even
            when the step may otherwise conclude its outcome (feature 041).
            Any other value leaves the step's effective set unchanged; a
            handler can never widen what its step may conclude.
        error_class: Feature 036. Set ONLY when the handler could not run to
            completion for an environmental reason (network unreachable, auth
            expired, subprocess timeout, missing binary, unexpected crash).
            Leave None on every success path AND on every clean failure -- a
            check that ran and found the repo non-compliant is a bare
            FAIL/WARN, not an environmental error. See
            :mod:`darnit.core.error_class`.
    """

    status: HandlerResultStatus
    message: str
    confidence: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    authority: Authority | None = None
    error_class: ErrorClass | None = None

    def __post_init__(self) -> None:
        """Enforce the two ``error_class`` invariants from the feature-036 contract.

        Rule 1 (FR-002a): reject unknown values. ``ErrorClass`` is a
        ``Literal`` and therefore erased at runtime, so without this check a
        typo'd or future-version value would flow silently into a report and
        an attestation as an uninterpretable failure cause.

        Rule 2: reject ``error_class`` alongside ``PASS``. A handler that
        could not complete cannot have produced a real pass.
        """
        if self.error_class is None:
            return
        if self.error_class not in ERROR_CLASSES:
            raise ValueError(
                f"error_class={self.error_class!r} is not a known ErrorClass; expected one of {sorted(ERROR_CLASSES)}"
            )
        if self.status == HandlerResultStatus.PASS:
            raise ValueError(
                f"error_class={self.error_class!r} is incompatible with "
                "status=PASS; a handler that could not complete cannot "
                "produce a PASS"
            )


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
        control_id: ID of the control being verified (empty for data gathering).
        project_context: Flattened .project/project.yaml values.
        gathered_evidence: Evidence accumulated from previous handlers in this control.
        shared_cache: Cache for shared handler results (keyed by shared handler name).
        dependency_results: Results from dependency controls (keyed by control ID).
        execution_context: Shared context instance across the entire audit run.
        mode: Feature 043. ``plan`` asks a remediation handler to compute its
            changes without making any; ``apply`` is a real run. Remediation
            handlers return their file changes in ``evidence["file_changes"]``
            in both modes and never write themselves: the remediation executor
            is the only writer. Verification handlers ignore it.
        platform: Feature 043. The run's platform session
            (``darnit.remediation.platform.PlatformSession``): the operator
            policy, the approved digests, and every platform requirement of
            the run, so ``platform_setting`` steps of several controls on one
            target share one change set. None outside remediation; a
            ``platform_setting`` step then plans alone under the operator
            policy with no approvals.
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
    execution_context: Any | None = None
    # Feature 031: assigned by the orchestrator's dispatch site when the
    # invocation targets the built-in ``mcp`` handler. None for every
    # other handler kind. A ``None`` value inside the mcp handler
    # indicates a plumbing bug and MUST resolve the pass ERROR.
    mcp_pool: Any | None = None
    mode: Literal["plan", "apply"] = "apply"
    platform: Any | None = None


# Handler callable signature: (config, context) -> HandlerResult
HandlerFn = Callable[[dict[str, Any], HandlerContext], HandlerResult]

# Feature 041: the outcomes a step may conclude. WARN concludes under the
# same permission as FAIL (both are non-compliant conclusions).
OUTCOMES: frozenset[str] = frozenset(("pass", "fail"))


def _outcome_set(values: Any, what: str) -> frozenset[str]:
    outcomes = frozenset(values)
    unknown = outcomes - OUTCOMES
    if unknown:
        raise ValueError(f"{what} contains unknown outcome(s) {sorted(unknown)}; expected a subset of {sorted(OUTCOMES)}")
    return outcomes


@dataclass
class SieveHandlerInfo:
    """Metadata about a registered sieve handler.

    Attributes:
        name: Short name used in TOML (e.g., "file_exists", "exec").
        phase: Recommended phase for this handler.
        fn: The handler callable.
        plugin: Name of the plugin that registered this handler (None for core).
        description: Human-readable description of what the handler does.
        ceiling: Feature 041. The outcomes (``pass``, ``fail``) a step of this
            type can at most conclude. Empty means evidence only.
        existence_ceiling: Feature 041. The ceiling when a step declares
            ``existence = true`` (its control's requirement is literally that
            a file exists or does not). None for step types without one.
        supports_plan: Feature 043. The handler honors ``HandlerContext.mode``
            for remediation: in ``plan`` mode it has no side effects. A
            handler without it is not previewable and is not invoked in a
            preview.
        settings: Feature 044. The step keys this step type reads, beyond
            the common step fields. None means not declared (plugin step
            types only): its steps' keys are not checked.
        expression_names: Feature 044. The top-level names an ``expr`` on
            this step type may reference. Empty means it accepts no ``expr``.
    """

    name: str
    phase: HandlerPhase
    fn: HandlerFn
    plugin: str | None = None
    description: str = ""
    ceiling: frozenset[str] = frozenset()
    existence_ceiling: frozenset[str] | None = None
    supports_plan: bool = False
    settings: frozenset[str] | None = None
    expression_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RefusedRegistration:
    """A plugin registration refused because another registrant owns the name (feature 044).

    ``registered_by`` is ``"core"`` or the plugin that registered the name first.
    """

    name: str
    attempted_by: str
    registered_by: str

    def message(self) -> str:
        return (
            f"Plugin {self.attempted_by!r} tried to register step type {self.name!r}, which "
            f"{'core' if self.registered_by == 'core' else 'plugin ' + repr(self.registered_by)} "
            "already registers; the registration was refused and the step type is unchanged"
        )


class SieveHandlerRegistry:
    """Registry for sieve pipeline handlers.

    Handlers are registered by name with a phase affinity. The registry supports:
    - Registration by core and by plugins (with plugin context tracking)
    - Lookup by name
    - Phase affinity validation (warns if handler used in unexpected phase)
    - Refusal of a plugin registration under a name core or another plugin
      already registered (feature 044): a replacement could widen a ceiling
    """

    def __init__(self) -> None:
        self._handlers: dict[str, SieveHandlerInfo] = {}
        self._plugin_context: str | None = None
        self.refused_registrations: list[RefusedRegistration] = []

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
        *,
        ceiling: Any = frozenset(),
        existence_ceiling: Any = None,
        supports_plan: bool = False,
        settings: Iterable[str] | None = None,
        expression_names: Iterable[str] = frozenset(),
    ) -> None:
        """Register a sieve handler.

        Args:
            name: Short name for TOML references (e.g., "file_exists").
            phase: Phase affinity as string or HandlerPhase enum.
            handler_fn: Callable with signature (config, context) -> HandlerResult.
            description: Human-readable description.
            ceiling: Feature 041. Outcomes (``"pass"``, ``"fail"``) a step
                of this type can at most conclude. A handler that registers
                no ceiling is evidence only: its results never conclude a
                control. Handlers that observe ground truth for the whole
                claim (``exec``, platform API checks, cryptographic
                verification) register ``{"pass", "fail"}``; presence and
                pattern handlers register ``{"fail"}``; model and manual
                handlers register nothing.
            existence_ceiling: Feature 041. Ceiling for steps that declare
                ``existence = true``. Only presence and pattern handlers
                register one.
            supports_plan: Feature 043. True only for a remediation handler
                that, given ``context.mode == "plan"``, changes nothing and
                returns the changes it would make.
            settings: Feature 044. The step keys the handler reads from its
                config, excluding the common step fields
                (framework-design 3.0.3). Every core step type declares
                them; a plugin step type that leaves None is not checked.
            expression_names: Feature 044. Names an ``expr`` on this step
                type may reference (``output`` and ``project`` for a
                post-step expression; the handler's own binding when it
                evaluates ``expr`` itself).

        Feature 044 (framework-design 3.0.3): a registration from a plugin
        context under a name core or a different plugin already registered
        is refused, logged at WARNING, and recorded in
        ``refused_registrations``; the existing step type is unchanged.
        """
        if isinstance(phase, str):
            phase = HandlerPhase(phase)

        existing = self._handlers.get(name)
        if existing and self._plugin_context and existing.plugin != self._plugin_context:
            refusal = RefusedRegistration(name, self._plugin_context, existing.plugin or "core")
            if refusal not in self.refused_registrations:
                self.refused_registrations.append(refusal)
            logger.warning(refusal.message())
            return
        if existing and existing.plugin and not self._plugin_context:
            logger.warning("Sieve handler '%s' re-registered by core (was '%s')", name, existing.plugin)

        info = SieveHandlerInfo(
            name=name,
            phase=phase,
            fn=handler_fn,
            plugin=self._plugin_context,
            description=description or handler_fn.__doc__ or "",
            ceiling=_outcome_set(ceiling, f"ceiling of handler {name!r}"),
            existence_ceiling=(
                None
                if existence_ceiling is None
                else _outcome_set(existence_ceiling, f"existence_ceiling of handler {name!r}")
            ),
            supports_plan=supports_plan,
            settings=None if settings is None else frozenset(settings),
            expression_names=frozenset(expression_names),
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
        self.refused_registrations.clear()


def effective_outcomes(info: SieveHandlerInfo, step: Any) -> frozenset[str]:
    """Outcomes a step may conclude for its control (feature 041).

    (existence ceiling if the step declares ``existence``, else ceiling),
    intersected with ``concludes`` when given, union the promoted outcome
    when a promotion exists (never for a model step: a model judgment is
    not promoted to conclude PASS). The legacy step ``authority = "suggestive"`` is
    ``concludes = []``. Computed at dispatch as well as validated at load, so
    a declaration that escaped validation still cannot widen the ceiling.
    """
    allowed = info.ceiling
    if getattr(step, "existence", False) and info.existence_ceiling is not None:
        allowed = info.existence_ceiling
    if getattr(step, "authority", None) == "suggestive":
        allowed = frozenset()
    concludes = getattr(step, "concludes", None)
    if concludes is not None:
        allowed = allowed & frozenset(concludes)
    promotion = getattr(step, "promotion", None)
    if promotion is not None and info.phase != HandlerPhase.LLM:
        allowed = allowed | {promotion.outcome}
    return frozenset(allowed)


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
