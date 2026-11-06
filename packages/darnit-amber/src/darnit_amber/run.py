"""``darnit-amber run``: execute the Amber audit and the corpus experiment under Witness, emit a run bundle.

One bundle per run: an in-toto v1 statement whose predicate is ``amber/run/v1``,
signed by the researcher as a DSSE envelope, with the Witness DSSE envelopes
that captured the run. The bundle id is the sha256 of the canonical statement.
See darnit issue #677 and specs/046-amber-run-bundle.
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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from darnit.stores.defaults.platform_paths import user_data_root
from darnit.stores.protocols import AttestationStore

PREDICATE_TYPE = "https://darnit.dev/amber/run/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
# Witness always records material and product, and command-run is built in. The environment attestor is
# left out on purpose: it records the host name, the user name and every variable a blocklist does not
# know; the statement carries an allowlisted snapshot instead (ENV_ALLOWLIST).
WITNESS_ATTESTORS = "git"
# Sigstore's public RFC 3161 timestamp authority: it sees a hash of the signature and nothing else.
TSA_URL = "https://timestamp.sigstore.dev/api/v1/timestamp"
MAX_STORED_OUTPUT = 10 * 1024 * 1024  # outputs up to this size are kept next to the bundle
# Variables recorded in the bundle: what decides how code runs, never credentials, paths or names
# (PATH is left out: it names the user's home directory on most machines).
ENV_ALLOWLIST = (
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "SHELL",
    "TERM",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "PYTHONPATH",
    "PYTHONHASHSEED",
    "PYTHONDONTWRITEBYTECODE",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "CUDA_VISIBLE_DEVICES",
    "NVIDIA_VISIBLE_DEVICES",
    "SOURCE_DATE_EPOCH",
)


class RunError(RuntimeError):
    pass


def safe_rel(path: str) -> str:
    """``path`` as a relative path inside the checkout, or raise: output paths come from an untrusted repository."""
    p = Path(path)
    if not path or p.is_absolute() or path.startswith(("/", "\\")) or ".." in p.parts or "\\" in path:
        raise RunError(f"output path {path!r} is not a relative path inside the repository")
    return p.as_posix()


def write_blob(store: Any, bundle_id: str, path: str, data: bytes) -> None:
    """Keep an experiment output next to its bundle: s3 key or local file <id>/outputs/<path>."""
    path = safe_rel(path)
    if hasattr(store, "_client"):
        store.write_blob(f"{bundle_id}/outputs/{path}", data)
        return
    dest = Path(store._root) / bundle_id / "outputs" / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def read_blob(store: Any, bundle_id: str, path: str) -> bytes:
    path = safe_rel(path)
    if hasattr(store, "_client"):
        return store.read_blob(f"{bundle_id}/outputs/{path}")
    return (Path(store._root) / bundle_id / "outputs" / path).read_bytes()


def read_output(store: Any, bundle: dict[str, Any], path: str) -> bytes:
    """A stored output of ``bundle``, checked against the digest in its statement: the store is not trusted."""
    path = safe_rel(path)
    outputs = ((bundle["statement"]["predicate"].get("experiment") or {}).get("outputs")) or []
    out = next((o for o in outputs if o["path"] == path), None)
    if out is None:
        raise RunError(f"{path} is not an output of this run; outputs: {[o['path'] for o in outputs]}")
    if not out.get("stored"):
        raise RunError(f"{path} was not stored with the bundle (too large or not captured)")
    data = read_blob(store, bundle["id"], path)
    if hashlib.sha256(data).hexdigest() != out.get("sha256"):
        raise RunError(f"stored output {path} does not match the digest in the statement")
    return data


def default_key() -> Path:
    """The researcher's signing key, generated once under darnit's data root (ed25519, 0600)."""
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


def public_url(url: str) -> str:
    """``url`` without credentials: a token in a clone URL must not end up in a bundle made to be shared."""
    if not url.startswith(("https://", "http://", "ssh://")):
        return url
    p = urlsplit(url)
    if not (p.username or p.password):
        return url
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    if p.scheme == "ssh" and p.username:
        host = f"{p.username}@{host}"  # the ssh user (git@) is part of the address, a password is not
    return urlunsplit((p.scheme, host, p.path, p.query, p.fragment))


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


def _git_dirty(repo: Path) -> list[str]:
    """Tracked files that differ from HEAD: a run on those is not a run of the commit."""
    r = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True
    )
    return [line[3:] for line in r.stdout.splitlines() if line.strip()]


def _infer_outputs(products: dict[str, Any]) -> list[str]:
    """Files the command created or changed, as Witness saw them, minus git's own and anything not inside the checkout."""
    out = []
    for p in products:
        if p.startswith(".git/"):
            continue
        try:
            out.append(safe_rel(p))
        except RunError:
            continue
    return sorted(out)


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
        "image_digest": None,  # pinned container image: darnit #677 step B
        "darnit": _version("darnit-core"),
        "darnit_amber": _version("darnit-amber"),
        "python": platform.python_version(),
        "os": platform.platform(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": mem,
        "variables": {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ},
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


def _parse_threshold(threshold: str) -> tuple[str, str]:
    t = str(threshold).strip()
    for op in ("==", "!=", "<=", ">=", "<", ">"):
        if t.startswith(op):
            return op, t[len(op) :].strip()
    return "==", t


def _number(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def compare(value: str, threshold: str, tolerance: Any) -> tuple[bool | None, str]:
    """``value`` against ``threshold`` (``op number`` or ``op text``): (holds, reason); ``None`` when not comparable.

    Ordering operators need two numbers; ``==`` and ``!=`` fall back to a
    text comparison, where the tolerance does not apply.
    """
    op, want = _parse_threshold(threshold)
    a, b = _number(value), _number(want)
    tol = _number(tolerance) if tolerance is not None else 0.0
    if tol is None:
        return None, f"tolerance {tolerance!r} is not a number"
    if a is None or b is None:
        if op in ("==", "!="):
            same = value.strip() == want.strip()
            return (same if op == "==" else not same), f"measured {value!r} {op} {want!r}"
        return None, f"{op} needs two numbers: measured {value!r}, threshold {want!r}"
    holds = {
        "==": abs(a - b) <= tol,
        "!=": abs(a - b) > tol,
        "<=": a <= b + tol,
        ">=": a >= b - tol,
        "<": a < b + tol,
        ">": a > b - tol,
    }[op]
    return holds, f"measured {value} {op} {want}" + (f" (tolerance {tol})" if tol else "")


def measure_claim(claim: dict[str, Any], read: Callable[[str], bytes | None]) -> None:
    """Fill ``measured``, ``verdict`` and ``reason``; ``read`` returns the bytes of an output the experiment produced, or None.

    Never raises: a claim that cannot be measured is NOT_COMPARABLE with the reason.
    """
    import re

    m = claim.get("measure")
    if not m:
        return
    try:
        path = safe_rel(str(m.get("file") or ""))
        data = read(path)
        if data is None:
            claim["reason"] = f"output {m.get('file')} not produced by the experiment"
            return
        found = re.search(m["regex"], data.decode(errors="replace"), re.M)
        if not found:
            claim["reason"] = f"regex did not match in {path}"
            return
        value = found.group(1) if found.groups() else found.group(0)
        if m.get("scale") is not None:
            n = _number(value)
            if n is None:
                claim["reason"] = f"scale given but {value!r} is not a number"
                return
            value = str(n * float(m["scale"]))
        claim["measured"] = value
        if m.get("comparable") is False:
            claim["reason"] = m.get("reason") or "measured, but not on the paper's terms"
            return
        if claim.get("threshold") is None:
            claim["reason"] = "no threshold"
            return
        holds, reason = compare(value, claim["threshold"], claim.get("tolerance"))
        claim["reason"] = reason
        if holds is not None:
            claim["verdict"] = "REPRODUCED" if holds else "NOT_REPRODUCED"
    except Exception as e:  # noqa: BLE001 - a bad regex or a bad spec is a measurement that failed, not a crash
        claim["measured"] = None
        claim["verdict"] = "NOT_COMPARABLE"
        claim["reason"] = f"measurement failed: {type(e).__name__}: {e}"


def overall_verdict(claims: list[dict[str, Any]]) -> str:
    """REPRODUCED only when every claim is; a claim that could not be measured counts against the run."""
    verdicts = [c["verdict"] for c in claims]
    if "NOT_REPRODUCED" in verdicts:
        return "NOT_REPRODUCED"
    if verdicts and all(v == "REPRODUCED" for v in verdicts):
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


def _witness_bin() -> str:
    witness = shutil.which("witness")
    if not witness:
        raise RunError("witness binary not found on PATH (https://github.com/in-toto/witness)")
    return witness


def _witness_env() -> dict[str, str]:
    """The environment Witness and the experiment run in: this one, minus the OIDC token, plus darnit's own bin dir."""
    from .identity import TOKEN_ENV

    env = {k: v for k, v in os.environ.items() if k != TOKEN_ENV}
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
    return env


def wrap_command(command: str) -> str:
    """The shell script Witness runs for the experiment.

    Witness writes no attestation when the command fails, and a failed
    experiment is a result worth recording. The command runs in a subshell
    and its exit status goes to the file named by ``$0``, outside the
    checkout; the wrapper itself exits 0. ``verify`` recomputes this script
    from the recorded command, so the command Witness saw is the one in the
    statement.
    """
    return f'({command})\nprintf %s "$?" > "$0"\n'


def _witness(
    step: str,
    key: Path | None,
    out: Path,
    cwd: Path,
    cmd: list[str],
    tsa: str | None = TSA_URL,
    token_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    full = [
        _witness_bin(),
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
    r = subprocess.run(full, cwd=cwd, capture_output=True, text=True, env=_witness_env())
    if r.returncode != 0 or not out.exists():
        raise RunError(f"witness run ({step}) failed:\n{r.stderr[-2000:]}")
    envelope, stmt = _decode_envelope(out)
    return envelope, _witness_sections(stmt)


def sign_statement(
    statement: dict[str, Any], key: Path | None, tsa: str | None, token_path: Path | None = None
) -> dict[str, Any]:
    """The statement as a DSSE envelope signed by the researcher (``witness sign``, same signer as the steps).

    The payload is the canonical statement, byte for byte: what the bundle
    id hashes is what the signature covers, so nothing under ``predicate``
    can be edited after the fact.
    """
    with tempfile.TemporaryDirectory(prefix="amber-sign-") as tmp:
        src, dst = Path(tmp) / "statement.json", Path(tmp) / "statement.dsse.json"
        src.write_bytes(_canonical(statement))
        full = [
            _witness_bin(),
            "sign",
            "-f",
            str(src),
            "-o",
            str(dst),
            "-t",
            STATEMENT_TYPE,
            *_signer_args(key, token_path),
            *(["--timestamp-servers", tsa] if tsa else []),
        ]
        r = subprocess.run(full, capture_output=True, text=True, env=_witness_env())
        if r.returncode != 0 or not dst.exists():
            raise RunError(f"witness sign failed:\n{r.stderr[-2000:]}")
        envelope = json.loads(dst.read_text())
    if base64.b64decode(envelope["payload"]) != _canonical(statement):
        raise RunError("witness sign changed the statement payload")
    return envelope


def _signing(key: Path | None, envelopes: dict[str, dict[str, Any]], tsa: str | None) -> dict[str, Any]:
    """What the bundle records about its signer: a key fingerprint, or the identity in the Fulcio certificates.

    Witness asks Fulcio for a certificate per step, so one login yields one certificate per envelope.
    """
    if key is not None:
        return {"method": "key", "key_fingerprint": key_fingerprint(key), "timestamp_authority": tsa}
    from .identity import certificate_identity, signature_chain

    certs = {}
    for name, env in envelopes.items():
        sig = next((s for s in env["signatures"] if s.get("certificate")), None)
        if sig is None:
            raise RunError(f"witness signed the {name} envelope without a certificate; --identity needs Fulcio")
        certs[name] = certificate_identity(signature_chain(sig)[0])
    first = next(iter(certs.values()))
    return {
        "method": "identity",
        "identity": first["subject"],
        "issuer": first["issuer"],
        "certificates_sha256": {name: c["certificate_sha256"] for name, c in certs.items()},
        "timestamp_authority": tsa,
    }


def compare_rerun(
    first: dict[str, Any], experiment: dict[str, Any] | None, claims: list[dict[str, Any]]
) -> dict[str, Any]:
    """Outputs and claims of this run against the bundle it repeats; ``drift`` is a verdict change, or an output change when nothing was measured."""
    first_pred = first["statement"]["predicate"]
    first_exp = first_pred.get("experiment") or {}
    first_claims = first_pred.get("claims") or []
    mine = {o["path"]: o["sha256"] for o in (experiment or {}).get("outputs") or []}
    outputs = [
        {
            "path": o["path"],
            "first": o["sha256"],
            "rerun": mine.get(o["path"]),
            "result": "identical" if mine.get(o["path"]) == o["sha256"] else "changed",
        }
        for o in first_exp.get("outputs") or []
    ]
    again = {c["id"]: c for c in claims}
    compared = [
        {
            "id": c["id"],
            "first": {"measured": c.get("measured"), "verdict": c.get("verdict")},
            "rerun": {
                "measured": again.get(c["id"], {}).get("measured"),
                "verdict": again.get(c["id"], {}).get("verdict"),
            },
            "result": "same" if again.get(c["id"], {}).get("verdict") == c.get("verdict") else "changed",
        }
        for c in first_claims
    ]
    measured = [c for c in compared if c["first"]["measured"] is not None]
    drift = any(c["result"] == "changed" for c in compared) or (
        not measured and any(o["result"] == "changed" for o in outputs)
    )
    return {"of": first["id"], "outputs": outputs, "claims": compared, "drift": drift}


def _store_bundle(store: Any, bundle: dict[str, Any]) -> None:
    store.write(bundle["id"], _canonical(bundle), "application/vnd.in-toto+json")


def execute(
    artifact: str,
    ref: str | None,
    key: Path | None,
    entry: dict[str, Any],
    store: AttestationStore,
    rerun_of: dict[str, Any] | None = None,
    tsa: str | None = TSA_URL,
    identity: bool = False,
    publish: str | None = None,
    allow_dirty: bool = False,
    clone_local: bool = False,
) -> dict[str, Any]:
    """Run, sign, store; then, with ``publish`` (a Rekor URL), record the envelopes there.

    ``rerun_of`` is the first bundle when this run repeats it: the comparison
    goes into the predicate before the id is computed, so one bundle is
    written, with its outputs under that id. ``clone_local`` clones a local
    path too, so a rerun executes the recorded commit and not the working tree.
    """
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
        if _is_url(artifact) or clone_local:
            repo = _clone(artifact, ref, tmpdir / "artifact")
        else:
            repo = Path(artifact).resolve()
            if not repo.is_dir():
                raise RunError(f"{artifact} is not a directory")
        dirty = _git_dirty(repo)
        if dirty and not allow_dirty:
            raise RunError(
                "the checkout has uncommitted changes to tracked files, so a run would not be a run of the commit: "
                f"{', '.join(dirty[:5])}{', ...' if len(dirty) > 5 else ''}; commit or stash them, or pass --allow-dirty "
                "to record the run without a commit"
            )
        token_path: Path | None = None
        if identity:
            from .identity import identity_token

            token_path = tmpdir / "oidc.token"
            token_path.touch(mode=0o600)
            token_path.write_text(identity_token())  # one login per run; both Witness steps reuse it
        started = datetime.now(UTC).isoformat()

        audit_file = tmpdir / "amber-audit.json"  # outside the checkout: the audit leaves nothing in the repository
        audit_env, audit_w = _witness(
            "amber-audit",
            key,
            tmpdir / "audit.json",
            repo,
            [
                "sh",
                "-c",
                f"darnit audit . -f amber --output json --no-fail > {audit_file}",
            ],  # darnit: on PATH, see _witness_env
            tsa,
            token_path,
        )
        audit = json.loads(audit_file.read_text())

        experiment: dict[str, Any] | None = None
        exp_env: dict[str, Any] | None = None
        captured: dict[str, bytes] = {}
        if exp_cmd:
            exit_file = tmpdir / "exit"
            exp_env, exp_w = _witness(
                "experiment",
                key,
                tmpdir / "experiment.json",
                repo,
                ["sh", "-c", wrap_command(exp_cmd), str(exit_file)],
                tsa,
                token_path,
            )
            if not exit_file.is_file():
                raise RunError("the experiment's exit status was not recorded")
            products = exp_w.get("product") or {}
            if exp_outputs is None:
                exp_outputs = _infer_outputs(products)
            outputs = []
            for p in exp_outputs:
                p = safe_rel(p)
                digest = (products.get(p) or {}).get("digest", {}).get("sha256")
                f = repo / p
                data = f.read_bytes() if p in products and f.is_file() else None
                if data is not None and hashlib.sha256(data).hexdigest() != digest:
                    data = None  # changed after Witness hashed it: not the experiment's bytes
                if data is not None:
                    captured[p] = data
                outputs.append(
                    {
                        "path": p,
                        "sha256": digest,
                        "captured": p in products,
                        "stored": data is not None and len(data) <= MAX_STORED_OUTPUT,
                    }
                )
            experiment = {
                "command": exp_cmd,
                "exit_code": int(exit_file.read_text().strip() or -1),
                "outputs": outputs,
                "products": {p: d.get("digest", {}).get("sha256") for p, d in products.items()},
            }
        blobs = {o["path"]: captured[o["path"]] for o in (experiment or {}).get("outputs") or [] if o["stored"]}
        for c in claims:
            measure_claim(c, captured.get)  # only what the experiment produced, as Witness hashed it
        for c in claims:
            c["matches_expected"] = (c["verdict"] == c["expected_verdict"]) if c.get("expected_verdict") else None
        commit = None if dirty else _git_commit(repo)
        subject_name = public_url(artifact if _is_url(artifact) else (_git_remote(repo) or str(repo)))

        envelopes = {"amber-audit": audit_env, **({"experiment": exp_env} if exp_env else {})}
        signing = _signing(key, envelopes, tsa)
        predicate = {
            "started_at": started,
            "environment": _environment(),
            "signing": signing,
            "corpus_entry": entry.get("id"),
            "entry": {
                "source": entry.get("_source", "file"),
                "artifact": {"clone": subject_name, "ref": commit, "dirty": bool(dirty)},
                "run": {"command": exp_cmd, "outputs": exp_outputs},
                "environment": entry.get("environment"),
            },
            "audit": {
                "framework": "amber",
                "command": audit_w.get("command-run", {}).get("cmd"),
                "exit_code": audit_w.get("command-run", {}).get("exitcode"),
                "results": [
                    {"id": x.get("id") or x.get("control_id"), "status": x.get("status")}
                    for x in audit.get("results", [])
                ],
            },
            "experiment": experiment,
            "claims": claims,
            "verdict": overall_verdict(claims),
            "reruns": compare_rerun(rerun_of, experiment, claims) if rerun_of else None,
            "witness_attestations": sorted(audit_w),
            # The statement, and so the bundle id, covers the envelopes: a bundle cannot swap them.
            "witness_envelopes_sha256": {
                name: hashlib.sha256(_canonical(env)).hexdigest() for name, env in envelopes.items()
            },
        }
        statement = {
            "_type": STATEMENT_TYPE,
            "subject": [{"name": subject_name, "digest": {"gitCommit": commit} if commit else {}}],
            "predicateType": PREDICATE_TYPE,
            "predicate": predicate,
        }
        statement_env = sign_statement(statement, key, tsa, token_path)

    bundle_id = hashlib.sha256(_canonical(statement)).hexdigest()
    bundle = {
        "id": bundle_id,
        "statement": statement,
        "statement_envelope": statement_env,
        "witness_envelopes": envelopes,
        "publication": None,
    }
    _store_bundle(store, bundle)
    for path, data in blobs.items():
        write_blob(store, bundle_id, path, data)
    if publish:
        from .publish import publish_envelope

        try:
            bundle["publication"] = {
                name: publish_envelope(env, key, publish)
                for name, env in {"statement": statement_env, **envelopes}.items()
            }
        except Exception as e:  # noqa: BLE001 - the bundle is signed and stored; say what did not get published
            raise RunError(
                f"bundle {bundle_id} is stored; publishing to {publish} failed: {type(e).__name__}: {e}"
            ) from e
        _store_bundle(store, bundle)
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
    publish: str | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    """``command`` (argv after ``--``) overrides the entry's run.command; with no entry, everything else is inferred."""
    entry = load_entry(claims)
    if artifact in (".", "") and (entry.get("artifact") or {}).get("clone"):
        artifact = entry["artifact"]["clone"]
        ref = ref or entry["artifact"].get("ref")
    if command:
        entry = {**entry, "run": {**(entry.get("run") or {}), "command": shlex.join(command)}}
        if not claims:
            entry["_source"] = "inferred"
    return execute(
        artifact, ref, key, entry, store, tsa=tsa, identity=identity, publish=publish, allow_dirty=allow_dirty
    )
