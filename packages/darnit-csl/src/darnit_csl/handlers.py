"""Custom sieve handlers for the community-spec framework.

`csl_llm_if_present` gates the LLM content check behind file existence: a missing
file fails deterministically (no reason to consult the model about a file that is
not there), while a file that exists is handed to the LLM for a content-quality
judgment. It is registered in the sieve handler registry with the ``llm`` phase so
the orchestrator's PENDING (llm_judgment) branch fires for the present-file case. darnit
imports this package during framework/implementation discovery, so the handler is
available in both the CLI audit path and `darnit serve`.
"""

from __future__ import annotations

import os
from typing import Any

from darnit.sieve.builtin_handlers import llm_eval_handler
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)


def csl_llm_if_present(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Fail if none of the candidate files exist; otherwise defer to llm_eval.

    Uses the same ``files_to_include`` list as the LLM check, so list every
    candidate path for the control. When at least one exists, delegation to
    ``llm_eval_handler`` yields the INCONCLUSIVE + consultation result, which the
    orchestrator turns into PENDING (this handler is registered in the ``llm``
    phase). When none exist, this returns a conclusive FAIL and the sieve never
    reaches the model.
    """
    files = config.get("files_to_include", [])
    for f in files:
        full = f if os.path.isabs(f) else os.path.join(context.local_path, f)
        if os.path.isfile(full):
            return llm_eval_handler(config, context)

    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message="Required file is missing.",
    )


def register_sieve_handlers() -> None:
    """Register the step type under the plugin's name, so the registry records it as this plugin's (feature 044)."""
    registry = get_sieve_handler_registry()
    registry.set_plugin_context("community-spec")
    try:
        registry.register(
            "csl_llm_if_present",
            phase="llm",
            handler_fn=csl_llm_if_present,
            description="Fail if the target file is missing; otherwise defer to the LLM content check.",
            ceiling={"fail"},
            settings={"prompt", "confidence_threshold", "analysis_hints", "files_to_include"},
        )
    finally:
        registry.set_plugin_context(None)


register_sieve_handlers()
