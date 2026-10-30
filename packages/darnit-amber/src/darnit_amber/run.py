"""``darnit-amber run``: execute the Amber audit and the corpus experiment under Witness, emit a run bundle.

One bundle per run: an in-toto v1 statement whose predicate is ``amber/run/v1``,
with the Witness DSSE envelopes that captured the run. The bundle id is the
sha256 of the canonical statement. See darnit issue #677.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata as md
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from darnit.stores.protocols import AttestationStore

PREDICATE_TYPE = "https://darnit.dev/amber/run/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
WITNESS_ATTESTORS = "environment,git,command-run,product"
AUDIT_OUTPUT = "amber-audit.json"
# Sigstore's public RFC 3161 timestamp authority: it sees a hash of the signature and nothing else.
TSA_URL = "https://timestamp.sigstore.dev/api/v1/timestamp"
MAX_STORED_OUTPUT = 10 * 1024 * 1024  # outputs up to this size are kept next to the bundle


def write_blob(store: Any, bundle_id: str, path: str, data: bytes) -> None:
    """Keep an experiment output next to its bundle: s3 key or local file <id>/outputs/<path>."""
    if hasattr(store, "_client"):
        store.write_blob(f"{bundle_id}/outputs/{path}", data)
        return
    dest = Path(store._root) / bundle_id / "outputs" / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def read_blob(store: Any, bundle_id: str, path: str) -> bytes:
    if hasattr(store, "_client"):
        return store.read_blob(f"{bundle_id}/outputs/{path}")
    return (Path(store._root) / bundle_id / "outputs" / path).read_bytes()


class RunError(RuntimeError):
    pass


def default_key() -> Path:
    """The researcher's signing key, generated once under darnit's data root (ed25519, 0600)."""
    from darnit.stores.defaults.platform_paths import user_data_root

    key = user_data_root() / "amber" / "signing.key"
    if key.is_file():
        return key
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private = ed25519.Ed25519PrivateKey.generate()
    key.parent.mkdir(parents=True, exist_ok=True)
    key.touch(mode=0o600)
    key.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    key.with_suffix(".pub").write_bytes(
        private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    return key


def key_fingerprint(key: Path) -> str:
    """sha256 of the key's public half (SubjectPublicKeyInfo DER); goes in the bundle instead of a path."""
    from cryptography.hazmat.primitives import serialization

    private = serialization.load_pem_private_key(key.read_bytes(), password=None)
    der = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return "sha256:" + hashlib.sha256(der).hexdigest()


def _is_url(s: str) -> bool:
    return s.startswith(("https://", "http://", "git@", "ssh://"))


def _clone(url: str, ref: str | None, dest: Path) -> Path:
    r = subprocess.run(["git", "clone", "-q", url, str(dest)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RunError(f"clone failed: {r.stderr.strip()}")
    if ref:
        r = subprocess.run(["git", "-C", str(dest), "checkout", "-q", ref], capture_output=True, text=True)
        if r.returncode != 0:
            raise RunError(f"checkout {ref} failed: {r.stderr.strip()}")
    return dest


def _git_commit(repo: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or None


def _git_remote(repo: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True)
    return r.stdout.strip() or None


def _infer_outputs(products: dict[str, Any]) -> list[str]:
    """Files the command created or changed, as Witness saw them, minus darnit's own."""
    return sorted(p for p in products if p != AUDIT_OUTPUT and not p.startswith(".git/"))


def _version(dist: str) -> str | None:
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return None


def _environment() -> dict[str, Any]:
    mem = None
    try:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        pass
    return {
        "image_digest": None,  # pinned container image: PR B
        "darnit": _version("darnit"),
        "darnit_amber": _version("darnit-amber"),
        "python": platform.python_version(),
        "os": platform.platform(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": mem,
    }


def _decode_envelope(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    env = json.loads(path.read_text())
    return env, json.loads(base64.b64decode(env["payload"]))


def _witness_sections(stmt: dict[str, Any]) -> dict[str, Any]:
    return {a["type"].rsplit("/", 2)[-2]: a["attestation"] for a in stmt["predicate"]["attestations"]}


def load_entry(path: Path | None) -> dict[str, Any]:
    """A corpus entry (yaml or json), or an empty dict."""
    if path is None:
        return {}
    if path.suffix == ".json":
        return json.loads(path.read_text()) or {}
    import yaml  # type: ignore[import-untyped]  # darnit already depends on it

    return yaml.safe_load(path.read_text()) or {}


def _claims(entry: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in entry.get("claims") or []:
        out.append(
            {
                "id": c.get("id") or c.get("metric"),
                "statement": c.get("statement"),
                "metric": c.get("metric"),
                "threshold": c.get("threshold"),
                "tolerance": c.get("tolerance"),
                "unit": c.get("unit"),
                "threshold_source": c.get("source"),
                "measurement_protocol": c.get("measurement_protocol"),
                "expected_verdict": c.get("expected_verdict"),
                "measure": c.get("measure"),
                "measured": None,
                "verdict": "NOT_COMPARABLE",
                "reason": "no measure declared for this claim",
            }
        )
    return out


_OPS = {
    "==": lambda a, b, t: abs(a - b) <= t if isinstance(a, float) else a == b,
    "!=": lambda a, b, t: not (abs(a - b) <= t) if isinstance(a, float) else a != b,
    "<=": lambda a, b, t: a <= b + t,
    ">=": lambda a, b, t: a >= b - t,
    "<": lambda a, b, t: a < b,
    ">": lambda a, b, t: a > b,
}


def _parse_threshold(threshold: str) -> tuple[str, str]:
    t = str(threshold).strip()
    for op in ("==", "!=", "<=", ">=", "<", ">"):
        if t.startswith(op):
            return op, t[len(op) :].strip()
    return "==", t


def _coerce(a: str, b: str) -> tuple[Any, Any]:
    try:
        return float(a), float(b)
    except ValueError:
        return a.strip(), b.strip()


def measure_claim(claim: dict[str, Any], repo: Path) -> None:
    """Fill ``measured``, ``verdict`` and ``reason`` from the checkout after the experiment ran."""
    import re

    m = claim.get("measure")
    if not m:
        return
    path = repo / m["file"]
    if not path.is_file():
        claim["reason"] = f"output {m['file']} not produced"
        return
    text = path.read_text(errors="replace")
    found = re.search(m["regex"], text, re.M)
    if not found:
        claim["reason"] = f"regex did not match in {m['file']}"
        return
    value = found.group(1) if found.groups() else found.group(0)
    if m.get("scale") is not None:
        value = str(float(value) * float(m["scale"]))
    claim["measured"] = value
    if m.get("comparable") is False:
        claim["reason"] = m.get("reason") or "measured, but not on the paper's terms"
        return
    if claim.get("threshold") is None:
        claim["reason"] = "no threshold"
        return
    op, want = _parse_threshold(claim["threshold"])
    a, b = _coerce(value, want)
    tol = float(claim.get("tolerance") or 0) if isinstance(a, float) else 0
    ok = _OPS[op](a, b, tol)
    claim["verdict"] = "REPRODUCED" if ok else "NOT_REPRODUCED"
    claim["reason"] = f"measured {value} {op} {want}" + (f" (tolerance {tol})" if tol else "")


def overall_verdict(claims: list[dict[str, Any]]) -> str:
    verdicts = {c["verdict"] for c in claims}
    if "NOT_REPRODUCED" in verdicts:
        return "NOT_REPRODUCED"
    if "REPRODUCED" in verdicts:
        return "REPRODUCED"
    return "NOT_COMPARABLE"


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _signer_args(key: Path | None, token_path: Path | None) -> list[str]:
    """``-k key`` or, with ``--identity``, a Fulcio certificate from the OIDC token in ``token_path``."""
    if token_path is not None:
        from .identity import FULCIO_URL, OIDC_CLIENT_ID, OIDC_ISSUER

        return [
            "--signer-fulcio-url",
            FULCIO_URL,
            "--signer-fulcio-oidc-issuer",
            OIDC_ISSUER,
            "--signer-fulcio-oidc-client-id",
            OIDC_CLIENT_ID,
            "--signer-fulcio-token-path",
            str(token_path.resolve()),  # a file, never argv: the token is a secret
        ]
    if key is None:
        raise RunError("a signing key or --identity is required")
    return ["-k", str(key.resolve())]  # witness runs inside the checkout


def _witness(
    step: str,
    key: Path | None,
    out: Path,
    cwd: Path,
    cmd: list[str],
    tsa: str | None = TSA_URL,
    token_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    witness = shutil.which("witness")
    if not witness:
        raise RunError("witness binary not found on PATH (https://github.com/in-toto/witness)")
    full = [
        witness,
        "run",
        "--step",
        step,
        "--attestations",
        WITNESS_ATTESTORS,
        *_signer_args(key, token_path),
        *(["-t", tsa] if tsa else []),  # RFC 3161 countersignature: proves when the signature existed
        "-o",
        str(out),
        "--",
        *cmd,
    ]
    r = subprocess.run(full, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RunError(f"witness run ({step}) failed:\n{r.stderr[-2000:]}")
    envelope, stmt = _decode_envelope(out)
    return envelope, _witness_sections(stmt)


def _signing(key: Path | None, envelopes: dict[str, dict[str, Any]], tsa: str | None) -> dict[str, Any]:
    """What the bundle records about its signer: a key fingerprint, or the identity in the Fulcio certificates.

    Witness asks Fulcio for a certificate per step, so one login yields one certificate per envelope.
    """
    if key is not None:
        return {"method": "key", "key_fingerprint": key_fingerprint(key), "timestamp_authority": tsa}
    from .identity import certificate_identity, signature_chain

    certs = {}
    for name, env in envelopes.items():
        sig = next(s for s in env["signatures"] if s.get("certificate"))
        certs[name] = certificate_identity(signature_chain(sig)[0])
    first = next(iter(certs.values()))
    return {
        "method": "identity",
        "identity": first["subject"],
        "issuer": first["issuer"],
        "certificates_sha256": {name: c["certificate_sha256"] for name, c in certs.items()},
        "timestamp_authority": tsa,
    }


def execute(
    artifact: str,
    ref: str | None,
    key: Path | None,
    entry: dict[str, Any],
    store: AttestationStore,
    rerun_of: str | None = None,
    tsa: str | None = TSA_URL,
    identity: bool = False,
) -> dict[str, Any]:
    darnit_bin = Path(sys.executable).parent / "darnit"
    if not darnit_bin.exists():
        raise RunError(f"darnit CLI not found next to {sys.executable}")
    if identity and not tsa:
        raise RunError(
            "--identity needs a timestamp: the certificate lives ten minutes, the timestamp places the signature in that window"
        )
    key = None if identity else (key or default_key())
    exp_cmd = (entry.get("run") or {}).get("command")
    exp_outputs = (entry.get("run") or {}).get("outputs")  # None: infer from Witness products
    claims = _claims(entry)

    with tempfile.TemporaryDirectory(prefix="amber-run-") as tmp:
        tmpdir = Path(tmp)
        repo = _clone(artifact, ref, tmpdir / "artifact") if _is_url(artifact) else Path(artifact).resolve()
        token_path: Path | None = None
        if identity:
            from .identity import identity_token

            token_path = tmpdir / "oidc.token"
            token_path.touch(mode=0o600)
            token_path.write_text(identity_token())  # one login per run; both Witness steps reuse it
        started = datetime.now(UTC).isoformat()

        audit_env, audit_w = _witness(
            "amber-audit",
            key,
            tmpdir / "audit.json",
            repo,
            ["sh", "-c", f"{darnit_bin} audit . -f amber --output json --no-fail > {AUDIT_OUTPUT}"],
            tsa,
            token_path,
        )
        audit = json.loads((repo / AUDIT_OUTPUT).read_text())

        experiment: dict[str, Any] | None = None
        exp_env: dict[str, Any] | None = None
        if exp_cmd:
            exp_env, exp_w = _witness(
                "experiment", key, tmpdir / "experiment.json", repo, ["sh", "-c", exp_cmd], tsa, token_path
            )
            products = exp_w.get("product") or {}
            if exp_outputs is None:
                exp_outputs = _infer_outputs(products)
            experiment = {
                "command": exp_cmd,
                "exit_code": exp_w.get("command-run", {}).get("exitcode"),
                "outputs": [
                    {
                        "path": p,
                        "sha256": (products.get(p) or {}).get("digest", {}).get("sha256"),
                        "captured": p in products,
                    }
                    for p in exp_outputs
                ],
                "products": {p: d.get("digest", {}).get("sha256") for p, d in products.items()},
            }
        blobs: dict[str, bytes] = {}
        for o in (experiment or {}).get("outputs") or []:
            f = repo / o["path"]
            o["stored"] = bool(o["captured"] and f.is_file() and f.stat().st_size <= MAX_STORED_OUTPUT)
            if o["stored"]:
                blobs[o["path"]] = f.read_bytes()
        for c in claims:
            measure_claim(c, repo)
        for c in claims:
            c["matches_expected"] = (c["verdict"] == c["expected_verdict"]) if c.get("expected_verdict") else None
        commit = _git_commit(repo)
        subject_name = artifact if _is_url(artifact) else (_git_remote(repo) or str(repo))

    predicate = {
        "started_at": started,
        "environment": _environment(),
        "signing": _signing(key, {"amber-audit": audit_env, **({"experiment": exp_env} if exp_env else {})}, tsa),
        "corpus_entry": entry.get("id"),
        "entry": {
            "source": entry.get("_source", "file"),
            "artifact": {"clone": subject_name, "ref": commit},
            "run": {"command": exp_cmd, "outputs": exp_outputs},
            "environment": entry.get("environment"),
        },
        "audit": {
            "framework": "amber",
            "command": audit_w.get("command-run", {}).get("cmd"),
            "exit_code": audit_w.get("command-run", {}).get("exitcode"),
            "results": [
                {"id": x.get("id") or x.get("control_id"), "status": x.get("status")} for x in audit.get("results", [])
            ],
        },
        "experiment": experiment,
        "claims": claims,
        "verdict": overall_verdict(claims),
        "reruns": {"of": rerun_of} if rerun_of else None,
        "witness_attestations": sorted(audit_w),
    }
    statement = {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": subject_name, "digest": {"gitCommit": commit} if commit else {}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": predicate,
    }
    bundle_id = hashlib.sha256(_canonical(statement)).hexdigest()
    bundle = {
        "id": bundle_id,
        "statement": statement,
        "witness_envelopes": {"amber-audit": audit_env, **({"experiment": exp_env} if exp_env else {})},
    }
    store.write(bundle_id, _canonical(bundle), "application/vnd.in-toto+json")
    for path, data in blobs.items():
        write_blob(store, bundle_id, path, data)
    return bundle


def run(
    artifact: str,
    ref: str | None,
    key: Path | None,
    claims: Path | None,
    store: AttestationStore,
    command: list[str] | None = None,
    tsa: str | None = TSA_URL,
    identity: bool = False,
) -> dict[str, Any]:
    """``command`` (argv after ``--``) overrides the entry's run.command; with no entry, everything else is inferred."""
    entry = load_entry(claims)
    if command:
        entry = {**entry, "run": {**(entry.get("run") or {}), "command": shlex.join(command)}}
        if not claims:
            entry["_source"] = "inferred"
    return execute(artifact, ref, key, entry, store, tsa=tsa, identity=identity)
