"""Verified Witness/in-toto runtime attestation check for RE-02.01.

Unlike every other check in this plugin (pure local filesystem inspection),
this module reaches out to GitHub to fetch the latest CI run's attestation
artifacts and cryptographically verifies them before trusting anything they
claim. A JSON file that merely *says* "no network access" is not evidence —
only a Sigstore-verified DSSE envelope bound to the repo's GitHub Actions
OIDC identity is.

Two predicate shapes are recognized:

- Witness's own ``attestation-collection/v0.1``, whose nested ``command-run``
  attestation records ``processes[].cmdline``/``program`` (and opened file
  digests) but has **no dedicated network field** — Witness's built-in tracer
  does not observe sockets. For this shape we can only fall back to scanning
  process command lines for the same suspicious substrings used by the grep
  heuristic in ``handlers.py``, which is not an authoritative "no network
  access" claim, only a negative-evidence hint.
- The newer, monitor-agnostic ``runtime-trace/v0.1`` predicate, which *does*
  define a top-level ``network`` array. An empty array is treated as an
  authoritative "no network access" claim; a non-empty one is authoritative
  evidence of network access. (The spec still defers the internal shape of
  each event to ``monitor.type``, so we only rely on emptiness, not content.)

Every failure mode here (no ``gh`` CLI, no auth, no matching run/artifact,
``sigstore`` not installed, verification failure, unrecognized predicate)
degrades to "no attestation evidence" rather than raising — this must never
be able to fail an audit outright.
"""

from __future__ import annotations

import base64
import json
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
    from sigstore.verify.policy import AllOf, GitHubWorkflowRepository, OIDCIssuer

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
_MAX_ARTIFACT_FILES = 5

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
    """Outcome of attempting to verify a Witness/runtime-trace attestation."""

    attempted: bool
    verified: bool = False
    network_clean: bool | None = None  # True/False = authoritative; None = no authoritative signal
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


def _latest_successful_run_id(owner: str, repo: str, branch: str) -> tuple[str | None, str | None]:
    """Returns (run_id, failure_reason) — exactly one is None."""
    outcome = _run_gh(
        [
            "run",
            "list",
            "--repo",
            f"{owner}/{repo}",
            "--branch",
            branch,
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId",
        ]
    )
    if outcome.proc is None:
        return None, outcome.reason
    if not outcome.proc.stdout:
        return None, "gh returned no output for the run list query"
    try:
        rows = json.loads(outcome.proc.stdout)
    except json.JSONDecodeError:
        return None, "gh returned unparseable output for the run list query"
    if not rows:
        return None, f"no successful CI run found on branch '{branch}'"
    run_id = rows[0].get("databaseId")
    if not run_id:
        return None, "latest successful run has no databaseId"
    return str(run_id), None


def _download_candidate_artifacts(owner: str, repo: str, run_id: str, dest: Path) -> tuple[list[Path], str | None]:
    """Returns (files, failure_reason) — files is empty iff failure_reason is set."""
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
    found = sorted(dest.rglob("*.json"))[:_MAX_ARTIFACT_FILES]
    if not found:
        return [], f"run {run_id} has no artifacts matching '*witness*'"
    return found, None


def _fetch_candidate_files(ctx: HandlerContext, scratch_dir: Path) -> tuple[list[Path], str | None]:
    """Best-effort fetch of Witness attestation artifacts from the latest CI run.

    Returns (files, failure_reason) — files is empty iff failure_reason is set.
    """
    if not ctx.owner or not ctx.repo:
        return [], "repository owner/name not available in this context"
    run_id, reason = _latest_successful_run_id(ctx.owner, ctx.repo, ctx.default_branch)
    if not run_id:
        return [], reason
    return _download_candidate_artifacts(ctx.owner, ctx.repo, run_id, scratch_dir)


def _verify_bundle(raw_bytes: bytes, owner: str, repo: str) -> dict[str, Any] | None:
    """Verify a Sigstore-bundled DSSE envelope against the repo's GitHub
    Actions OIDC identity. Returns the decoded in-toto statement on success,
    or None if verification is unavailable or fails.
    """
    if not SIGSTORE_VERIFY_AVAILABLE:
        return None
    try:
        bundle = Bundle.from_json(raw_bytes)
    except Exception as exc:
        logger.debug("not a Sigstore bundle: %s", exc)
        return None

    policy = AllOf(
        [
            OIDCIssuer(GITHUB_ACTIONS_OIDC_ISSUER),
            GitHubWorkflowRepository(f"{owner}/{repo}"),
        ]
    )

    try:
        payload_type, payload_bytes = Verifier.production().verify_dsse(bundle, policy)
    except Exception as exc:
        logger.debug("Sigstore verification failed: %s", exc)
        return None

    if "in-toto" not in payload_type:
        return None
    try:
        return json.loads(payload_bytes)
    except json.JSONDecodeError:
        return None


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
    predicate = statement.get("predicate", {})
    if statement.get("predicateType") == _WITNESS_COLLECTION_TYPE:
        return predicate.get("attestations", [])
    return [{"type": statement.get("predicateType", ""), "attestation": predicate}]


def _check_network_cleanliness(statement: dict[str, Any]) -> tuple[bool | None, str]:
    """Inspect a verified in-toto statement for network-access evidence.

    Returns ``(network_clean, detail)``:
    - ``(True, ...)``  — authoritative: a runtime-trace ``network`` array was
      present and empty.
    - ``(False, ...)`` — authoritative: a non-empty ``network`` array, or a
      command-run process cmdline matched a suspicious pattern.
    - ``(None, ...)``  — no authoritative signal (command-run only, nothing
      suspicious found — absence of evidence, not evidence of absence).
    """
    for entry in _nested_attestations(statement):
        entry_type = entry.get("type", "")
        payload = entry.get("attestation", {})

        if "runtime-trace" in entry_type or "network" in payload:
            network_events = payload.get("monitorLog", {}).get("network", payload.get("network"))
            if network_events is not None:
                if len(network_events) == 0:
                    return True, "runtime-trace predicate recorded an empty network log"
                return False, f"runtime-trace predicate recorded {len(network_events)} network event(s)"

        if "command-run" in entry_type or "commandrun" in entry_type:
            for proc in payload.get("processes", []) or []:
                haystack = f"{proc.get('program', '')} {proc.get('cmdline', '')}"
                for pattern in _SUSPICIOUS_CMDLINE_PATTERNS:
                    if pattern in haystack:
                        return False, f"command-run process matched '{pattern.strip()}': {haystack.strip()[:120]}"

    return None, "no authoritative network signal in verified attestation"


def check_witness_attestation(ctx: HandlerContext) -> WitnessCheckResult:
    """Fetch, verify, and inspect the latest CI run's Witness attestation.

    Returns a result with ``verified=False`` (and no PASS-worthy signal) for
    any missing prerequisite. Never raises.
    """
    if not SIGSTORE_VERIFY_AVAILABLE:
        return WitnessCheckResult(
            attempted=False,
            detail="sigstore not installed — install darnit-core[attestation] to enable",
        )

    with tempfile.TemporaryDirectory(prefix="darnit-witness-") as tmp:
        candidates, reason = _fetch_candidate_files(ctx, Path(tmp))
        if not candidates:
            return WitnessCheckResult(attempted=True, detail=reason or "no Witness attestation artifacts found")

        checked_files: list[str] = []
        for f in candidates:
            checked_files.append(f.name)
            try:
                raw_bytes = f.read_bytes()
            except OSError as exc:
                logger.debug("could not read %s: %s", f, exc)
                continue

            statement = _verify_bundle(raw_bytes, ctx.owner, ctx.repo)
            if statement is None:
                continue  # not verifiable — do not fall back to trusting unsigned content

            network_clean, detail = _check_network_cleanliness(statement)
            return WitnessCheckResult(
                attempted=True,
                verified=True,
                network_clean=network_clean,
                detail=detail,
                evidence={"artifact": f.name, "checked_files": checked_files},
            )

        return WitnessCheckResult(
            attempted=True,
            detail="attestation artifact(s) found but none verified against the repo's GitHub Actions identity",
            evidence={"checked_files": checked_files},
        )
