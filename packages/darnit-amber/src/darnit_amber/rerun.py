"""
`darnit-amber verify` checks a stored run.
`darnit-amber rerun` repeats a verified one.

A rerun runs the same command at the same commit, in the image its environment lock rebuilds (or, with
`host_environment`, on this machine, traced), and compares the results. It is kept in
`<bundle>/reruns/<time>-<id>/`:

  <name>/               the clone the command ran in, named after the experiment (the CLI opens a shell there)
  Dockerfile            the image it ran in
  commands.log          every command amber ran, with its output
  result.json           the comparison
  key.pub, runs/<id>/   only when signed (`sign`): the rerun recorded as a run of its own, carrying the comparison
"""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .environment import build_image, diff_locks, dockerfile, lock_matches_trace
from .run import observe, record
from .utils import (
    PAYLOAD_TYPE,
    PUBLIC_KEY_FILE,
    TSA_URL,
    RunError,
    amber_record,
    canonical,
    exit_code,
    experiment_argv,
    key_fingerprint,
    output_path,
    read_run,
    run_dir,
    sha256,
    signature_ok,
    timestamps,
    verify_keyless,
    witness_attestations,
)


def verify(
    bundle: Path,
    run_id: str,
    *,
    pubkey: Path | None = None,
    identity: str | None = None,
    issuer: str | None = None,
) -> dict[str, Any]:
    """
    Every check a stored run must pass, each true or false; `verified` only when all are true.

    Who must have signed it, as the verifier knows them (not as the run says):
      pubkey:            a run signed with a key: its public half, which signed both envelopes
      identity, issuer:  a run signed keyless: the signer's identity (an email address, or a CI workflow's
                         URI) and the issuer of the login (e.g. https://github.com/login/oauth)
    """
    from cryptography.hazmat.primitives import serialization

    statement, envelope, witness_envelope = read_run(bundle, run_id)
    predicate = statement["predicate"]
    checks: dict[str, Any] = {}

    # The id is the statement's digest, the envelope carries exactly that statement, and the statement
    # names Witness's envelope by digest, so neither line of the bundle can be swapped.
    checks["id_matches_statement"] = sha256(canonical(statement)) == run_id
    checks["statement_signed"] = (
        envelope.get("payloadType") == PAYLOAD_TYPE
        and envelope["payload"] == base64.b64encode(canonical(statement)).decode()
    )
    try:
        witness_payload = base64.b64decode(witness_envelope["payload"])
        attestations = witness_attestations(witness_envelope)
    except Exception:  # noqa: BLE001 - unreadable
        witness_payload, attestations = b"", {}
    checks["witness_matches_statement"] = sha256(witness_payload) == predicate["witness"]["payload_sha256"]

    # What Witness saw is what the statement says: the command, its exit code, its outputs.
    command_run = attestations.get("command-run") or {}
    products = {path: d.get("digest", {}).get("sha256") for path, d in (attestations.get("product") or {}).items()}
    checks["command_matches_witness"] = command_run.get("cmd") == experiment_argv(
        predicate["command"], predicate["runner"]
    )
    checks["exit_code_matches_witness"] = exit_code(command_run.get("stdout") or "") == predicate["exit_code"]
    checks["outputs_match_witness"] = bool(attestations) and all(
        products.get(path) == digest for path, digest in predicate["outputs"].items()
    )

    # The copies of the outputs in the run's directory are those outputs.
    try:
        copies = {path: output_path(run_dir(bundle, run_id), path) for path in predicate["outputs"]}
        checks["output_copies_match"] = all(
            digest is None or (copies[path].is_file() and sha256(copies[path].read_bytes()) == digest)
            for path, digest in predicate["outputs"].items()
        )
    except RunError:
        checks["output_copies_match"] = False

    # The environment lock describes what Witness traced.
    if predicate["environment"]:
        problems = lock_matches_trace(predicate["environment"], command_run)
        checks["environment_matches_trace"] = not problems
        checks["environment_problems"] = problems[:20]

    # Signed keyless: sigstore checks the bundle (a Fulcio certificate for the identity, the Rekor entry,
    # the signature). Witness's envelope, signed with a throwaway key, is bound by its digest above.
    signing = predicate["signing"]
    if signing.get("method") == "sigstore":
        record = json.loads(amber_record(run_dir(bundle, run_id)).read_text())
        named = (signing.get("identity"), signing.get("issuer"))  # the statement names its signer too: the same
        checks["signatures_verified"] = (
            identity is not None
            and issuer is not None
            and (identity, issuer) == named
            and verify_keyless(record, identity, issuer) == canonical(statement)
        )
        checks["verified"] = all(v for v in checks.values() if isinstance(v, bool))
        return {"id": run_id, "subject": statement["subject"][0], "signer": signing, **checks}

    # Signed with a key: both envelopes, every signature timestamped by a trusted authority, verify with it.
    envelopes = {"statement": envelope, "witness": witness_envelope}
    checks["timestamps"] = {name: timestamps(e) for name, e in envelopes.items()}
    checks["timestamps_trusted"] = all(
        e.get("signatures")
        and {t["signature"] for t in checks["timestamps"][name] if t["trusted"]} >= set(range(len(e["signatures"])))
        for name, e in envelopes.items()
    )
    public_key = serialization.load_pem_public_key(pubkey.read_bytes()) if pubkey else None
    checks["signatures_verified"] = (
        pubkey is not None
        and key_fingerprint(pubkey) == signing.get("key_fingerprint")
        and all(signature_ok(e, public_key) for e in envelopes.values())
    )

    checks["verified"] = all(v for v in checks.values() if isinstance(v, bool))
    return {"id": run_id, "subject": statement["subject"][0], "signer": signing, **checks}


def verify_commit_runs(bundle: Path, commit: str) -> dict[str, dict[str, Any]]:
    """
    Every run in `bundle` of `commit`, verified against the signer it names: run id -> {statement,
    witness_envelope, report, signer}. That shows a record was not changed since it was signed, not who
    signed it: the caller decides whom it trusts. An unreadable run is included, as one that does not verify.
    """
    runs: dict[str, dict[str, Any]] = {}
    for directory in sorted((bundle / "runs").glob("*/")):
        try:
            statement, _, witness_envelope = read_run(bundle, directory.name)
        except RunError as e:
            runs[directory.name] = {"statement": None, "report": {"verified": False, "error": str(e)}, "signer": None}
            continue
        if statement["subject"][0].get("digest", {}).get("gitCommit") != commit:
            continue

        # The signer the run names: a key (the bundle's key.pub) or a keyless identity.
        signing = statement["predicate"].get("signing") or {}
        if signing.get("method") == "sigstore":
            signer = expected = {"identity": signing.get("identity"), "issuer": signing.get("issuer")}
        else:
            key = bundle / PUBLIC_KEY_FILE
            expected = {"pubkey": key}
            signer = {"key_fingerprint": key_fingerprint(key) if key.is_file() else None}
        try:
            report = verify(bundle, directory.name, **expected)
        except Exception as e:  # noqa: BLE001 - a run that cannot be checked does not verify
            report = {"verified": False, "error": f"{type(e).__name__}: {e}"}
        runs[directory.name] = {
            "statement": statement,
            "witness_envelope": witness_envelope,
            "report": report,
            "signer": signer,
        }
    return runs


def failed(report: dict[str, Any]) -> list[str]:
    """The names of the checks a verify report failed."""
    return [name for name, ok in report.items() if ok is False and name != "verified"]


def rerun(
    bundle: Path,
    run_id: str,
    consent: Callable[[str, str | None], bool],
    *,
    key: Path | None = None,
    pubkey: Path | None = None,
    identity: str | None = None,
    issuer: str | None = None,
    source: str | None = None,
    tsa: str | None = TSA_URL,
    host_environment: bool = False,
    sign: bool = False,
) -> dict[str, Any]:
    """
    Verify a run, ask ``consent(command, dockerfile)``, and run it again. Returns the comparison, plus the image.

    sign:                      record the rerun as a signed run of its own (by default it is only compared)
    key:                       the rerunner's signing key for that record (None: keyless)
    pubkey, identity, issuer:  who must have signed the run (see verify)
    """
    # 1. Only a run that verifies is repeated.
    report = verify(bundle, run_id, pubkey=pubkey, identity=identity, issuer=issuer)
    if not report["verified"]:
        raise RunError(f"run {run_id} does not verify ({', '.join(failed(report))}); nothing from it runs")
    signer = report["signer"].get("identity") or report["signer"].get("key_fingerprint", "")[:16]
    print(f"amber: run {run_id[:12]} verified (signed by {signer})", file=sys.stderr)

    # 2. What it ran: the command, the commit, the environment.
    statement, _, _ = read_run(bundle, run_id)
    subject, first = statement["subject"][0], statement["predicate"]
    lock = first["environment"]
    if source is None and subject["name"].startswith("local/"):
        raise RunError(f"the run names {subject['name']}, which records no path; pass --source")
    if lock is None and not host_environment:
        raise RunError("the run has no environment lock to rebuild (it was not traced); pass --host-environment")

    # 3. Show the researcher what will run, and where.
    recipe = None if lock is None or host_environment else dockerfile(lock)
    if not consent(first["command"], recipe):
        raise RunError("rerun not confirmed")

    # 4. Run it again in its own directory, built image first.
    here = (bundle / "reruns" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{run_id[:12]}").resolve()
    here.mkdir(parents=True)
    checkout = here / (Path(subject["name"].rstrip("/")).name.removesuffix(".git") or "checkout")
    log = here / "commands.log"
    if recipe:
        (here / "Dockerfile").write_text(recipe)
    try:
        image = None
        if recipe and lock:
            print("amber: building the image from the run's environment... ", end="", file=sys.stderr, flush=True)
            image = build_image(lock, log)
            print("done", file=sys.stderr)
        observed = observe(
            source or subject["name"],
            first["command"],
            key,
            checkout,
            commit=subject["digest"]["gitCommit"],
            results=list(first["outputs"]),
            tsa=tsa,
            image=image,
            log=log,
        )
    except RunError as e:
        raise RunError(f"{e}\n(rerun state: {here})") from e

    # 5. Compare; with `sign`, record the rerun as a run that carries the comparison.
    comparison = _compare(run_id, statement, lock, observed, image)
    new_id = record(observed, key, here, tsa=tsa, reruns=comparison)["id"] if sign else None
    result = {"id": new_id, "dir": str(here), "exit_code": observed["exit_code"], **comparison}
    (here / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result | {"image": image, "checkout": checkout}


def _compare(
    run_id: str,
    statement: dict[str, Any],
    lock: dict[str, Any] | None,
    observed: dict[str, Any],
    image: dict[str, Any] | None,
) -> dict[str, Any]:
    """The rerun against the run it repeats: which outputs changed, how the environments differ, and a grade.

    drift                     an output changed
    environment_not_compared  outputs identical; no second environment to compare with
    same_environment          outputs identical, in an environment with the same packages and files
    different_environment     outputs identical, in an environment that differs (``diff`` says how)
    """
    first, now = statement["predicate"]["outputs"], observed["outputs"]
    changed = [path for path, digest in first.items() if now.get(path) != digest]

    if image:
        diff = image["diff"]  # build_image compared the image with the lock
    elif lock and observed["lock"]:
        diff = diff_locks(lock, observed["lock"])  # a traced rerun on this machine
    else:
        diff = None

    if changed:
        grade = "drift"
    elif diff is None:
        grade = "environment_not_compared"
    else:
        grade = "same_environment" if diff["identical"] else "different_environment"

    image_info = {k: image[k] for k in ("runtime", "image", "platform", "dockerfile")} if image else None
    return {"of": run_id, "changed": changed, "grade": grade, "image": image_info, "diff": diff}
