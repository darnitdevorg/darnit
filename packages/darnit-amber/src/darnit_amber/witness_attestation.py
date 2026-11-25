"""What the Witness attestations of an experiment's recorded runs show about network access (``repro_witness_attestation``).

The attestations are those of the `darnit-amber run`s of the audited commit, in the repository's bundle
(`.amber/`), and are read only after `rerun.verify` has checked the run: its signature (a key, or a
keyless Sigstore identity), and that Witness's attestation is the one the signed statement names. A JSON
file that merely *says* "no network access" is not evidence.

What is read from a verified Witness attestation (#553):

- ``runtime-trace/v0.1``, as the statement's predicate type or as an entry of a Witness
  ``attestation-collection/v0.1`` whose ``type`` is exactly that URI: ``monitorLog.network`` only. A
  non-empty list shows network access. An empty or absent list does NOT show its absence: under the
  in-toto parsing rules an absent optional list equals an empty one, and what the log records depends
  on ``monitor.type`` and its ``tracePolicy``, so a monitor that does not trace sockets records the same
  empty log.
- Witness ``command-run``: process ``program``/``cmdline`` scanned for the installer substrings also
  used by the CI-file scan in ``handlers.py``. A match shows network access; no match shows nothing.

So this check can produce FAIL evidence and nothing else. A missing bundle, no run of the commit, or a
run that does not verify degrades to "no attestation evidence" with the reason, rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from darnit.sieve.handler_registry import HandlerContext

from .rerun import verify_commit_runs
from .utils import DEFAULT_BUNDLE, head_commit, payload

_WITNESS_COLLECTION_TYPE = "https://witness.dev/attestation-collection/v0.1"
_RUNTIME_TRACE_TYPE = "https://in-toto.io/attestation/runtime-trace/v0.1"

# Same substrings as handlers._SUSPICIOUS_PATTERNS, duplicated deliberately:
# this is a best-effort fallback over attacker-influenced process cmdlines
# from a *different* data source (Witness command-run), not the CI-file scan.
_SUSPICIOUS_CMDLINE_PATTERNS: tuple[str, ...] = (
    "curl ",
    "wget ",
    "pip install ",
    "npm install",
    "yarn install",
    "apt-get install",
    "brew install",
)


@dataclass
class WitnessCheckResult:
    """Outcome of attempting to verify Witness/runtime-trace attestations.

    ``network_recorded`` is True only when a verified attestation recorded
    network access during the build. False means a verified runtime trace
    recorded no network events, which is not proof that none happened (see the
    module docstring). None means no verified runtime trace and no suspicious
    command line was found.
    """

    attempted: bool
    verified: bool = False
    network_recorded: bool | None = None
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def _nested_attestations(statement: dict[str, Any]) -> list[dict[str, Any]]:
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        return []
    if statement.get("predicateType") == _WITNESS_COLLECTION_TYPE:
        entries = predicate.get("attestations")
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    return [{"type": statement.get("predicateType", ""), "attestation": predicate}]


def _monitor_type(trace: dict[str, Any]) -> str | None:
    monitor = trace.get("monitor")
    if isinstance(monitor, dict) and isinstance(monitor.get("type"), str):
        return monitor["type"]
    return None


def _check_network_evidence(statement: dict[str, Any]) -> tuple[bool | None, str, list[str]]:
    """Inspect a verified in-toto statement for evidence of network access.

    Returns ``(network_recorded, detail, monitor_types)``:
    - ``True``  -- a runtime-trace ``monitorLog.network`` list is non-empty, or
      a command-run process command line matched a suspicious pattern.
    - ``False`` -- a runtime trace was present and recorded no network events.
      Not proof of no network access (see the module docstring).
    - ``None``  -- no runtime trace and nothing suspicious.

    Only a predicate whose type is exactly the runtime-trace URI is read for
    network events; a ``network`` key under any other predicate type is ignored.
    """
    monitor_types: list[str] = []
    traced_without_network = False
    for entry in _nested_attestations(statement):
        entry_type = entry.get("type", "")
        payload = entry.get("attestation")
        if not isinstance(entry_type, str) or not isinstance(payload, dict):
            continue

        if entry_type == _RUNTIME_TRACE_TYPE:
            monitor_type = _monitor_type(payload)
            if monitor_type:
                monitor_types.append(monitor_type)
            monitor_log = payload.get("monitorLog")
            network_events = monitor_log.get("network") if isinstance(monitor_log, dict) else None
            if network_events is None or network_events == []:
                traced_without_network = True
            elif isinstance(network_events, list):
                return (
                    True,
                    f"runtime-trace predicate recorded {len(network_events)} network event(s) "
                    f"(monitor: {monitor_type or 'unknown'})",
                    monitor_types,
                )
            continue

        if "command-run" in entry_type or "commandrun" in entry_type:
            processes = payload.get("processes")
            for proc in processes if isinstance(processes, list) else []:
                if not isinstance(proc, dict):
                    continue
                haystack = f"{proc.get('program', '')} {proc.get('cmdline', '')}"
                for pattern in _SUSPICIOUS_CMDLINE_PATTERNS:
                    if pattern in haystack:
                        return (
                            True,
                            f"command-run process matched '{pattern.strip()}': {haystack.strip()[:120]}",
                            monitor_types,
                        )

    if traced_without_network:
        return False, "runtime-trace predicate recorded no network events", monitor_types
    return None, "no runtime-trace network log or suspicious command line in verified attestation", monitor_types


def verified_attestations(checkout: Path) -> tuple[list[tuple[str, dict[str, Any]]], str, dict[str, Any]]:
    """
    The Witness attestations (in-toto statements) of the verified runs of the checkout's commit, by run id,
    with a reason when there are none, and the evidence of what was looked at.
    """
    commit = head_commit(checkout)
    if commit is None:
        return [], "the audited checkout has no commit", {}
    evidence: dict[str, Any] = {"commit": commit}

    runs = verify_commit_runs(checkout / DEFAULT_BUNDLE, commit)
    if not runs:
        return [], f"no darnit-amber run of commit {commit[:12]} in {DEFAULT_BUNDLE}/", evidence
    evidence["runs"] = {run_id[:12]: r["report"]["verified"] for run_id, r in runs.items()}

    verified = [(run_id, payload(r["witness_envelope"])) for run_id, r in runs.items() if r["report"]["verified"]]
    if not verified:
        return [], f"no run of commit {commit[:12]} verifies", evidence
    return verified, "", evidence


def check_witness_attestation(ctx: HandlerContext) -> WitnessCheckResult:
    """Read the verified Witness attestations of the audited commit's recorded runs for network access."""
    statements, reason, evidence = verified_attestations(Path(ctx.local_path))
    if not statements:
        return WitnessCheckResult(attempted=True, detail=reason, evidence=evidence)

    monitor_types: list[str] = []
    traced_without_network = False
    evidence.update(monitor_types=monitor_types, artifact=statements[0][0][:12])
    for run_id, statement in statements:
        network_recorded, detail, types = _check_network_evidence(statement)
        monitor_types.extend(t for t in types if t not in monitor_types)
        if network_recorded:
            evidence["artifact"] = run_id[:12]
            return WitnessCheckResult(
                attempted=True, verified=True, network_recorded=True, detail=detail, evidence=evidence
            )
        traced_without_network = traced_without_network or network_recorded is False

    if traced_without_network:
        detail = "runtime-trace predicate recorded no network events"
        return WitnessCheckResult(
            attempted=True, verified=True, network_recorded=False, detail=detail, evidence=evidence
        )
    detail = "no runtime-trace network log or suspicious command line in the verified attestations"
    return WitnessCheckResult(attempted=True, verified=True, detail=detail, evidence=evidence)
