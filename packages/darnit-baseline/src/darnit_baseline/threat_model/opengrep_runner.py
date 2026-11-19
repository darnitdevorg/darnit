"""Opengrep / Semgrep CLI invocation with graceful degradation.

Detects the binary at runtime via ``shutil.which`` (opengrep preferred,
semgrep fallback), invokes it with a fixed flag vector, parses the JSON
result, and **always** inspects ``data["errors"]`` even when the exit code
is 0 — rule-schema errors surface there silently otherwise.

See ``specs/010-threat-model-ast/contracts/opengrep-runner-contract.md`` for
the full behavioral contract.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("darnit_baseline.threat_model.opengrep_runner")


@dataclass(frozen=True)
class OpengrepResult:
    """Result of a single Opengrep invocation.

    ``available`` is True iff the binary was located and invoked successfully
    (even if that invocation produced errors or zero findings). It is False
    when the binary is missing.

    ``rule_errors`` is populated from ``data["errors"]`` in the JSON response
    and reflects rule-schema problems (NOT scan failures — those end up in
    ``degraded_reason``).
    """

    available: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    rule_errors: list[dict[str, Any]] = field(default_factory=list)
    degraded_reason: str | None = None
    binary_used: str | None = None
    version: str | None = None
    scan_duration_s: float | None = None


def _detect_binary() -> tuple[str, str] | None:
    """Return ``(path, name)`` for the first available tool, or None.

    Prefers ``opengrep`` over ``semgrep``; their rule formats are compatible
    because Opengrep was forked from Semgrep CE 1.100.
    """
    for candidate in ("opengrep", "semgrep"):
        path = shutil.which(candidate)
        if path:
            return path, candidate
    return None


def _capture_version(binary: str) -> str | None:
    try:
        proc = subprocess.run(  # noqa: S603 - trusted binary, fixed args
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("failed to capture %s version: %s", binary, e)
    return None


def run_opengrep(
    target: Path,
    rules_dir: Path,
    timeout_s: int = 120,
) -> OpengrepResult:
    """Invoke Opengrep/Semgrep against ``target`` using rules from ``rules_dir``.

    Returns a populated :class:`OpengrepResult` describing whether the tool
    ran, what findings it produced, and any degradation reason. Never raises
    under normal operation — errors are captured in ``degraded_reason``.
    """

    detected = _detect_binary()
    if detected is None:
        reason = "opengrep/semgrep binary not installed on PATH"
        logger.info("opengrep degraded: %s", reason)
        return OpengrepResult(available=False, degraded_reason=reason)

    binary_path, binary_name = detected
    version = _capture_version(binary_path)

    if not rules_dir.is_dir():
        reason = f"rules directory not found: {rules_dir}"
        logger.warning("opengrep degraded: %s", reason)
        return OpengrepResult(
            available=True,
            degraded_reason=reason,
            binary_used=binary_name,
            version=version,
        )

    argv = [
        binary_path,
        "scan",
        "--json",
        "--quiet",
        "--disable-version-check",
        # Note: ``--metrics=off`` was removed because Opengrep (as of 1.6.0)
        # does not support the ``--metrics`` flag (it's Semgrep-specific).
        # Metrics are disabled via the ``SEMGREP_SEND_METRICS=off`` env var
        # instead, which both Opengrep and Semgrep honor.
        "--timeout",
        "10",
        "--timeout-threshold",
        "3",
        "--config",
        str(rules_dir),
        str(target),
    ]
    env = {**os.environ, "SEMGREP_SEND_METRICS": "off"}

    start = time.perf_counter()
    try:
        proc = subprocess.run(  # noqa: S603 - trusted binary, known args
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        reason = f"{binary_name} timed out after {timeout_s}s"
        logger.warning("opengrep degraded: %s", reason)
        return OpengrepResult(
            available=True,
            degraded_reason=reason,
            binary_used=binary_name,
            version=version,
            scan_duration_s=time.perf_counter() - start,
        )
    except (OSError, FileNotFoundError) as e:
        reason = f"{binary_name} failed to start: {e}"
        logger.warning("opengrep degraded: %s", reason)
        return OpengrepResult(
            available=True,
            degraded_reason=reason,
            binary_used=binary_name,
            version=version,
        )

    duration = time.perf_counter() - start

    if proc.returncode not in (0, 1):
        stderr_snippet = (proc.stderr or "")[:500]
        reason = f"{binary_name} exit {proc.returncode}: {stderr_snippet}"
        logger.warning("opengrep degraded: %s", reason)
        return OpengrepResult(
            available=True,
            degraded_reason=reason,
            binary_used=binary_name,
            version=version,
            scan_duration_s=duration,
        )

    try:
        data = json.loads(proc.stdout) if proc.stdout else {}
    except json.JSONDecodeError as e:
        reason = f"malformed JSON from {binary_name}: {e}"
        logger.warning("opengrep degraded: %s", reason)
        return OpengrepResult(
            available=True,
            degraded_reason=reason,
            binary_used=binary_name,
            version=version,
            scan_duration_s=duration,
        )

    findings = data.get("results", []) or []
    rule_errors = data.get("errors", []) or []

    # Critical invariant: inspect errors[] even on exit 0.
    degraded_reason: str | None = None
    if rule_errors:
        degraded_reason = (
            f"{len(rule_errors)} opengrep rule-schema error(s); findings from "
            f"unaffected rules were still returned"
        )
        for err in rule_errors:
            logger.warning(
                "opengrep rule error type=%s long_msg=%s",
                err.get("type"),
                err.get("long_msg") or err.get("message"),
            )

    logger.debug(
        "opengrep.run: binary=%s, findings=%d, rule_errors=%d, duration=%.2fs",
        binary_name,
        len(findings),
        len(rule_errors),
        duration,
    )
    return OpengrepResult(
        available=True,
        findings=findings,
        rule_errors=rule_errors,
        degraded_reason=degraded_reason,
        binary_used=binary_name,
        version=version,
        scan_duration_s=duration,
    )


def clean_opengrep_check_id(check_id: str) -> str:
    """Extract the clean rule id from Opengrep's check_id (#776).

    Opengrep prefixes each rule id with the path of the rules directory
    passed to --config (e.g. ``Users.<user>..local.share.....threat_model.opengrep_rules.darnit.datastore.sqlite``).
    This strips everything up to and including ``opengrep_rules.`` (or slash variants)
    and anchors to the canonical rule prefix if present.
    """
    if not check_id:
        return check_id

    for marker in ("opengrep_rules.", "opengrep_rules/", "opengrep_rules\\"):
        if marker in check_id:
            remainder = check_id.rsplit(marker, 1)[1]
            if ".darnit." in remainder:
                return "darnit." + remainder.split(".darnit.", 1)[1]
            return remainder

    return check_id


__all__ = ["OpengrepResult", "clean_opengrep_check_id", "run_opengrep"]
