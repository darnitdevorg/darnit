"""Helpers shared by run, verify and rerun: constants, subprocess calls, reading a stored run, signatures."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

PREDICATE_TYPE = "https://darnit.dev/amber/run/v1"
PAYLOAD_TYPE = "application/vnd.in-toto+json"
TSA_URL = "https://timestamp.sigstore.dev/api/v1/timestamp"  # sees a hash of the signature, nothing else

# The last line the wrapped command prints (experiment_argv), so the exit code is in Witness's signed stdout.
EXIT_MARKER = "AMBER_EXIT_CODE="

# A run keeps copies of its results in its directory, under this folder, at their paths in the source.
OUTPUT_DIR = "outputs"

# Environment variables that change how code runs without naming the machine. A rerun sets them again.
ENV_ALLOWLIST = (
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "PYTHONHASHSEED",
    "PYTHONDONTWRITEBYTECODE",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "CUDA_VISIBLE_DEVICES",
    "SOURCE_DATE_EPOCH",
)


class RunError(RuntimeError):
    """Anything that stops a run, verify or rerun. The CLI prints it and exits 1."""


def call(
    cmd: list[str], log: Path | None = None, check: bool = True, stream: bool = False, **kw: Any
) -> subprocess.CompletedProcess[str]:
    """Run ``cmd``. ``stream`` shows its output instead of capturing it; ``log`` gets the command and its output."""
    result = subprocess.run(cmd, capture_output=not stream, text=True, **kw)

    if log is not None:
        with log.open("a") as f:
            f.write(f"$ {shlex.join(cmd)}\n[exit {result.returncode}]\n{result.stdout or ''}{result.stderr or ''}\n")

    if check and result.returncode != 0:
        raise RunError(f"{shlex.join(cmd[:3])} failed: {(result.stderr or result.stdout or '').strip()[-1500:]}")
    return result


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> bytes:
    """JSON with sorted keys and no whitespace: the exact bytes that are signed, and hashed into a run id."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def experiment_argv(command: str, runner: list[str]) -> list[str]:
    """
    What Witness runs: `command` in a subshell, then a last line with its exit code.

    Witness writes no attestation for a failing command, and a failed experiment is still worth recording,
    so the wrapper always succeeds and reports the exit code on stdout, which Witness records and signs.
    `runner` is a prefix such as `docker run ... image` when the command runs inside an image.
    """
    return [*runner, "sh", "-c", f'({command})\nprintf "\\n{EXIT_MARKER}%s\\n" "$?"\n']


def exit_code(stdout: str) -> int | None:
    """The exit code the wrapper printed as the last line of `stdout`, or None."""
    last = stdout.rstrip("\n").rpartition("\n")[2]
    code = last.removeprefix(EXIT_MARKER)
    return int(code) if last.startswith(EXIT_MARKER) and code.isdigit() else None


# A bundle (default `<source>/.amber/`) is what a researcher sends with their source:
#   key.pub                         the public key its runs are signed with
#   runs/<id>/amber.intoto.json     amber's statement, signed with that key
#   runs/<id>/amber.sigstore.json   or, signed keyless, that statement in a Sigstore bundle
#   runs/<id>/witness.intoto.json   Witness's attestation collection, as Witness signed it
#   runs/<id>/outputs/<path>        copies of the results (`--results`; digests in amber's statement)
#   reruns/<time>-<id>/             reruns made from it (rerun.py); each is a bundle of its own
# Nothing read from it is trusted until verify() has checked it.
AMBER_FILE, WITNESS_FILE, PUBLIC_KEY_FILE = "amber.intoto.json", "witness.intoto.json", "key.pub"
SIGSTORE_FILE = "amber.sigstore.json"
DEFAULT_BUNDLE = ".amber"


def head_commit(checkout: Path) -> str | None:
    """The commit a checkout is at (None: not a git checkout with a commit)."""
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True)
    return head.stdout.strip() if head.returncode == 0 and head.stdout.strip() else None


def run_dir(bundle: Path, run_id: str) -> Path:
    """`<bundle>/runs/<run_id>/`. The id comes from untrusted input, so it may not point outside the bundle."""
    if not re.fullmatch(r"[0-9a-f]{64}", run_id):
        raise RunError(f"{run_id} is not a run id (64 hex digits)")
    return bundle / "runs" / run_id


def newest_run(bundle: Path) -> str:
    """The id of the bundle's most recently recorded run."""
    runs = sorted((bundle / "runs").glob("*/amber.*.json"), key=lambda f: f.stat().st_mtime)
    if not runs:
        raise RunError(f"no runs in {bundle}")
    return runs[-1].parent.name


def output_path(directory: Path, path: str) -> Path:
    """`directory/outputs/path`, where a run keeps its copy of an output. `path` comes from a record: it may not leave."""
    if not path or path.startswith("/") or ".." in Path(path).parts:
        raise RunError(f"{path} is not a relative path inside the checkout")
    return directory / OUTPUT_DIR / path


def payload(envelope: dict[str, Any]) -> dict[str, Any]:
    """The statement an envelope carries (not checked: see verify)."""
    statement: dict[str, Any] = json.loads(base64.b64decode(envelope["payload"]))
    return statement


def amber_record(directory: Path) -> Path:
    """The file holding a run's signed statement: a Sigstore bundle if it was signed keyless, else a DSSE envelope."""
    keyless = directory / SIGSTORE_FILE
    return keyless if keyless.exists() else directory / AMBER_FILE


def read_run(bundle: Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A stored run: amber's statement, the envelope that carries it, and Witness's envelope."""
    try:
        record = json.loads(amber_record(run_dir(bundle, run_id)).read_text())
        envelope = record.get("dsseEnvelope", record)  # a Sigstore bundle carries the envelope inside it
        witness_envelope = json.loads((run_dir(bundle, run_id) / WITNESS_FILE).read_text())
        statement = payload(envelope)
    except FileNotFoundError:
        raise RunError(f"no run {run_id} in {bundle}") from None
    except (KeyError, TypeError, ValueError) as e:
        raise RunError(f"run {run_id} does not hold two DSSE envelopes: {e}") from e

    if not isinstance(statement, dict) or statement.get("predicateType") != PREDICATE_TYPE:
        raise RunError(f"run {run_id} does not carry a {PREDICATE_TYPE} statement")
    return statement, envelope, witness_envelope


def witness_attestations(envelope: dict[str, Any]) -> dict[str, Any]:
    """A Witness envelope's attestations by attestor name (`product`, `command-run`, ...)."""
    return {a["type"].rsplit("/", 2)[-2]: a["attestation"] for a in payload(envelope)["predicate"]["attestations"]}


# Keys, signatures and timestamps.


def key_fingerprint(key: Path) -> str:
    """sha256 of the public key (SubjectPublicKeyInfo DER) of a PEM private key, or of a PEM public key."""
    from cryptography.hazmat.primitives import serialization as s

    pem = key.read_bytes()
    if b"PUBLIC KEY" in pem:
        public = s.load_pem_public_key(pem)
    else:
        public = s.load_pem_private_key(pem, None).public_key()
    return "sha256:" + sha256(public.public_bytes(s.Encoding.DER, s.PublicFormat.SubjectPublicKeyInfo))


def public_key_pem(key: Path) -> bytes:
    """The PEM public key of a PEM private key."""
    from cryptography.hazmat.primitives import serialization as s

    private = s.load_pem_private_key(key.read_bytes(), None)
    return private.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo)


def signature_ok(envelope: dict[str, Any], public_key: Any) -> bool:
    """One of the envelope's DSSE signatures verifies with ``public_key`` (Ed25519, ECDSA P-256 or RSA, SHA-256)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding

    try:
        payload, payload_type = base64.b64decode(envelope["payload"]), envelope["payloadType"]
    except Exception:  # noqa: BLE001
        return False

    # DSSE signs this "pre-authentication encoding", not the payload itself.
    pae = b"DSSEv1 %d %s %d " % (len(payload_type), payload_type.encode(), len(payload)) + payload

    for signature in envelope.get("signatures") or []:
        try:
            raw = base64.b64decode(signature["sig"])
            if isinstance(public_key, ed25519.Ed25519PublicKey):
                public_key.verify(raw, pae)
            elif isinstance(public_key, ec.EllipticCurvePublicKey):
                public_key.verify(raw, pae, ec.ECDSA(hashes.SHA256()))
            else:
                public_key.verify(raw, pae, padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception:  # noqa: BLE001 - try the next signature
            continue
    return False


def timestamps(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Witness's RFC 3161 timestamps on each signature, each checked against Sigstore's timestamp authorities.

    One item per timestamp: ``{signature: index, trusted: bool, time, error?}``. ``trusted`` means the
    timestamp covers that signature and chains to an authority that was valid at that time.
    """
    import rfc3161_client
    from rfc3161_client import VerifierBuilder
    from sigstore.models import ClientTrustConfig

    try:
        root = ClientTrustConfig.production().trusted_root
    except Exception:  # noqa: BLE001 - offline: the root sigstore ships is authentic, only possibly stale
        root = ClientTrustConfig.production(offline=True).trusted_root

    items = []
    for index, signature in enumerate(envelope.get("signatures") or []):
        for timestamp in signature.get("timestamps") or []:
            item: dict[str, Any] = {"signature": index, "trusted": False}
            try:
                signed, token = base64.b64decode(signature["sig"]), base64.b64decode(timestamp["data"])

                # Witness stores the bare token; the library reads a whole TimeStampResp, so wrap it in one (DER).
                length = len(token) + 5
                size = bytes([length]) if length < 0x80 else bytes([0x80 | 2]) + length.to_bytes(2, "big")
                response = rfc3161_client.decode_timestamp_response(b"\x30" + size + b"\x30\x03\x02\x01\x00" + token)
                info = response.tst_info
                item["time"] = info.gen_time.isoformat()

                # It must timestamp this signature, and chain to one of Sigstore's authorities.
                covers_signature = info.message_imprint.message == hashlib.sha256(signed).digest()
                for authority in root.get_timestamp_authorities() if covers_signature else []:
                    certs = authority.certificates(allow_expired=True)
                    builder = VerifierBuilder().tsa_certificate(certs[0]).add_root_certificate(certs[-1])
                    for cert in certs[1:-1]:
                        builder = builder.add_intermediate_certificate(cert)
                    try:
                        builder.build().verify_message(response, signed)
                    except Exception:  # noqa: BLE001 - not this authority
                        continue
                    start, end = authority.validity_period_start, authority.validity_period_end
                    item["trusted"] = start <= info.gen_time and (not end or info.gen_time < end)
                    break
            except Exception as e:  # noqa: BLE001 - reported, never fatal
                item["error"] = f"{type(e).__name__}: {e}"
            items.append(item)
    return items


# Keyless signing (Sigstore): the signer is an identity (an email address, or a CI workflow), not a key.
# A login gets a certificate for it from Fulcio, valid for minutes, and the signature is recorded in the
# public Rekor log. There is no key to keep or lose; a verifier names the identity it expects.


def identity_token() -> Any:
    """A Sigstore identity: the CI's own (GitHub Actions, GitLab, ...), else a login in the browser (or a link)."""
    from sigstore.models import ClientTrustConfig
    from sigstore.oidc import IdentityToken, Issuer, detect_credential

    ambient = detect_credential()
    if ambient:
        return IdentityToken(ambient)
    print("amber: signing the run with Sigstore: sign in below (or pass --key to sign with a key)", file=sys.stderr)
    return Issuer(ClientTrustConfig.production().signing_config.get_oidc_url()).identity_token()


def sign_keyless(statement: bytes, token: Any) -> dict[str, Any]:
    """`statement` signed as a DSSE envelope with a Fulcio certificate for `token`'s identity, logged in Rekor."""
    from sigstore import dsse
    from sigstore.models import ClientTrustConfig
    from sigstore.sign import SigningContext

    # sigstore-python's statement parser refuses the in-toto digest `gitCommit` (our subject), but signing
    # only uses the bytes: hand them over as they are.
    wrapped = dsse.Statement.__new__(dsse.Statement)
    wrapped._contents = statement

    context = SigningContext.from_trust_config(ClientTrustConfig.production())
    with context.signer(token) as signer:
        bundle: dict[str, Any] = json.loads(signer.sign_dsse(wrapped).to_json())
    return bundle


def verify_keyless(bundle: dict[str, Any], identity: str, issuer: str) -> bytes | None:
    """
    The payload of a Sigstore bundle, if its certificate chains to Fulcio, names `identity` from `issuer`,
    and its signature verifies and is in Rekor; else None.
    """
    from sigstore.models import Bundle
    from sigstore.verify import Verifier
    from sigstore.verify.policy import Identity

    try:
        verifier = Verifier.production()
    except Exception:  # noqa: BLE001 - offline: the trusted root sigstore ships
        verifier = Verifier.production(offline=True)
    try:
        policy = Identity(identity=identity, issuer=issuer)
        _, statement = verifier.verify_dsse(Bundle.from_json(json.dumps(bundle)), policy)
    except Exception:  # noqa: BLE001 - any failure is "does not verify"
        return None
    return statement
