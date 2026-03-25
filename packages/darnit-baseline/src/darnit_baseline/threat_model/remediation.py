"""Sieve remediation handler for generating dynamic STRIDE threat models.

This handler wraps the existing threat model analysis pipeline as a
sieve remediation handler, replacing the static file_create + template
approach for SA-03.02. On analysis failure, falls back to the static
template content (pre-resolved by the executor).
"""

from __future__ import annotations

import os
from typing import Any

from darnit.core.logging import get_logger
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)

logger = get_logger("threat_model.remediation")


def generate_threat_model_handler(
    config: dict[str, Any],
    context: HandlerContext,
) -> HandlerResult:
    """Generate a dynamic STRIDE threat model for remediation.

    Runs the full analysis pipeline (framework detection, asset discovery,
    threat analysis, attack chain detection) and writes a detailed Markdown
    report. Falls back to static template content on analysis failure.

    Config fields:
        path: str - Output file path relative to repository root
        overwrite: bool - Whether to overwrite existing file (default: false)
        content: str - Pre-resolved template content (fallback, provided by executor)

    Context fields:
        local_path: str - Repository root path

    Returns:
        HandlerResult with PASS on success, ERROR on unrecoverable failure.
    """
    path = config.get("path", "")
    if not path:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="No path specified for threat model generation",
        )

    local_path = context.local_path
    full_path = os.path.join(local_path, path)

    # Respect overwrite flag
    if os.path.exists(full_path) and not config.get("overwrite", False):
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Threat model already exists: {path}",
            evidence={"path": path, "action": "skipped"},
        )

    # Try dynamic analysis
    try:
        content = _run_dynamic_analysis(local_path)
    except Exception as exc:
        logger.warning(
            "Dynamic threat model analysis failed, falling back to template: %s",
            exc,
        )
        # Fall back to static template content
        fallback_content = config.get("content", "")
        if not fallback_content:
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=f"Dynamic analysis failed and no template content available: {exc}",
                evidence={"path": path, "error": str(exc)},
            )

        try:
            os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(fallback_content)
        except OSError as write_err:
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=f"Failed to write fallback template: {write_err}",
                evidence={"path": path, "error": str(write_err)},
            )

        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Dynamic analysis unavailable — created from template: {path}",
            confidence=1.0,
            evidence={"path": path, "action": "created_from_template", "fallback_reason": str(exc)},
        )

    # Write dynamic report
    try:
        os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Failed to write threat model: {e}",
            evidence={"path": path, "error": str(e)},
        )

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"Generated dynamic threat model: {path}",
        confidence=1.0,
        evidence={"path": path, "action": "created"},
    )


def _run_dynamic_analysis(repo_path: str) -> str:
    """Run the full STRIDE analysis pipeline and return Markdown content.

    This reuses the same analysis pipeline as the generate_threat_model MCP tool.

    Args:
        repo_path: Absolute path to the repository

    Returns:
        Markdown-formatted threat model report

    Raises:
        Exception: If any step of the analysis pipeline fails
    """
    from .chains import detect_attack_chains
    from .discovery import (
        detect_frameworks,
        discover_all_assets,
        discover_injection_sinks,
    )
    from .generators import generate_markdown_threat_model
    from .stride import analyze_stride_threats, identify_control_gaps

    frameworks = detect_frameworks(repo_path)
    assets = discover_all_assets(repo_path, frameworks)
    injection_sinks = discover_injection_sinks(repo_path)
    threats = analyze_stride_threats(assets, injection_sinks)
    attack_chains = detect_attack_chains(threats, assets)
    control_gaps = identify_control_gaps(assets, threats)

    return generate_markdown_threat_model(
        repo_path,
        assets,
        threats,
        control_gaps,
        frameworks,
        detail_level="detailed",
        attack_chains=attack_chains,
    )


__all__ = [
    "generate_threat_model_handler",
]
