"""run / verify / rerun, with a fake ``witness`` on PATH that runs the command and signs for real."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import ed25519
from darnit_amber import rerun as amber_rerun
from darnit_amber import run as amber_run
from darnit_amber.handlers import repro_run_verified_handler
from darnit_amber.utils import PAYLOAD_TYPE, key_fingerprint

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus

# Runs the command, records its stdout and the files it changed, and signs with -k.
FAKE_WITNESS = """
import base64, hashlib, json, subprocess, sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization

args = sys.argv[1:]
opt = lambda flag: args[args.index(flag) + 1]
def envelope(payload, ptype):
    key = serialization.load_pem_private_key(Path(opt("-k")).read_bytes(), None)
    sig = key.sign(b"DSSEv1 %d %s %d " % (len(ptype), ptype.encode(), len(payload)) + payload)
    return {"payloadType": ptype, "payload": base64.b64encode(payload).decode(), "signatures": [{"sig": base64.b64encode(sig).decode()}]}
def digests():
    return {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in Path().rglob("*") if p.is_file() and ".git" not in p.parts}
if args[0] == "sign":
    Path(opt("-o")).write_text(json.dumps(envelope(Path(opt("-f")).read_bytes(), opt("-t"))))
else:
    cmd, before = args[args.index("--") + 1 :], digests()
    done = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(done.stdout)
    products = {p: {"digest": {"sha256": d}} for p, d in digests().items() if before.get(p) != d}
    stmt = {"predicateType": "https://witness.dev/attestation-collection/v0.1", "predicate": {"attestations": [
        {"type": "https://witness.dev/attestations/product/v0.1", "attestation": products},
        {"type": "https://witness.dev/attestations/command-run/v0.1", "attestation": {"cmd": cmd, "stdout": done.stdout}}]}}
    Path(opt("-o")).write_text(json.dumps(envelope(json.dumps(stmt).encode(), "witness")))
"""


def _keypair(directory: Path) -> tuple[Path, Path]:
    private = ed25519.Ed25519PrivateKey.generate()
    key, pub = directory / "key.pem", directory / "key.pub"
    key.write_bytes(private.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()))
    pub.write_bytes(private.public_key().public_bytes(ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo))
    return key, pub


@pytest.fixture
def amber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An experiment in a git repository, a fake witness, a key pair, and one recorded run."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/witness").write_text(f"#!{sys.executable}\n{FAKE_WITNESS}")
    (tmp_path / "bin/witness").chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setattr(amber_rerun, "timestamps", lambda e: [{"signature": 0, "trusted": True}])
    key, pub = _keypair(tmp_path)

    art = tmp_path / "artifact"
    art.mkdir()
    (art / "exp.sh").write_text("mkdir -p results\necho answer=42 > results/out.txt\n")
    git = ["git", "-C", str(art), "-c", "user.name=t", "-c", "user.email=t@x"]
    subprocess.run(["git", "init", "-q", str(art)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)

    bundle = art / ".amber"
    first = amber_run.run(str(art), key, "sh exp.sh", bundle, results=["results/"], trace=False)
    return {"art": art, "key": key, "pub": pub, "bundle": bundle, "id": first["id"]}


def _tamper(amber, change) -> None:
    """Edit the statement inside the first run's signed envelope."""
    path = amber["bundle"] / "runs" / amber["id"] / "amber.intoto.json"
    envelope = json.loads(path.read_text())
    statement = json.loads(base64.b64decode(envelope["payload"]))
    change(statement)
    envelope["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
    path.write_text(json.dumps(envelope))


def test_a_run_is_recorded_and_verifies(amber):
    report = amber_rerun.verify(amber["bundle"], amber["id"], pubkey=amber["pub"])
    assert report["verified"], amber_rerun.failed(report)
    assert (amber["bundle"] / "runs" / amber["id"] / "outputs/results/out.txt").read_text() == "answer=42\n"


def test_verify_fails_a_changed_run_or_the_wrong_key(amber, tmp_path):
    (tmp_path / "other").mkdir()
    _, other = _keypair(tmp_path / "other")
    assert not amber_rerun.verify(amber["bundle"], amber["id"], pubkey=other)["verified"]

    _tamper(amber, lambda s: s["predicate"].update(exit_code=7))
    assert not amber_rerun.verify(amber["bundle"], amber["id"], pubkey=amber["pub"])["verified"]


def test_a_rerun_gets_the_same_results(amber):
    consent = lambda command, recipe: True  # noqa: E731
    result = amber_rerun.rerun(
        amber["bundle"],
        amber["id"],
        consent,
        key=amber["key"],
        pubkey=amber["pub"],
        source=str(amber["art"]),
        host_environment=True,
    )
    assert result["changed"] == []


def test_a_keyless_run_verifies_only_for_its_signer(amber, monkeypatch):
    """Sigstore is faked: the bundle verifies only for the identity and issuer that signed it."""

    class Token:
        identity, federated_issuer = "researcher@uni.edu", "https://github.com/login/oauth"

    def sign(statement, token):
        envelope = {"payload": base64.b64encode(statement).decode(), "payloadType": PAYLOAD_TYPE, "signatures": []}
        return {"dsseEnvelope": envelope, "signer": [token.identity, token.federated_issuer]}

    def check(bundle, identity, issuer):
        signed = bundle["signer"] == [identity, issuer]
        return base64.b64decode(bundle["dsseEnvelope"]["payload"]) if signed else None

    monkeypatch.setattr(amber_run, "identity_token", Token)
    monkeypatch.setattr(amber_run, "sign_keyless", sign)
    monkeypatch.setattr(amber_rerun, "verify_keyless", check)

    bundle = amber["art"] / ".amber-keyless"
    run_id = amber_run.run(str(amber["art"]), None, "sh exp.sh", bundle, results=["results/"], trace=False)["id"]
    assert amber_rerun.verify(bundle, run_id, identity=Token.identity, issuer=Token.federated_issuer)["verified"]
    assert not amber_rerun.verify(bundle, run_id, identity="someone@else.org", issuer=Token.federated_issuer)[
        "verified"
    ]


def test_the_audit_passes_only_a_verified_run_by_a_trusted_signer(amber):
    """repro_run_verified (control RE-02.03)."""
    ctx = HandlerContext(local_path=str(amber["art"]))
    trusted = {"trusted_keys": [key_fingerprint(amber["pub"])]}
    assert repro_run_verified_handler({}, ctx).status == HandlerResultStatus.INCONCLUSIVE  # no trusted signer
    assert repro_run_verified_handler(trusted, ctx).status == HandlerResultStatus.PASS

    _tamper(amber, lambda s: s["predicate"].update(exit_code=7))
    assert repro_run_verified_handler(trusted, ctx).status == HandlerResultStatus.FAIL
