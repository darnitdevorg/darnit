"""
`darnit-amber run`: run an experiment under Witness and store a signed record of it (darnit #677).

The experiment is not changed: amber clones its source, runs the command there, and writes everything it
records into a bundle (utils.py; default `<source>/.amber/`). A run is `<bundle>/runs/<id>/`:

  amber.sigstore.json  amber's statement (predicate PREDICATE_TYPE): the command, its exit code, the digests
                       of its results, the environment lock, and the digest of Witness's statement. Signed
                       keyless by default: a Sigstore bundle for the researcher's identity (utils.py).
  amber.intoto.json    the same statement, instead, when signed with a key (`--key`): a DSSE envelope
  witness.intoto.json  Witness's attestation collection: git, materials, products, the command's stdout
                       and, when traced, every file each process opened. Witness signs it with the key, or
                       keyless with a key made for this run alone; either way the statement binds it by digest.
  outputs/<path>       copies of the results (the files named with `--results`), so they travel with the run

The run's id is the sha256 of amber's statement.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .environment import build_lock, docker_run
from .utils import (
    AMBER_FILE,
    DEFAULT_BUNDLE,
    ENV_ALLOWLIST,
    EXIT_MARKER,
    PAYLOAD_TYPE,
    PREDICATE_TYPE,
    PUBLIC_KEY_FILE,
    SIGSTORE_FILE,
    TSA_URL,
    WITNESS_FILE,
    RunError,
    call,
    canonical,
    exit_code,
    experiment_argv,
    identity_token,
    key_fingerprint,
    output_path,
    public_key_pem,
    run_dir,
    sha256,
    sign_keyless,
    witness_attestations,
)

# The default bundle lives inside the source, so the clean-checkout check ignores it (it is never committed).
EXCLUDE_BUNDLE = f":(exclude){DEFAULT_BUNDLE}"


def run(
    source: str,
    key: Path | None,
    command: str,
    bundle: Path,
    *,
    results: list[str] | None = None,
    tsa: str | None = TSA_URL,
    trace: bool | None = None,
    record_failure: bool = False,
) -> dict[str, Any]:
    """
    Run `command` in a fresh clone of `source` under Witness, then sign and store the record in `bundle`.

    key:             the researcher's signing key; None signs keyless, as the identity they sign in with after the run
    record_failure:  record the run even if the command fails (by default a failing run is not recorded)
    """
    with tempfile.TemporaryDirectory(prefix="amber-run-") as tmp:
        observed = observe(source, command, key, Path(tmp) / "checkout", results=results, tsa=tsa, trace=trace)

    # A command that failed is usually a mistake (a wrong path, a missing file), not a result worth signing.
    if observed["exit_code"] != 0 and not record_failure:
        raise RunError("nothing recorded. To record a failing run on purpose, run it again with --record-failure.")
    return record(observed, key, bundle, tsa=tsa)


def observe(
    source: str,
    command: str,
    key: Path | None,
    checkout: Path,
    *,
    commit: str | None = None,
    results: list[str] | None = None,
    tsa: str | None = TSA_URL,
    trace: bool | None = None,
    image: dict[str, Any] | None = None,
    log: Path | None = None,
) -> dict[str, Any]:
    """
    Clone `source` into `checkout`, run `command` there under Witness, and return what it saw.

    commit:    the commit to run (default: HEAD of a local checkout, which must then be clean)
    results:   the files, or directories of files, the command writes that are its results: recorded by
               digest, copied into the run, and compared by a rerun (default: none)
    trace:     record every file the command reads, for the environment lock (default: on Linux,
               the only place Witness can trace)
    image:     run inside this image (a rerun); Witness then runs here, untraced, around `docker run`
    log:       file that gets every command run and its output
    """

    if not shutil.which("witness"):
        raise RunError("witness binary not found on PATH (https://github.com/in-toto/witness)")
    trace = (sys.platform.startswith("linux") if trace is None else trace) and image is None
    checkout = checkout.resolve()

    # 1. A fresh clone, so the experiment reads only what the commit holds.
    subject = _clone(source, commit, checkout)
    commit = call(["git", "-C", str(checkout), "rev-parse", "HEAD"]).stdout.strip()
    where = " in the image" if image else (" (traced)" if trace else "")
    print(f"amber: running `{command}` at commit {commit[:7]}{where}", file=sys.stderr)

    # 2. Witness runs the command, shows its output, and signs what it saw: the command and its stdout,
    #    the files it created or changed ("product"), and with --trace every file each process opened.
    started_at = datetime.now(UTC).isoformat()
    runner = docker_run(image, checkout) if image else []
    witness = ["witness", "run", "-l", "error", "--step", "experiment", "--attestations", "git"]
    if trace:
        # Witness also records the environment variables: keep only the allowlisted ones.
        allowed = [arg for name in ENV_ALLOWLIST for arg in ("--env-allow-sensitive-key", name)]
        witness += ["--trace", "--env-filter-sensitive-vars", "--env-add-sensitive-key", "*", *allowed]

    with tempfile.TemporaryDirectory(prefix="amber-witness-") as tmp:
        witness_json = Path(tmp) / "witness.json"
        # Witness signs with the researcher's key, or, signing keyless, with a key made for this run alone.
        witness_key = key.resolve() if key else _throwaway_key(Path(tmp))
        timestamp = ["-t", tsa] if tsa and key else []
        witness += ["-k", str(witness_key), *timestamp, "-o", str(witness_json), "--"]
        argv = [*witness, *experiment_argv(command, runner)]
        returncode, stdout = _show_output(argv, checkout)
        if log is not None:
            with log.open("a") as f:
                f.write(f"$ {shlex.join(argv)}\n[exit {returncode}]\n{stdout}\n")
        if returncode != 0 or not witness_json.exists():
            raise RunError("witness run failed (its output is above)")
        witness_envelope = json.loads(witness_json.read_bytes())

    attestations = witness_attestations(witness_envelope)
    command_run = attestations.get("command-run") or {}
    products = {path: d.get("digest", {}).get("sha256") for path, d in (attestations.get("product") or {}).items()}

    # 3. The exit code, from the last line of the stdout Witness recorded.
    code = exit_code(command_run.get("stdout") or "")
    if code is None:
        raise RunError("Witness's record of the command's output does not end with its exit code")
    print(f"amber: the experiment {'finished' if code == 0 else f'failed (exit {code})'}", file=sys.stderr)

    # 4. The environment lock, now, while this environment exists: resolvers read its package databases.
    lock = None
    if trace and command_run.get("processes"):
        env = {name: os.environ[name] for name in ENV_ALLOWLIST if name in os.environ}
        lock = build_lock(command_run, checkout, exclude=set(products), env=env)

    # 5. The results: the files the command created or changed that `results` names, by digest, and their
    #    bytes, to be copied into the run's directory so they travel with it.
    named = [r.rstrip("/") for r in results or []]
    paths = [path for path in sorted(products) if any(path == r or path.startswith(r + "/") for r in named)]
    output_files = {}
    for path in paths:
        file = checkout / path
        if products[path] and file.is_file() and sha256(file.read_bytes()) == products[path]:
            output_files[path] = file.read_bytes()

    return {
        "subject": subject,
        "commit": commit,
        "started_at": started_at,
        "command": command,
        "runner": runner,
        "exit_code": code,
        "outputs": {path: products[path] for path in paths},
        "lock": lock,
        "output_files": output_files,
        "witness_envelope": witness_envelope,
    }


def record(
    observed: dict[str, Any],
    key: Path | None,
    bundle: Path,
    *,
    tsa: str | None = TSA_URL,
    reruns: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Sign a statement over what `observe` saw, and store it with Witness's envelope in `<bundle>/runs/<id>/`.

    key:    the signing key; None signs keyless (the researcher signs in now, after the run)
    reruns: a rerun's comparison with the run it repeats (rerun.py).
    """
    witness_envelope = observed["witness_envelope"]

    # Who signs: the key, or the identity of a Sigstore login (its certificate lasts minutes, so it is asked now).
    if key is None:
        token = identity_token()
        signing = {"method": "sigstore", "identity": token.identity, "issuer": token.federated_issuer}
    else:
        signing = {"method": "key", "key_fingerprint": key_fingerprint(key), "timestamp_authority": tsa}

    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": observed["subject"], "digest": {"gitCommit": observed["commit"]}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "started_at": observed["started_at"],
            "command": observed["command"],
            "runner": observed["runner"],
            "exit_code": observed["exit_code"],
            "outputs": observed["outputs"],  # path -> sha256 (None: the run did not produce it)
            "environment": observed["lock"],  # environment.py; None when not traced
            "witness": {"payload_sha256": sha256(base64.b64decode(witness_envelope["payload"]))},
            "signing": signing,
            "claims": None,  # not designed yet: a run records no verdict, a rerun compares outputs
            "reruns": reruns,
        },
    }

    run_id = sha256(canonical(statement))
    directory = run_dir(bundle, run_id)

    # Keyless: a Sigstore bundle, kept as it is (verify checks it with sigstore).
    if key is None:
        _write_run(directory, observed, SIGSTORE_FILE, sign_keyless(canonical(statement), token))
        return {"id": run_id, "statement": statement, "lock": observed["lock"]}

    # With a key: the researcher signs the canonical statement (with Witness, so one tool holds the key).
    with tempfile.TemporaryDirectory(prefix="amber-sign-") as tmp:
        unsigned, signed = Path(tmp) / "statement.json", Path(tmp) / "signed.json"
        unsigned.write_bytes(canonical(statement))
        sign = ["witness", "sign", "-l", "error", "-f", str(unsigned), "-o", str(signed), "-t", PAYLOAD_TYPE]
        sign += ["-k", str(key.resolve()), *(["--timestamp-servers", tsa] if tsa else [])]
        call(sign)
        envelope = json.loads(signed.read_text())
    if base64.b64decode(envelope["payload"]) != canonical(statement):
        raise RunError("witness sign changed the statement")

    # The bundle holds runs signed with one key, and that key's public half.
    public_key = public_key_pem(key)
    key_file = bundle / PUBLIC_KEY_FILE
    if key_file.exists() and key_file.read_bytes() != public_key:
        raise RunError(f"{bundle} holds runs signed with another key; use another --output")
    bundle.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(public_key)

    _write_run(directory, observed, AMBER_FILE, envelope)
    return {"id": run_id, "statement": statement, "lock": observed["lock"]}


def _write_run(directory: Path, observed: dict[str, Any], name: str, signed: dict[str, Any]) -> None:
    """A run's directory: the copies of its results, Witness's envelope, and last the signed statement."""
    directory.mkdir(parents=True, exist_ok=True)
    for path, data in observed["output_files"].items():
        output_path(directory, path).parent.mkdir(parents=True, exist_ok=True)
        output_path(directory, path).write_bytes(data)
    (directory / WITNESS_FILE).write_text(json.dumps(observed["witness_envelope"], indent=2) + "\n")
    (directory / name).write_text(json.dumps(signed, indent=2) + "\n")  # last: a run without it is incomplete


def _throwaway_key(directory: Path) -> Path:
    """A new ed25519 key in `directory`, for Witness to sign one keyless run with; it is never kept."""
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric import ed25519

    path = directory / "witness-key.pem"
    private = ed25519.Ed25519PrivateKey.generate()
    path.write_bytes(private.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()))
    return path


def _show_output(argv: list[str], cwd: Path) -> tuple[int, str]:
    """
    Run `argv` (Witness around the experiment), showing the experiment's output as it comes; return
    (exit code, stdout). The wrapper's exit-code line, and the blank line before it, are for Witness, not shown.
    """
    stdout, held = [], ""
    print("─── experiment output " + "─" * 30, file=sys.stderr, flush=True)
    with subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, cwd=cwd, stdin=subprocess.DEVNULL) as process:
        assert process.stdout is not None
        for line in process.stdout:
            stdout.append(line)
            if line.startswith(EXIT_MARKER):
                held = ""
                continue
            sys.stdout.write(held)
            held = ""
            if line == "\n":
                held = line  # shown only if the exit-code line does not follow it
            else:
                sys.stdout.write(line)
            sys.stdout.flush()
        sys.stdout.write(held)
        sys.stdout.flush()
    print("─" * 52, file=sys.stderr, flush=True)
    return process.returncode, "".join(stdout)


def _clone(source: str, commit: str | None, dest: Path) -> str:
    """
    Clone `source` (a local checkout or a git URL) into `dest` at `commit`; return its name for the record.

    A local checkout must be clean, and is named by its origin remote (`local/<dir>` without one).
    Credentials in a URL are dropped from the name.
    """
    if source.startswith(("https://", "http://", "ssh://", "git@")):
        name = source
    else:
        local = Path(source).resolve()
        status = call(
            ["git", "-C", str(local), "status", "--porcelain", "--untracked-files=all", "--", ".", EXCLUDE_BUNDLE]
        ).stdout
        if commit is None and status:
            raise RunError(f"the checkout has uncommitted changes or untracked files; commit or remove them:\n{status}")
        remote = call(["git", "-C", str(local), "remote", "get-url", "origin"], check=False).stdout.strip()
        name, source = remote or f"local/{local.name}", str(local)

    if name.startswith(("https://", "http://", "ssh://")):
        url = urlsplit(name)
        user = f"{url.username}@" if url.scheme == "ssh" and url.username else ""
        host = user + (url.hostname or "") + (f":{url.port}" if url.port else "")
        name = urlunsplit((url.scheme, host, url.path, "", ""))

    call(["git", "clone", "-q", source, str(dest)])
    if commit:
        call(["git", "-C", str(dest), "checkout", "-q", commit])
    return name
