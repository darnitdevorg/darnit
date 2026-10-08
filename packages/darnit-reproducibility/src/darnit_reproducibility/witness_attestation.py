"""Verified Witness / in-toto runtime-trace attestation check (``repro_witness_attestation``).

Unlike every other check in this plugin (pure local filesystem inspection),
this module reaches out to GitHub for the attestation artifacts of the CI runs
that built the audited commit, and cryptographically verifies them before
reading anything they claim. A JSON file that merely *says* "no network
access" is not evidence -- only a Sigstore-verified DSSE envelope signed by a
GitHub Actions workflow of this repository, running on the audited commit, is.

What is read from a verified statement (#553):

- ``runtime-trace/v0.1``, as the statement's predicate type or as an entry of
  a Witness ``attestation-collection/v0.1`` whose ``type`` is exactly that URI:
  ``monitorLog.network`` only. A non-empty list shows network access. An empty
  or absent list does NOT show its absence: under the in-toto parsing rules an
  absent optional list equals an empty one, and what the log records depends
  on ``monitor.type`` and its ``tracePolicy``, so a monitor that does not trace
  sockets records the same empty log.
- Witness ``command-run``: process ``program``/``cmdline`` scanned for the
  installer substrings also used by the CI-file scan in ``handlers.py``. A
  match shows network access; no match shows nothing.

So this check can produce FAIL evidence and nothing else. Every failure mode
(no ``gh`` CLI, no auth, no commit, no matching run or artifact, ``sigstore``
not installed, verification failure, unrecognized predicate) degrades to "no
attestation evidence" with the specific reason rather than raising.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger
from darnit.sieve.handler_registry import HandlerContext

logger = get_logger("darnit_reproducibility.witness_attestation")

try:
    from sigstore.models import Bundle
    from sigstore.verify import Verifier
    from sigstore.verify.policy import AllOf, GitHubWorkflowRepository, GitHubWorkflowSHA, OIDCIssuer

    SIGSTORE_VERIFY_AVAILABLE = True
except ImportError:
    SIGSTORE_VERIFY_AVAILABLE = False

GITHUB_ACTIONS_OIDC_ISSUER = "https://token.actions.githubusercontent.com"

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

_GH_TIMEOUT_SECONDS = 60
_GIT_TIMEOUT_SECONDS = 15
_MAX_RUNS = 5
_MAX_ARTIFACT_FILES = 20

_COMMIT_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

# Filenames ending in these suffixes are far more likely to be the actual
# attestation bundle than an incidental *.json artifact (e.g. a build log
# dumped as json) — check them first so the cap above can't skip past the
# real file on a repo with many "*witness*"-matched artifacts.
_PRIORITY_ARTIFACT_SUFFIXES: tuple[str, ...] = (".att.json", ".bundle.json", ".sigstore.json")

# Substrings gh prints to stderr on an auth failure — used to tell "you're not
# logged in" apart from "nothing found", which otherwise look identical (both
# are just "no candidate files") to the caller.
_AUTH_ERROR_HINTS: tuple[str, ...] = (
    "gh auth login",
    "not logged into",
    "authentication",
    "bad credentials",
    "401",
    "requires authentication",
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


@dataclass
class _GhOutcome:
    """Result of a single `gh` invocation, with a human-readable reason on failure."""

    proc: subprocess.CompletedProcess[str] | None
    reason: str | None = None


def _run_gh(args: list[str]) -> _GhOutcome:
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return _GhOutcome(None, "gh CLI not found in PATH")
    except subprocess.TimeoutExpired:
        return _GhOutcome(None, f"gh command timed out after {_GH_TIMEOUT_SECONDS}s")

    if proc.returncode == 0:
        return _GhOutcome(proc)

    stderr_lower = proc.stderr.lower()
    if any(hint in stderr_lower for hint in _AUTH_ERROR_HINTS):
        return _GhOutcome(None, "gh is not authenticated for this repository (run `gh auth login`)")
    return _GhOutcome(None, f"gh exited {proc.returncode}: {proc.stderr.strip()[:200]}")


def _head_commit(local_path: str) -> tuple[str | None, str | None]:
    """The audited commit: ``git rev-parse HEAD`` in the audited checkout.

    Returns (sha, failure_reason) -- exactly one is None.
    """
    if not local_path or not Path(local_path).is_dir():
        return None, "audited path is not a directory, so there is no commit to bind attestations to"
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=local_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return None, "git not found in PATH, so the audited commit is unknown"
    except subprocess.TimeoutExpired:
        return None, f"git rev-parse HEAD timed out after {_GIT_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return None, f"git rev-parse HEAD could not run: {exc}"
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not _COMMIT_SHA.fullmatch(sha):
        return (
            None,
            "audited path has no commit (git rev-parse HEAD failed), so there is nothing to bind attestations to",
        )
    return sha, None


def _successful_run_ids(owner: str, repo: str, sha: str) -> tuple[list[str], str | None]:
    """Successful CI runs for the audited commit.

    Returns (run_ids, failure_reason) -- run_ids is empty iff failure_reason is set.
    """
    outcome = _run_gh(
        [
            "run",
            "list",
            "--repo",
            f"{owner}/{repo}",
            "--commit",
            sha,
            "--status",
            "success",
            "--limit",
            str(_MAX_RUNS),
            "--json",
            "databaseId",
        ]
    )
    if outcome.proc is None:
        return [], outcome.reason
    if not outcome.proc.stdout:
        return [], "gh returned no output for the run list query"
    try:
        rows = json.loads(outcome.proc.stdout)
    except json.JSONDecodeError:
        return [], "gh returned unparseable output for the run list query"
    if not isinstance(rows, list) or not rows:
        return [], f"no successful CI run found for commit {sha[:12]}"
    run_ids = [str(row["databaseId"]) for row in rows if isinstance(row, dict) and row.get("databaseId")]
    if not run_ids:
        return [], f"successful runs for commit {sha[:12]} have no databaseId"
    return run_ids, None


def _order_candidates(files: list[Path]) -> list[Path]:
    priority = [f for f in files if f.name.endswith(_PRIORITY_ARTIFACT_SUFFIXES)]
    rest = [f for f in files if f not in priority]
    return (priority + rest)[:_MAX_ARTIFACT_FILES]


def _download_candidate_artifacts(owner: str, repo: str, run_id: str, dest: Path) -> tuple[list[Path], str | None]:
    """Returns (files, failure_reason) -- files is empty iff failure_reason is set."""
    dest.mkdir(parents=True, exist_ok=True)
    outcome = _run_gh(
        [
            "run",
            "download",
            run_id,
            "--repo",
            f"{owner}/{repo}",
            "--pattern",
            "*witness*",
            "--dir",
            str(dest),
        ]
    )
    if outcome.proc is None:
        return [], outcome.reason
    found = _order_candidates(sorted(dest.rglob("*.json")))
    if not found:
        return [], f"run {run_id} has no artifacts matching '*witness*'"
    return found, None


def _fetch_candidate_files(
    owner: str, repo: str, run_ids: list[str], scratch_dir: Path
) -> tuple[list[Path], str | None]:
    """Attestation artifacts of the given runs, priority files first, capped.

    Returns (files, failure_reason) -- files is empty iff failure_reason is set.
    """
    files: list[Path] = []
    reasons: list[str] = []
    for run_id in run_ids:
        found, reason = _download_candidate_artifacts(owner, repo, run_id, scratch_dir / run_id)
        files.extend(found)
        if reason and reason not in reasons:
            reasons.append(reason)
    candidates = _order_candidates(files)
    if not candidates:
        return [], "; ".join(reasons) or "no Witness attestation artifacts found"
    return candidates, None


def _verification_policy(owner: str, repo: str, sha: str) -> Any:
    """Signed by a GitHub Actions workflow of this repository, running on the audited commit."""
    return AllOf(
        [
            OIDCIssuer(GITHUB_ACTIONS_OIDC_ISSUER),
            GitHubWorkflowRepository(f"{owner}/{repo}"),
            GitHubWorkflowSHA(sha),
        ]
    )


def _verify_bundle(raw_bytes: bytes, owner: str, repo: str, sha: str) -> dict[str, Any] | None:
    """Verify a Sigstore-bundled DSSE envelope against the repository's GitHub
    Actions OIDC identity for the audited commit. Returns the decoded in-toto
    statement on success, or None if verification is unavailable or fails.
    """
    if not SIGSTORE_VERIFY_AVAILABLE:
        return None
    try:
        bundle = Bundle.from_json(raw_bytes)
    except Exception as exc:
        logger.debug("not a Sigstore bundle: %s", exc)
        return None

    try:
        payload_type, payload_bytes = Verifier.production().verify_dsse(bundle, _verification_policy(owner, repo, sha))
    except Exception as exc:
        logger.debug("Sigstore verification failed: %s", exc)
        return None

    if "in-toto" not in payload_type:
        return None
    try:
        statement = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return None
    return statement if isinstance(statement, dict) else None


def _decode_raw_dsse(raw_bytes: bytes) -> dict[str, Any] | None:
    """Fallback for a bare (unsigned or non-Sigstore-bundled) DSSE envelope.

    Only used to populate evidence for debugging — never treated as verified.
    """
    try:
        envelope = json.loads(raw_bytes)
        payload_b64 = envelope.get("payload")
        if not payload_b64:
            return None
        return json.loads(base64.b64decode(payload_b64))
    except Exception:
        return None


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


def check_witness_attestation(ctx: HandlerContext) -> WitnessCheckResult:
    """Fetch, verify, and inspect the attestations of the CI runs that built the audited commit.

    Returns a result with ``verified=False`` and the specific reason for any
    missing prerequisite. Never raises for a missing prerequisite.
    """
    if not SIGSTORE_VERIFY_AVAILABLE:
        return WitnessCheckResult(
            attempted=False,
            detail="sigstore not installed — install darnit-core[attestation] to enable",
        )
    if not ctx.owner or not ctx.repo:
        return WitnessCheckResult(attempted=False, detail="repository owner/name not available in this context")

    sha, reason = _head_commit(ctx.local_path)
    if sha is None:
        return WitnessCheckResult(attempted=False, detail=reason or "audited commit unknown")
    evidence: dict[str, Any] = {"commit": sha}

    run_ids, reason = _successful_run_ids(ctx.owner, ctx.repo, sha)
    if not run_ids:
        return WitnessCheckResult(attempted=True, detail=reason or "no successful CI run found", evidence=evidence)
    evidence["runs"] = run_ids

    with tempfile.TemporaryDirectory(prefix="darnit-witness-") as tmp:
        candidates, reason = _fetch_candidate_files(ctx.owner, ctx.repo, run_ids, Path(tmp))
        if not candidates:
            return WitnessCheckResult(
                attempted=True, detail=reason or "no Witness attestation artifacts found", evidence=evidence
            )

        checked_files: list[str] = []
        verified_artifacts: list[str] = []
        monitor_types: list[str] = []
        traced_without_network = False
        evidence.update(checked_files=checked_files, verified_artifacts=verified_artifacts, monitor_types=monitor_types)
        for f in candidates:
            checked_files.append(f.name)
            try:
                raw_bytes = f.read_bytes()
            except OSError as exc:
                logger.debug("could not read %s: %s", f, exc)
                continue

            statement = _verify_bundle(raw_bytes, ctx.owner, ctx.repo, sha)
            if statement is None:
                continue  # not verifiable — do not fall back to trusting unsigned content

            verified_artifacts.append(f.name)
            network_recorded, detail, types = _check_network_evidence(statement)
            monitor_types.extend(t for t in types if t not in monitor_types)
            if network_recorded:
                evidence["artifact"] = f.name
                return WitnessCheckResult(
                    attempted=True, verified=True, network_recorded=True, detail=detail, evidence=evidence
                )
            traced_without_network = traced_without_network or network_recorded is False

        if not verified_artifacts:
            return WitnessCheckResult(
                attempted=True,
                detail=(
                    "attestation artifact(s) found but none verified against the repo's GitHub Actions "
                    f"identity for commit {sha[:12]}"
                ),
                evidence=evidence,
            )

        evidence["artifact"] = verified_artifacts[0]
        if traced_without_network:
            return WitnessCheckResult(
                attempted=True,
                verified=True,
                network_recorded=False,
                detail="runtime-trace predicate recorded no network events",
                evidence=evidence,
            )
        return WitnessCheckResult(
            attempted=True,
            verified=True,
            detail="no runtime-trace network log or suspicious command line in verified attestation",
            evidence=evidence,
        )
