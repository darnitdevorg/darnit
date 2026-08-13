"""HarnessRun driver: end-to-end audit with in-band LLM dispatch.

Feature 026 T009-T015 + T023. Consumes the same sieve entry points MCP does
(`run_sieve_audit(stop_on_llm=True)` + `SieveOrchestrator.verify_with_llm_response`)
and adds a driver that dispatches LLM steps itself via the injected `LLMStep`.

Per research.md R1: TWO-PASS approach preserves sieve purity. Initial pass
returns PENDING_LLM results; the driver dispatches those through the LLM step
and feeds each response back into the orchestrator for a final result.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from darnit.core.llm_step import ConsultationRequest, LLMJudgment, LLMStep, PydanticAILLMStep
from darnit.core.logging import get_logger
from darnit.harness.answer_sources import (
    AnswerResolver,
    FileAnswerSource,
    ProjectYamlAnswerSource,
)
from darnit.harness.exit_codes import HarnessExitCode
from darnit.harness.report import HarnessReport, HarnessSummary, PendingFeedbackEntry
from darnit.sieve.models import LLMConsultationResponse, PassOutcome
from darnit.tools.audit import prepare_audit, run_checks

logger = get_logger("harness")


class HarnessSetupError(Exception):
    """Raised for SETUP_ERROR class failures (missing credentials, bad path,
    unparseable config, unloadable framework).

    The message is user-facing (appears in the stderr exit-summary line).
    """


# Third-party SDK exceptions (httpx, anthropic) can embed credential material
# in their string form -- request URLs with `api_key=...` query params,
# Authorization header values, raw `sk-ant-...` tokens in the exception body.
# Anything derived from `str(exc)` MUST pass through _redact_secrets before
# reaching a log line or the JSON report. RF-4 / CLI-14 depend on this.
_REDACTORS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,'\"]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s,'\"]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,'\"&]+"), r"\1[REDACTED]"),
)


def _redact_secrets(text: str) -> str:
    """Strip common credential material from arbitrary text.

    Applied to third-party exception strings before they land in logs or the
    JSON report. Not a general-purpose scrubber -- targeted at the shapes
    httpx/anthropic errors actually produce.
    """
    for pattern, replacement in _REDACTORS:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class HarnessRun:
    """One end-to-end audit invocation with in-band LLM dispatch.

    Construction is EXPLICIT: the caller passes an already-composed
    ``answer_resolver``. There is no auto-discovery magic in
    ``__post_init__``; the classmethod ``build_default_resolver`` is the
    documented factory for the standard file composition (data-model.md
    section 3). This keeps HarnessRun testable in isolation without
    filesystem dependencies.
    """

    local_path: str
    framework_name: str | None = None
    level: int = 3
    answer_resolver: AnswerResolver = field(default_factory=AnswerResolver)
    llm_step: LLMStep = field(default_factory=PydanticAILLMStep)
    per_call_timeout_s: int = 60
    total_run_timeout_s: int = 15 * 60

    # Counters populated during .run()
    llm_calls_total: int = 0
    llm_provider: str = "anthropic:claude-sonnet-5"

    # ------------------------------------------------------------------
    # Factory for the standard file-based resolver composition (T024)
    # ------------------------------------------------------------------

    @classmethod
    def build_default_resolver(
        cls,
        local_path: str,
        answers_path: str | None = None,
    ) -> AnswerResolver:
        """Compose the default resolver per research.md R3.

        1. ProjectYamlAnswerSource(local_path) -- always added; empty if
           the file is absent.
        2. FileAnswerSource(answers_path) -- if the operator passed
           ``--answers``. Raises AnswerSourceLoadError at construction on
           parse failure; the caller wraps this in HarnessSetupError.

        Later sources OVERRIDE earlier (contract AS-6): ``--answers`` wins.
        """
        resolver = AnswerResolver()
        resolver.add(ProjectYamlAnswerSource(local_path))
        if answers_path:
            resolver.add(FileAnswerSource(answers_path))
        return resolver

    # ------------------------------------------------------------------
    # Startup checks (T010, T011)
    # ------------------------------------------------------------------

    def _check_credentials(self) -> str | None:
        """Return None on success or an error message string on failure.

        Fails fast in <2s per SC-002. Two checks (both required):

        1. ``ANTHROPIC_API_KEY`` env var set. Does NOT ping the API; a real
           check would add per-run latency and cost. If the key is invalid,
           the first LLM call surfaces the 401 via R6's INCONCLUSIVE-on-error
           path.

        2. ``pydantic_ai`` module importable. Feature 025 T001 added it as
           a required runtime dep; if the running Python env doesn't have it
           (e.g., ``uv run darnit`` picked up a stale global install rather
           than the workspace's editable install), fail fast with a message
           pointing at ``uv sync`` -- do NOT let the audit run and produce
           a misleading "complete, exit 0" report where every LLM step
           silently degraded to WARN.
        """
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "missing ANTHROPIC_API_KEY environment variable"
        # If the default LLM step is PydanticAILLMStep, verify its SDK is
        # importable. Callers who inject a MockLLMStep (tests) skip this
        # check because their step doesn't need pydantic_ai.
        if isinstance(self.llm_step, PydanticAILLMStep):
            try:
                import pydantic_ai  # noqa: F401
            except ImportError:
                return (
                    "pydantic_ai module not importable. Run `uv sync` from "
                    "the darnit workspace, or invoke as "
                    "`uv run --directory <darnit-workspace> darnit harness ...`"
                )
        return None

    def _initial_audit(
        self,
    ) -> tuple[list[dict[str, Any]], str, str, str]:
        """Run the initial sieve pass with stop_on_llm=True.

        Returns (results, owner, repo, default_branch).

        Raises ``HarnessSetupError`` on framework-load failures / missing
        `.baseline.toml` / undetectable owner+repo. Message points at
        `darnit init` per CLI-1.
        """
        owner, repo, resolved_path, default_branch, error = prepare_audit(
            None,
            None,
            self.local_path,
        )
        if error:
            raise HarnessSetupError(
                f"cannot prepare audit for {self.local_path}: {error}. "
                "Run `darnit init` if this repo has no .baseline.toml.",
            )

        try:
            results, _skipped = run_checks(
                owner=owner or "",
                repo=repo or "",
                local_path=resolved_path,
                default_branch=default_branch,
                level=self.level,
                stop_on_llm=True,
                apply_user_config=True,
                framework_name=self.framework_name,
            )
        except Exception as exc:
            raise HarnessSetupError(
                f"initial audit failed to load framework: {exc}",
            ) from exc

        # Empty results means no controls loaded -- almost always because
        # the target has no .baseline.toml (framework not resolvable) or
        # no framework name was passed via --framework. Silent "0 PASS,
        # 0 FAIL" is misleading; a fleet operator wiring this into CI would
        # see exit 0 and assume compliance. Raise SETUP_ERROR pointing at
        # `darnit init` (CLI-1 contract).
        if not results:
            raise HarnessSetupError(
                f"no controls loaded for {self.local_path}. "
                "Likely cause: no .baseline.toml in the target repo, or "
                "the framework named in .baseline.toml is not installed. "
                "Run `darnit init` in the target repo, or pass "
                "`--framework <name>` explicitly.",
            )

        return results, owner or "", repo or "", default_branch

    # ------------------------------------------------------------------
    # LLM dispatch (T012, T013)
    # ------------------------------------------------------------------

    async def _dispatch_llm_step(
        self,
        consultation_request: dict[str, Any],
    ) -> LLMConsultationResponse:
        """Call the injected LLMStep for one PENDING_LLM control.

        Per research.md R6: bounded by ``per_call_timeout_s``. Any failure
        (timeout, exception) returns an INCONCLUSIVE response with the
        error captured in ``reasoning`` so the control routes to WARN
        (not ERROR) -- honest degradation for a Collect-phase problem.
        """
        control_id = consultation_request.get("control_id", "<unknown>")
        prompt = consultation_request.get("prompt", "")

        # PR #365 review fix: propagate the sieve's evidence, hints,
        # threshold, and pre-read file contents. Prior code dropped these
        # so the LLM ran the prompt with no supporting context.
        request = ConsultationRequest(
            control_id=control_id,
            prompt=prompt,
            max_tokens=4096,
            gathered_evidence=consultation_request.get("gathered_evidence", {}) or {},
            file_contents=consultation_request.get("file_contents", {}) or {},
            analysis_hints=consultation_request.get("analysis_hints", []) or [],
            confidence_threshold=consultation_request.get("confidence_threshold"),
        )

        try:
            judgment: LLMJudgment = await asyncio.wait_for(
                self.llm_step.evaluate(request),
                timeout=self.per_call_timeout_s,
            )
            self.llm_calls_total += 1
        except TimeoutError:
            logger.warning(
                "%s LLM call timed out after %ds",
                control_id,
                self.per_call_timeout_s,
            )
            return LLMConsultationResponse(
                status=PassOutcome.INCONCLUSIVE,
                confidence=0.0,
                reasoning=f"LLM call failed: timeout after {self.per_call_timeout_s}s",
            )
        except Exception as exc:
            safe_exc_msg = _redact_secrets(str(exc))
            logger.warning(
                "%s LLM call raised %s: %s",
                control_id,
                type(exc).__name__,
                safe_exc_msg,
            )
            self.llm_calls_total += 1  # counts against provider even on failure
            return LLMConsultationResponse(
                status=PassOutcome.INCONCLUSIVE,
                confidence=0.0,
                reasoning=f"LLM call failed: {type(exc).__name__}: {safe_exc_msg}",
            )

        # Map LLMJudgment.outcome -> PassOutcome for the sieve.
        outcome_map = {
            "yes": PassOutcome.PASS,
            "no": PassOutcome.FAIL,
            "inconclusive": PassOutcome.INCONCLUSIVE,
        }
        sieve_outcome = outcome_map.get(judgment.outcome, PassOutcome.INCONCLUSIVE)

        return LLMConsultationResponse(
            status=sieve_outcome,
            confidence=judgment.confidence,
            reasoning=judgment.reasoning,
        )

    async def _llm_continuation_loop(
        self,
        results: list[dict[str, Any]],
        owner: str,
        repo: str,
        default_branch: str,
    ) -> list[dict[str, Any]]:
        """For each PENDING_LLM result, dispatch the LLM and get a final result.

        Feeds each response through ``SieveOrchestrator.verify_with_llm_response``
        which applies the Stage 1 authority rule (LLM = suggestive, cannot
        conclude). The returned result is what replaces the PENDING_LLM entry.

        Bounded by ``total_run_timeout_s`` at the outer call site.
        """
        from darnit.config.control_loader import control_from_effective
        from darnit.config.merger import load_effective_config_auto
        from darnit.sieve.models import CheckContext
        from darnit.sieve.orchestrator import SieveOrchestrator

        # Load the effective (composed) config so we can rebuild ControlSpecs
        # to feed back into verify_with_llm_response after LLM dispatch.
        # PR #365 review fix: resolve framework via `load_effective_config_auto`
        # so `.baseline.toml`'s `extends` (or --framework) determines the
        # framework, matching how run_sieve_audit chose it for the initial
        # pass. The previous code called `load_effective_config_by_name`
        # with a hardcoded "openssf-baseline" fallback, so a non-baseline
        # harness run would silently load the wrong framework.
        effective_config = load_effective_config_auto(
            Path(self.local_path),
            framework_name=self.framework_name,
        )

        orchestrator = SieveOrchestrator(stop_on_llm=True)

        pending = [r for r in results if r.get("status") == "PENDING_LLM"]
        if not pending:
            return results

        logger.info(
            "harness: dispatching %d pending LLM step(s) via %s",
            len(pending),
            self.llm_provider,
        )

        updated: dict[str, dict[str, Any]] = {}
        total_pending = len(pending)
        for idx, result in enumerate(pending, start=1):
            control_id = result["id"]
            logger.info(
                "[%d/%d] %s dispatching_llm %s",
                idx,
                total_pending,
                control_id,
                self.llm_provider,
            )

            evidence = result.get("evidence", {}) or {}
            consultation = evidence.get("llm_consultation") or {}
            if not consultation:
                logger.warning(
                    "%s PENDING_LLM but no llm_consultation in evidence; skipping",
                    control_id,
                )
                continue

            response = await self._dispatch_llm_step(consultation)

            # Build ControlSpec + CheckContext for the continuation call.
            effective = effective_config.controls.get(control_id)
            if effective is None:
                logger.warning(
                    "%s PENDING_LLM but control not in framework config; skipping",
                    control_id,
                )
                continue
            control_spec = control_from_effective(control_id, effective)

            check_ctx = CheckContext(
                owner=owner,
                repo=repo,
                local_path=self.local_path,
                default_branch=default_branch,
                control_id=control_id,
            )

            sieve_result = orchestrator.verify_with_llm_response(
                control_spec,
                check_ctx,
                response,
            )
            final_dict = sieve_result.to_legacy_dict()
            updated[control_id] = final_dict

            logger.info(
                "[%d/%d] %s resolved_%s (%s)",
                idx,
                total_pending,
                control_id,
                final_dict.get("status", "unknown").lower().replace("/", "_"),
                final_dict.get("authority", "unknown"),
            )

        # Replace pending entries with their final versions.
        return [updated.get(r["id"], r) for r in results]

    # ------------------------------------------------------------------
    # Collect (T014)
    # ------------------------------------------------------------------

    def _collect_unanswered(
        self,
        results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[PendingFeedbackEntry], dict[str, str]]:
        """Apply resolver answers to any feedback questions in the results.

        Per data-model.md "State transitions" COLLECT_UNANSWERED: does NOT
        re-audit. A control's verdict RETAINS its pre-Collect status. The
        answer is captured in context_values + on the question object; it
        does NOT retroactively change the verdict. Also does NOT persist
        to .project/ (research.md R4 idempotence argument).

        Feedback questions come from two sources (PR #365 review fix):

        1. Any ``result["feedback_questions"]`` a caller has already
           attached (unchanged legacy path).
        2. The framework's own pending-context enumerator
           (``darnit.config.context_storage.get_pending_context``). This
           is the only source that currently fires in production; before
           this fix, ``--answers`` had nothing to match against and was
           effectively inert.

        Returns (mutated_results, remaining_pending_feedback, context_values).
        """
        context_values: dict[str, str] = {}
        remaining_pending: list[PendingFeedbackEntry] = []

        # (1) Legacy attach path: caller-populated feedback_questions.
        for result in results:
            questions = result.get("feedback_questions", []) or []
            for q in questions:
                if isinstance(q, dict):
                    ctx_key = q.get("context_key")
                    already = q.get("answered", False)
                else:
                    ctx_key = getattr(q, "context_key", None)
                    already = getattr(q, "answered", False)
                if not ctx_key or already:
                    continue

                answer, source_name = self.answer_resolver.resolve(ctx_key)
                if answer is not None:
                    context_values[ctx_key] = answer
                    if isinstance(q, dict):
                        q["answered"] = True
                        q["answer"] = answer
                        q["answered_by"] = source_name
                    else:
                        q.answered = True
                        q.answer = answer
                else:
                    q_text = q.get("question", "") if isinstance(q, dict) else getattr(q, "question", "")
                    remaining_pending.append(
                        PendingFeedbackEntry(
                            control_id=result.get("id", ""),
                            context_key=str(ctx_key),
                            question=str(q_text),
                        ),
                    )

        # (2) Framework pending-context enumerator: read `[context.*]` keys
        # that the framework declared and that current .project/project.yaml
        # has not yet answered. Route each through the answer resolver so
        # `--answers` and the auto-discovered `.project/project.yaml` are
        # actually consulted. Failure to enumerate is not fatal -- log and
        # continue with whatever the caller already attached.
        try:
            from darnit.config.context_storage import get_pending_context

            pending_ctx = get_pending_context(self.local_path, level=self.level)
        except Exception as exc:
            logger.debug("get_pending_context failed: %s", exc)
            pending_ctx = []

        seen_ctx_keys = set(context_values.keys()) | {e.context_key for e in remaining_pending}
        for req in pending_ctx:
            ctx_key = req.key
            if ctx_key in seen_ctx_keys:
                continue
            seen_ctx_keys.add(ctx_key)

            answer, _source = self.answer_resolver.resolve(ctx_key)
            if answer is not None:
                context_values[ctx_key] = answer
                continue

            question_text = getattr(req.definition, "prompt", None) or getattr(req.definition, "hint", None) or ctx_key
            remaining_pending.append(
                PendingFeedbackEntry(
                    control_id=(req.control_ids[0] if req.control_ids else ""),
                    context_key=ctx_key,
                    question=str(question_text),
                ),
            )

        return results, remaining_pending, context_values

    # ------------------------------------------------------------------
    # Report assembly (T018)
    # ------------------------------------------------------------------

    def _assemble_report(
        self,
        results: list[dict[str, Any]],
        target_owner: str,
        target_repo: str,
        pending_feedback: list[PendingFeedbackEntry],
    ) -> HarnessReport:
        summary_counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 0, "PENDING_LLM": 0}
        for r in results:
            status = r.get("status", "ERROR")
            summary_counts[status] = summary_counts.get(status, 0) + 1

        summary = HarnessSummary(
            total=len(results),
            pass_=summary_counts["PASS"],
            fail=summary_counts["FAIL"],
            warn=summary_counts["WARN"] + summary_counts["PENDING_LLM"],
            n_a=summary_counts["N/A"],
            error=summary_counts["ERROR"],
        )

        # PR #365 review fix: an all-ERROR (or all-WARN) run must NOT exit
        # 0. Per the exit-code contract (cli.md CLI-11), SUCCESS requires
        # "all applicable controls PASS or N/A"; anything else is
        # AUDIT_FAILURES. Constitution II (Conservative-by-Default) also
        # treats WARN and ERROR as non-compliant.
        if summary.fail > 0 or summary.error > 0 or summary.warn > 0:
            exit_class = HarnessExitCode.AUDIT_FAILURES
        else:
            exit_class = HarnessExitCode.SUCCESS

        return HarnessReport(
            target={
                "local_path": self.local_path,
                "owner": target_owner or None,
                "repo": target_repo or None,
            },
            summary=summary,
            controls=results,
            pending_feedback=pending_feedback,
            answer_sources_used=self.answer_resolver.sources_used(),
            llm_calls={"total": self.llm_calls_total, "provider": self.llm_provider},
            exit_class=int(exit_class),
        )

    # ------------------------------------------------------------------
    # Public entry point (T015)
    # ------------------------------------------------------------------

    async def run(self) -> HarnessReport:
        """Run the harness end-to-end.

        Lifecycle per data-model.md "State transitions":
        1. Credentials check (missing key -> raise HarnessSetupError)
        2. Initial audit (stop_on_llm=True)
        3. LLM continuation loop (bounded by total_run_timeout_s)
        4. Collect unanswered (does NOT re-audit; MVP policy)
        5. Assemble + return report

        Raises HarnessSetupError on class-2 conditions; caller in
        ``cmd_harness`` catches and maps to exit code + stderr summary.
        """
        # Startup credential check
        cred_error = self._check_credentials()
        if cred_error is not None:
            raise HarnessSetupError(cred_error)

        logger.info("harness: starting audit of %s", self.local_path)
        logger.info(self.answer_resolver.summary())

        # Bound the whole run by total_run_timeout_s.
        try:
            report = await asyncio.wait_for(
                self._run_body(),
                timeout=self.total_run_timeout_s,
            )
        except TimeoutError as exc:
            logger.error(
                "harness: audit exceeded total-run timeout of %ds",
                self.total_run_timeout_s,
            )
            raise HarnessRunTimeout(
                f"audit exceeded total-run timeout of {self.total_run_timeout_s}s",
            ) from exc

        return report

    async def _run_body(self) -> HarnessReport:
        """Body of run(), separated so run() can wrap it in wait_for."""
        # Initial audit. run_sieve_audit is synchronous and calls out to gh/git
        # shell handlers that can block for arbitrary time on a bad repo.
        # Run it in a worker thread so `asyncio.wait_for(total_run_timeout_s)`
        # around _run_body can actually preempt a stuck audit.
        results, owner, repo, default_branch = await asyncio.to_thread(
            self._initial_audit,
        )
        total_controls = len(results)
        for idx, r in enumerate(results, start=1):
            status = r.get("status", "unknown")
            control_id = r.get("id", "unknown")
            # Map status -> phase verb. Explicit table so "PENDING_LLM"
            # doesn't get mangled by string replaces.
            _phase_verb_map = {
                "PASS": "resolved_pass",
                "FAIL": "resolved_fail",
                "WARN": "resolved_warn",
                "N/A": "resolved_na",
                "ERROR": "resolved_error",
                "PENDING_LLM": "resolved_pending",
            }
            phase_verb = _phase_verb_map.get(status, f"resolved_{status.lower()}")
            logger.info(
                "[%d/%d] %s %s",
                idx,
                total_controls,
                control_id,
                phase_verb,
            )

        # LLM continuation loop
        results = await self._llm_continuation_loop(results, owner, repo, default_branch)

        # Collect unanswered feedback questions
        results, pending_feedback, _context_values = self._collect_unanswered(results)

        # Assemble report
        return self._assemble_report(results, owner, repo, pending_feedback)


class HarnessRunTimeout(Exception):
    """Raised when total_run_timeout_s is exceeded during .run().

    Caller maps to exit code INTERNAL_ERROR.
    """


__all__ = [
    "HarnessRun",
    "HarnessSetupError",
    "HarnessRunTimeout",
]
