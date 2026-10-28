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


class RunError(RuntimeError):
    pass


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
                "unit": c.get("unit"),
                "threshold_source": c.get("source"),
                "measurement_protocol": c.get("measurement_protocol"),
                "measured": None,
                "verdict": "NOT_COMPARABLE",
                "reason": "claim measurement not implemented in this version",
            }
        )
    return out


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _witness(step: str, key: Path, out: Path, cwd: Path, cmd: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
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
        "-k",
        str(key),
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


def run(artifact: str, ref: str | None, key: Path, claims: Path | None, store: AttestationStore) -> dict[str, Any]:
    darnit_bin = Path(sys.executable).parent / "darnit"
    if not darnit_bin.exists():
        raise RunError(f"darnit CLI not found next to {sys.executable}")
    entry = load_entry(claims)
    exp_cmd = (entry.get("run") or {}).get("command")
    exp_outputs = (entry.get("run") or {}).get("outputs") or []

    with tempfile.TemporaryDirectory(prefix="amber-run-") as tmp:
        tmpdir = Path(tmp)
        repo = _clone(artifact, ref, tmpdir / "artifact") if _is_url(artifact) else Path(artifact).resolve()
        started = datetime.now(UTC).isoformat()

        audit_env, audit_w = _witness(
            "amber-audit",
            key,
            tmpdir / "audit.json",
            repo,
            ["sh", "-c", f"{darnit_bin} audit . -f amber --output json --no-fail > {AUDIT_OUTPUT}"],
        )
        audit = json.loads((repo / AUDIT_OUTPUT).read_text())

        experiment: dict[str, Any] | None = None
        exp_env: dict[str, Any] | None = None
        if exp_cmd:
            exp_env, exp_w = _witness("experiment", key, tmpdir / "experiment.json", repo, ["sh", "-c", exp_cmd])
            products = exp_w.get("product") or {}
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
        commit = _git_commit(repo)

    predicate = {
        "started_at": started,
        "environment": _environment(),
        "corpus_entry": entry.get("id"),
        "audit": {
            "framework": "amber",
            "command": audit_w.get("command-run", {}).get("cmd"),
            "exit_code": audit_w.get("command-run", {}).get("exitcode"),
            "results": [
                {"id": x.get("id") or x.get("control_id"), "status": x.get("status")} for x in audit.get("results", [])
            ],
        },
        "experiment": experiment,
        "claims": _claims(entry),
        "reruns": None,
        "witness_attestations": sorted(audit_w),
    }
    statement = {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": artifact, "digest": {"gitCommit": commit} if commit else {}}],
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
    return bundle
