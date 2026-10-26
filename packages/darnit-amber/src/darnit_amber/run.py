"""``darnit-amber run``: execute the Amber audit under Witness and emit a run bundle.

One bundle per run: an in-toto v1 statement whose predicate is ``amber/run/v1``,
stored next to the Witness DSSE envelope that captured the run. The bundle id is
the sha256 of the canonical statement. See darnit issue #677.
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
    cmd = ["git", "clone", "-q", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [url, str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RunError(f"clone failed: {r.stderr.strip()}")
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
    stmt = json.loads(base64.b64decode(env["payload"]))
    return env, stmt


def _witness_sections(stmt: dict[str, Any]) -> dict[str, Any]:
    return {a["type"].rsplit("/", 2)[-2]: a["attestation"] for a in stmt["predicate"]["attestations"]}


def _claims(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    raw = json.loads(path.read_text()) if path.suffix == ".json" else _load_yaml(path)
    out = []
    for c in raw.get("claims", raw) if isinstance(raw, dict) else raw:
        out.append(
            {
                "id": c.get("id"),
                "statement": c.get("statement"),
                "metric": c.get("metric"),
                "threshold": c.get("threshold"),
                "threshold_source": c.get("source"),
                "measured": None,
                "verdict": "NOT_COMPARABLE",
                "reason": "claim measurement not implemented in this version",
            }
        )
    return out


def _load_yaml(path: Path) -> Any:
    import yaml  # type: ignore[import-untyped]  # darnit already depends on it

    return yaml.safe_load(path.read_text())


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def run(artifact: str, ref: str | None, key: Path, claims: Path | None, store: AttestationStore) -> dict[str, Any]:
    witness = shutil.which("witness")
    if not witness:
        raise RunError("witness binary not found on PATH (https://github.com/in-toto/witness)")
    darnit_bin = Path(sys.executable).parent / "darnit"
    if not darnit_bin.exists():
        raise RunError(f"darnit CLI not found next to {sys.executable}")

    with tempfile.TemporaryDirectory(prefix="amber-run-") as tmp:
        tmpdir = Path(tmp)
        repo = _clone(artifact, ref, tmpdir / "artifact") if _is_url(artifact) else Path(artifact).resolve()
        envelope_path = tmpdir / "witness.json"
        started = datetime.now(UTC).isoformat()
        inner = f"{darnit_bin} audit . -f amber --output json --no-fail > {AUDIT_OUTPUT}"
        cmd = [
            witness,
            "run",
            "--step",
            "amber-audit",
            "--attestations",
            WITNESS_ATTESTORS,
            "-k",
            str(key),
            "-o",
            str(envelope_path),
            "--",
            "sh",
            "-c",
            inner,
        ]
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        if r.returncode != 0 or not envelope_path.exists():
            raise RunError(f"witness run failed:\n{r.stderr[-2000:]}")
        audit = json.loads((repo / AUDIT_OUTPUT).read_text())
        envelope, wstmt = _decode_envelope(envelope_path)
        w = _witness_sections(wstmt)
        commit = _git_commit(repo)

    predicate = {
        "started_at": started,
        "environment": _environment(),
        "command": {
            "argv": w.get("command-run", {}).get("cmd"),
            "exit_code": w.get("command-run", {}).get("exitcode"),
            "answer_file": None,
        },
        "claims": _claims(claims),
        "audit": {
            "framework": "amber",
            "results": [
                {"id": x.get("id") or x.get("control_id"), "status": x.get("status")} for x in audit.get("results", [])
            ],
        },
        "outputs": [{"path": p, "sha256": d.get("sha256")} for p, d in (w.get("product") or {}).items()],
        "reruns": None,
        "witness_attestations": sorted(w),
    }
    statement = {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": artifact, "digest": {"gitCommit": commit} if commit else {}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": predicate,
    }
    bundle_id = hashlib.sha256(_canonical(statement)).hexdigest()
    bundle = {"id": bundle_id, "statement": statement, "witness_envelope": envelope}

    store.write(bundle_id, _canonical(bundle), "application/vnd.in-toto+json")
    return bundle
