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
import math
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
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


def default_store() -> Path:
    """Where bundles go without ``--out``: under darnit's data root, next to the key.

    Not the working directory: ``darnit-amber run`` defaults to the artifact at
    ``.``, and a store created inside it is an untracked directory that makes
    the next run refuse as dirty (review, Nov 11 and 13).
    """
    return user_data_root() / "amber" / "runs"


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
    """``url`` without credentials, query or fragment: a token in a clone URL must not end up in a shared bundle."""
    if not url.startswith(("https://", "http://", "ssh://")):
        return url
    p = urlsplit(url)
    if not (p.username or p.password or p.query or p.fragment):
        return url
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    if p.scheme == "ssh" and p.username:
        host = f"{p.username}@{host}"  # the ssh user (git@) is part of the address, a password is not
    # A clone URL needs no query string or fragment; ``?access_token=`` is a credential by another route.
    return urlunsplit((p.scheme, host, p.path, "", ""))


def _clone(url: str, ref: str | None, dest: Path, keep_remote: bool = True) -> Path:
    r = subprocess.run(["git", "clone", "-q", url, str(dest)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RunError(f"clone failed: {r.stderr.strip()}")
    if not keep_remote:
        # A clone of a local path would carry that path as `origin`, and Witness's git attestor records
        # remotes verbatim into the signed envelope. The statement names the artifact as local/<name>.
        subprocess.run(["git", "-C", str(dest), "remote", "remove", "origin"], check=True, capture_output=True)
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
    """Files that differ from HEAD, untracked ones included: a run that can read them is not a run of the commit.

    Files git ignores are not listed: a clean checkout is run from a fresh
    clone of its commit, where they do not exist.
    """
    r = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True
    )
    return [line[3:] for line in r.stdout.splitlines() if line.strip()]


def _local_subject(repo: Path) -> str:
    """Name for a local artifact without a remote: its directory name, not where it lives on the researcher's disk."""
    return f"local/{repo.name}"


def _infer_outputs(products: dict[str, Any]) -> list[str]:
    """Files the command created or changed, as Witness saw them, minus git's own and anything not inside the checkout."""
    out = []
    for p in products:
        if p.startswith(".git/") or p.startswith(RECORD_DIR + "/"):
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


# Where a run writes what it needs Witness to see: the experiment's exit status and the audit report.
# Inside the checkout, so the product attestor hashes them; removed again after each step.
RECORD_DIR = ".amber"
EXIT_RECORD = f"{RECORD_DIR}/exit"
AUDIT_RECORD = f"{RECORD_DIR}/audit.json"

# Allowlisted variables whose value is a path: scrubbed before recording (SHELL can be ~/.local/bin/fish, #747).
_PATH_VARIABLES = ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONPATH", "SHELL")
_SYSTEM_PREFIXES = ("/usr", "/opt", "/lib", "/lib64", "/etc", "/nix", "/bin", "/sbin", "/snap")


def _scrub_path(value: str, checkout: Path | None) -> str:
    """Each path in ``value`` as what it is, not where the researcher keeps it.

    Under the checkout: ``$CHECKOUT/...``; under the home directory:
    ``$HOME/...``; under a system prefix: unchanged; anywhere else
    (``/scratch/<user>/...``, ``/Volumes/...``): ``$ELSEWHERE/<last name>``.
    A relative entry is kept as written.
    """
    home = Path.home()
    out = []
    for part in value.split(os.pathsep):
        p = Path(part)
        if not p.is_absolute():
            out.append(part)
        elif checkout is not None and p.is_relative_to(checkout):
            out.append(str(Path("$CHECKOUT") / p.relative_to(checkout)))
        elif p.is_relative_to(home):
            out.append(str(Path("$HOME") / p.relative_to(home)))
        elif any(p == Path(pre) or p.is_relative_to(pre) for pre in _SYSTEM_PREFIXES):
            out.append(part)
        else:
            out.append(str(Path("$ELSEWHERE") / p.name))
    return os.pathsep.join(out)


def _environment(checkout: Path | None = None) -> dict[str, Any]:
    """What darnit-amber asked the host and wrote down. Not observed by Witness; see ``provenance``."""
    mem = None
    try:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        pass
    variables = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    for k in _PATH_VARIABLES:
        if k in variables:
            variables[k] = _scrub_path(variables[k], checkout)
    return {
        "recorded_by": "darnit-amber",
        "image_digest": None,  # pinned container image: darnit #677 step B
        "darnit": _version("darnit-core"),
        "darnit_amber": _version("darnit-amber"),
        "python": platform.python_version(),
        "os": platform.platform(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": mem,
        "variables": variables,
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


_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
# Looks like a number without being one in plain decimal: inf, nan, 1_000, 0x10, 1e400 ... Such a value is
# refused rather than compared as text, so ``== 1_000`` cannot hold on the string alone.
_NUMBER_LIKE = re.compile(r"[+-]?(?:inf(?:inity)?|nan|0[xX][0-9a-fA-F_]+|[\d_]*\.?[\d_]+(?:[eE][+-]?[\d_]+)?)", re.I)


def _number(s: Any) -> Decimal | None:
    """A finite number in plain decimal notation, exactly as written; ``inf``, ``nan`` and ``1_000`` are not numbers here.

    Decimal, not float: a measurement and a threshold that differ past the 53rd
    bit (9007199254740992 vs 9007199254740993) are the same float, and a claim
    that misses its threshold must not come out REPRODUCED (review, Nov 13).
    """
    if isinstance(s, bool):
        return None
    if isinstance(s, int):
        return Decimal(s)
    if isinstance(s, float):
        return Decimal(repr(s)) if math.isfinite(s) else None
    if not isinstance(s, str) or not _NUMBER.fullmatch(s.strip()):
        return None
    v = Decimal(s.strip())
    return v if v.is_finite() else None


def compare(value: str, threshold: str, tolerance: Any) -> tuple[bool | None, str]:
    """``value`` against ``threshold`` (``op number`` or ``op text``): (holds, reason); ``None`` when not comparable.

    Ordering operators need two numbers; ``==`` and ``!=`` fall back to a
    text comparison, where the tolerance does not apply, but only for text
    that does not look like a number: ``inf``, ``nan``, ``1_000`` or ``0x10``
    on either side is not comparable at all.
    """
    op, want = _parse_threshold(threshold)
    a, b = _number(value), _number(want)
    tol = _number(tolerance) if tolerance is not None else Decimal(0)
    if tol is None or tol < 0:
        return None, f"tolerance {tolerance!r} is not a finite number >= 0"
    if a is None or b is None:
        for side, text in (("measured", value), ("threshold", want)):
            if _number(text) is None and isinstance(text, str) and _NUMBER_LIKE.fullmatch(text.strip()):
                return None, f"{side} {text!r} is not a finite number in plain decimal notation"
        if op in ("==", "!="):
            same = value.strip() == want.strip()
            return (same if op == "==" else not same), f"measured {value!r} {op} {want!r}"
        return None, f"{op} needs two numbers: measured {value!r}, threshold {want!r}"
    strict = {"==": a == b, "!=": a != b, "<=": a <= b, ">=": a >= b, "<": a < b, ">": a > b}[op]
    holds = {
        "==": abs(a - b) <= tol,
        "!=": abs(a - b) > tol,
        "<=": a <= b + tol,
        ">=": a >= b - tol,
        "<": a < b + tol,
        ">": a > b - tol,
    }[op]
    note = ""
    if tol:
        shown = f"{tol.normalize():f}"
        note = f" (holds only with tolerance {shown})" if holds and not strict else f" (tolerance {shown})"
    return holds, f"measured {value} {op} {want}" + note


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
            scale = _number(m["scale"])
            if scale is None:
                claim["reason"] = f"scale {m['scale']!r} is not a number"
                return
            value = f"{(n * scale).normalize():f}"
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


def _signer_args(key: Path | None) -> list[str]:
    """``-k key``: the researcher's key, by absolute path because Witness runs inside the checkout."""
    if key is None:
        raise RunError("a signing key is required")
    return ["-k", str(key.resolve())]


def _witness_bin() -> str:
    witness = shutil.which("witness")
    if not witness:
        raise RunError("witness binary not found on PATH (https://github.com/in-toto/witness)")
    return witness


def _witness_env() -> dict[str, str]:
    """The environment Witness and the experiment run in: this one, plus darnit's own bin dir."""
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
    return env


def wrap_command(command: str) -> str:
    """The shell script Witness runs for the experiment.

    Witness writes no attestation when the command fails, and a failed
    experiment is a result worth recording. The command runs in a subshell
    and its exit status goes to the file named by ``$0`` (``.amber/exit``
    inside the checkout, so Witness hashes it as a product); the wrapper
    itself exits 0. ``verify`` recomputes this script from the recorded
    command, so the command Witness saw is the one in the statement.
    """
    return f'(\n{command}\n)\nprintf %s "$?" > "$0"\n'  # the ) on its own line: a trailing # comment cannot eat it


def audit_command() -> str:
    """The audit step's shell command; ``verify`` recomputes it, so the audit Witness ran is the one recorded."""
    return f"darnit audit . -f amber --output json --no-fail > {AUDIT_RECORD}"


def exit_status(blob: bytes) -> int:
    """The exit status an ``.amber/exit`` record holds; -1 when the wrapper wrote nothing usable."""
    try:
        return int(blob.decode().strip())
    except ValueError:
        return -1


def audit_results(report: dict[str, Any]) -> list[dict[str, Any]]:
    """What the statement keeps of an audit report: control id and status, nothing else."""
    return [{"id": x.get("id") or x.get("control_id"), "status": x.get("status")} for x in report.get("results", [])]


def _record(repo: Path, rel: str, witness: dict[str, Any], what: str) -> tuple[bytes, dict[str, Any]]:
    """Read a file the step wrote under ``.amber/`` and pair it with the digest Witness recorded for it.

    The bytes must match that digest; otherwise the file is not what Witness
    saw and the run is not recorded.
    """
    f = repo / rel
    if not f.is_file():
        raise RunError(f"{what} was not recorded ({rel} missing)")
    data = f.read_bytes()
    digest = ((witness.get("product") or {}).get(rel) or {}).get("digest", {}).get("sha256")
    if digest is None:
        raise RunError(f"Witness recorded no product for {rel}; {what} cannot be attested")
    if hashlib.sha256(data).hexdigest() != digest:
        raise RunError(f"{rel} changed after Witness hashed it; {what} cannot be attested")
    return data, {"path": rel, "sha256": digest}


def _witness(
    step: str,
    key: Path | None,
    out: Path,
    cwd: Path,
    cmd: list[str],
    tsa: str | None = TSA_URL,
) -> tuple[dict[str, Any], dict[str, Any]]:
    full = [
        _witness_bin(),
        "run",
        "--step",
        step,
        "--attestations",
        WITNESS_ATTESTORS,
        *_signer_args(key),
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


def sign_statement(statement: dict[str, Any], key: Path | None, tsa: str | None) -> dict[str, Any]:
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
            *_signer_args(key),
            *(["--timestamp-servers", tsa] if tsa else []),
        ]
        r = subprocess.run(full, capture_output=True, text=True, env=_witness_env())
        if r.returncode != 0 or not dst.exists():
            raise RunError(f"witness sign failed:\n{r.stderr[-2000:]}")
        envelope = json.loads(dst.read_text())
    if base64.b64decode(envelope["payload"]) != _canonical(statement):
        raise RunError("witness sign changed the statement payload")
    return envelope


def _signing(key: Path, tsa: str | None) -> dict[str, Any]:
    """What the bundle records about its signer: the key's fingerprint, and the timestamp authority used."""
    return {"method": "key", "key_fingerprint": key_fingerprint(key), "timestamp_authority": tsa}


def compare_rerun(
    first: dict[str, Any], experiment: dict[str, Any] | None, claims: list[dict[str, Any]]
) -> dict[str, Any]:
    """This run against the bundle it repeats: exit status, every output path of either run, and the claims.

    ``drift`` is a changed exit status, a changed claim verdict, or, when
    nothing was measured, any output that changed, appeared or went missing.
    A measured claim decides for its outputs: the same number from a file
    with a new timestamp in it is not drift.
    """
    first_pred = first["statement"]["predicate"]
    first_exp = first_pred.get("experiment") or {}
    first_claims = first_pred.get("claims") or []
    theirs = {o["path"]: o["sha256"] for o in first_exp.get("outputs") or []}
    mine = {o["path"]: o["sha256"] for o in (experiment or {}).get("outputs") or []}
    outputs = []
    for path in sorted(theirs.keys() | mine.keys()):
        a, b = theirs.get(path), mine.get(path)
        result = "identical" if a == b else "missing" if b is None else "added" if a is None else "changed"
        outputs.append({"path": path, "first": a, "rerun": b, "result": result})
    exit_codes = {"first": first_exp.get("exit_code"), "rerun": (experiment or {}).get("exit_code")}
    if exit_codes["first"] is None or exit_codes["rerun"] is None:
        exit_codes["result"] = "unknown"  # a bundle without a recorded exit status: nothing to compare
    else:
        exit_codes["result"] = "same" if exit_codes["first"] == exit_codes["rerun"] else "changed"
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
    drift = (
        exit_codes["result"] == "changed"
        or any(c["result"] == "changed" for c in compared)
        or (not measured and any(o["result"] != "identical" for o in outputs))
    )
    return {"of": first["id"], "exit_code": exit_codes, "outputs": outputs, "claims": compared, "drift": drift}


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
    allow_dirty: bool = False,
) -> dict[str, Any]:
    """Run, sign, store.

    ``rerun_of`` is the first bundle when this run repeats it: the comparison
    goes into the predicate before the id is computed, so one bundle is
    written, with its outputs under that id. A URL, and a local path that is
    clean or run at a named ``ref``, is executed from a fresh clone of the
    commit; only ``allow_dirty`` runs a working tree in place.
    """
    darnit_bin = Path(sys.executable).parent / "darnit"
    if not darnit_bin.exists():
        raise RunError(f"darnit CLI not found next to {sys.executable}")
    key = key or default_key()
    exp_cmd = (entry.get("run") or {}).get("command")
    exp_outputs = (entry.get("run") or {}).get("outputs")  # None: infer from Witness products
    claims = _claims(entry)

    _witness_bin()  # before any clone: nothing to fetch if there is nothing to run under
    with tempfile.TemporaryDirectory(prefix="amber-run-") as tmp:
        tmpdir = Path(tmp)
        dirty: list[str] = []
        local_name: str | None = None
        if _is_url(artifact):
            repo = _clone(artifact, ref, tmpdir / "artifact")
        else:
            source = Path(artifact).resolve()
            if not source.is_dir():
                raise RunError(f"{artifact} is not a directory")
            local_name = _git_remote(source) or _local_subject(source)
            if ref is None:  # a run at HEAD; at a named commit the clone below contains exactly that commit
                dirty = _git_dirty(source)
            if dirty and not allow_dirty:
                raise RunError(
                    "the checkout has uncommitted changes or untracked files, so a run could read what the commit "
                    f"does not contain: {', '.join(dirty[:5])}{', ...' if len(dirty) > 5 else ''}; commit or remove "
                    "them, or pass --allow-dirty to record the run without a commit"
                )
            if dirty:
                repo = source  # --allow-dirty: run in place, record no commit
            else:
                # A clean checkout is run from a fresh clone of its commit: files git ignores
                # (caches, data, precomputed results) are not there, so the experiment reads
                # only what the commit contains. The same path rerun takes.
                repo = _clone(str(source), ref, tmpdir / "artifact", keep_remote=False)
        started = datetime.now(UTC).isoformat()

        record_dir = repo / RECORD_DIR
        # The record dir is removed after each step, success or failure: nothing of darnit's is left for the
        # experiment to read, or in the user's checkout when --allow-dirty ran in place.
        record_dir.mkdir()
        try:
            audit_env, audit_w = _witness(
                "amber-audit",
                key,
                tmpdir / "audit.json",
                repo,
                ["sh", "-c", audit_command()],  # darnit: on PATH, see _witness_env
                tsa,
            )
            audit_blob, audit_record = _record(repo, AUDIT_RECORD, audit_w, "the audit report")
        finally:
            shutil.rmtree(record_dir, ignore_errors=True)
        audit = json.loads(audit_blob)

        experiment: dict[str, Any] | None = None
        exp_env: dict[str, Any] | None = None
        captured: dict[str, bytes] = {}
        exit_record: dict[str, Any] | None = None
        if exp_cmd:
            record_dir.mkdir()
            try:
                exp_env, exp_w = _witness(
                    "experiment",
                    key,
                    tmpdir / "experiment.json",
                    repo,
                    ["sh", "-c", wrap_command(exp_cmd), EXIT_RECORD],
                    tsa,
                )
                exit_blob, exit_record = _record(repo, EXIT_RECORD, exp_w, "the experiment's exit status")
            finally:
                shutil.rmtree(record_dir, ignore_errors=True)
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
                "exit_code": exit_status(exit_blob),
                "exit_status": exit_record,
                "outputs": outputs,
                "products": {p: d.get("digest", {}).get("sha256") for p, d in products.items()},
            }
        blobs = {o["path"]: captured[o["path"]] for o in (experiment or {}).get("outputs") or [] if o["stored"]}
        blobs[AUDIT_RECORD] = audit_blob  # the two records are stored too, so verify can read what Witness hashed
        if exit_record:
            blobs[EXIT_RECORD] = exit_blob
        for c in claims:
            measure_claim(c, captured.get)  # only what the experiment produced, as Witness hashed it
            c["signed_by"] = "signing"  # the run's signer stands behind this claim; claim() marks its own
        for c in claims:
            c["matches_expected"] = (c["verdict"] == c["expected_verdict"]) if c.get("expected_verdict") else None
        commit = None if dirty else _git_commit(repo)
        subject_name = public_url(artifact if _is_url(artifact) else local_name or _local_subject(repo))

        envelopes = {"amber-audit": audit_env, **({"experiment": exp_env} if exp_env else {})}
        signing = _signing(key, tsa)
        predicate = {
            "started_at": started,
            # Which parts of this predicate ``verify`` checks against a Witness envelope, and which the tool
            # wrote down itself. The exit status and the audit report are written inside the checkout
            # (``.amber/``) so Witness hashes them as products; ``verify`` reads the stored copies back
            # against those digests and recomputes ``exit_code`` and ``audit.results`` from them.
            "provenance": {
                "observed": [
                    "audit.command",
                    "audit.exit_code",
                    "audit.report",
                    "audit.results",
                    "experiment.command",
                    "experiment.exit_code",
                    "experiment.exit_status",
                    "experiment.outputs",
                    "experiment.products",
                    "witness_envelopes_sha256",
                ],
                "self_reported": ["started_at", "environment", "signing", "entry", "claims", "verdict"],
            },
            "environment": _environment(repo),
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
                "report": audit_record,
                "results": audit_results(audit),
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
        statement_env = sign_statement(statement, key, tsa)

    bundle_id = hashlib.sha256(_canonical(statement)).hexdigest()
    bundle = {
        "id": bundle_id,
        "statement": statement,
        "statement_envelope": statement_env,
        "witness_envelopes": envelopes,
        "publication": None,  # reserved: where a transparency-log record goes once the bundle is published
    }
    _store_bundle(store, bundle)
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
    return execute(artifact, ref, key, entry, store, tsa=tsa, allow_dirty=allow_dirty)
