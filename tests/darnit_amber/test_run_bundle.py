"""Tests for ``darnit-amber run`` (issue #677, PR A). No witness binary needed."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from darnit_amber import run as amber_run
from darnit_amber.cli import main


def test_claims_from_yaml_are_not_comparable(tmp_path: Path) -> None:
    f = tmp_path / "claims.yaml"
    f.write_text("claims:\n  - id: C1\n    metric: m\n    threshold: '<= 1'\n    source: paper\n")
    claims = amber_run._claims(amber_run.load_entry(f))
    assert len(claims) == 1
    assert claims[0]["id"] == "C1"
    assert claims[0]["threshold_source"] == "paper"
    assert claims[0]["measured"] is None
    assert claims[0]["verdict"] == "NOT_COMPARABLE"


def test_claims_absent_is_empty() -> None:
    assert amber_run._claims(amber_run.load_entry(None)) == []


def test_canonical_is_key_order_independent() -> None:
    a = amber_run._canonical({"b": 1, "a": [1, 2]})
    b = amber_run._canonical({"a": [1, 2], "b": 1})
    assert a == b
    assert json.loads(a) == {"a": [1, 2], "b": 1}


def test_witness_sections_keyed_by_attestor_name() -> None:
    stmt = {
        "predicate": {
            "attestations": [
                {"type": "https://witness.dev/attestations/command-run/v0.1", "attestation": {"exitcode": 0}},
                {"type": "https://witness.dev/attestations/product/v0.1", "attestation": {}},
            ]
        }
    }
    sections = amber_run._witness_sections(stmt)
    assert sections["command-run"] == {"exitcode": 0}
    assert set(sections) == {"command-run", "product"}


def test_run_requires_witness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(amber_run.shutil, "which", lambda _: None)
    rc = main(["run", str(tmp_path), "--key", str(tmp_path / "k"), "--out", str(tmp_path / "out")])
    assert rc == 1
    assert "witness binary not found" in capsys.readouterr().err


def test_entry_run_command_is_read(tmp_path: Path) -> None:
    f = tmp_path / "entry.yaml"
    f.write_text("id: x\nrun:\n  command: 'echo hi > out.txt'\n  outputs: [out.txt]\n")
    e = amber_run.load_entry(f)
    assert e["run"]["command"] == "echo hi > out.txt"
    assert e["run"]["outputs"] == ["out.txt"]


def _claim(**kw):
    base = {
        "id": "c",
        "threshold": "== 3",
        "expected_verdict": "REPRODUCED",
        "measure": {"file": "out.txt", "regex": r"value=(\S+)"},
    }
    base.update(kw)
    return amber_run._claims({"claims": [base]})[0]


def test_measure_reproduced(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("value=3\n")
    c = _claim()
    amber_run.measure_claim(c, tmp_path)
    assert (c["measured"], c["verdict"]) == ("3", "REPRODUCED")


def test_measure_not_reproduced_and_tolerance(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("value=3.2\n")
    c = _claim()
    amber_run.measure_claim(c, tmp_path)
    assert c["verdict"] == "NOT_REPRODUCED"
    c = _claim(tolerance=0.5)
    amber_run.measure_claim(c, tmp_path)
    assert c["verdict"] == "REPRODUCED"


def test_measure_string_and_operators(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("value=falsified\n")
    c = _claim(threshold="== falsified")
    amber_run.measure_claim(c, tmp_path)
    assert c["verdict"] == "REPRODUCED"
    (tmp_path / "out.txt").write_text("value=0.59\n")
    c = _claim(threshold="<= 0.6")
    amber_run.measure_claim(c, tmp_path)
    assert c["verdict"] == "REPRODUCED"


def test_measure_not_comparable_cases(tmp_path: Path) -> None:
    c = _claim()
    amber_run.measure_claim(c, tmp_path)
    assert c["verdict"] == "NOT_COMPARABLE" and "not produced" in c["reason"]
    (tmp_path / "out.txt").write_text("nothing here\n")
    c = _claim()
    amber_run.measure_claim(c, tmp_path)
    assert "did not match" in c["reason"]
    (tmp_path / "out.txt").write_text("value=0.71\n")
    c = _claim(
        measure={
            "file": "out.txt",
            "regex": r"value=(\S+)",
            "scale": 100,
            "comparable": False,
            "reason": "other quantity",
        }
    )
    amber_run.measure_claim(c, tmp_path)
    assert (c["measured"], c["verdict"], c["reason"]) == ("71.0", "NOT_COMPARABLE", "other quantity")


def test_overall_verdict() -> None:
    v = amber_run.overall_verdict
    assert v([{"verdict": "REPRODUCED"}, {"verdict": "NOT_COMPARABLE"}]) == "REPRODUCED"
    assert v([{"verdict": "REPRODUCED"}, {"verdict": "NOT_REPRODUCED"}]) == "NOT_REPRODUCED"
    assert v([{"verdict": "NOT_COMPARABLE"}]) == "NOT_COMPARABLE"
    assert v([]) == "NOT_COMPARABLE"


def test_rerun_compares_claims_not_just_files(monkeypatch, tmp_path):
    from darnit_amber import rerun as rr

    first = {
        "id": "first",
        "statement": {
            "subject": [{"name": "https://x/y.git", "digest": {"gitCommit": "abc"}}],
            "predicate": {
                "corpus_entry": "e",
                "experiment": {"command": "true", "outputs": [{"path": "t.txt", "sha256": "aaa"}]},
                "claims": [
                    {
                        "id": "c",
                        "threshold": ">= 0",
                        "measure": {"file": "t.txt", "regex": "(\\d+)", "comparable": False},
                        "measured": "1",
                        "verdict": "NOT_COMPARABLE",
                        "reason": "hw",
                    }
                ],
            },
        },
    }
    seen = {}

    def fake_execute(artifact, ref, key, entry, store, rerun_of=None, **kw):
        seen["entry"] = entry
        experiment = {"command": "true", "exit_code": 0, "outputs": [{"path": "t.txt", "sha256": "bbb"}]}
        claims = [{"id": "c", "measured": "2", "verdict": "NOT_COMPARABLE"}]
        return {
            "id": "second",
            "statement": {
                "subject": first["statement"]["subject"],
                "predicate": {
                    "experiment": experiment,
                    "claims": claims,
                    "verdict": "NOT_COMPARABLE",
                    "reruns": amber_run.compare_rerun(rerun_of, experiment, claims),
                },
            },
        }

    class Store:
        def read(self, _id):
            return json.dumps(first).encode()

        def write(self, *_):
            pass

    monkeypatch.setattr(rr, "execute", fake_execute)
    out = rr.rerun(Store(), "first", tmp_path / "k")
    assert seen["entry"]["claims"][0]["measure"]["file"] == "t.txt"
    assert "measured" not in seen["entry"]["claims"][0]
    assert out["outputs"][0]["result"] == "changed"
    assert out["claims"][0] == {
        "id": "c",
        "first": {"measured": "1", "verdict": "NOT_COMPARABLE"},
        "rerun": {"measured": "2", "verdict": "NOT_COMPARABLE"},
        "result": "same",
    }
    assert out["drift"] is False
    assert out["id"] == "second"


def test_infer_outputs_drops_darnit_and_git_files():
    from darnit_amber.run import _infer_outputs

    prods = {"amber-audit.json": {}, ".git/index": {}, "out/b.txt": {}, "out/a.txt": {}}
    assert _infer_outputs(prods) == ["out/a.txt", "out/b.txt"]


def test_run_command_after_dashdash_builds_inferred_entry(monkeypatch, tmp_path):
    from darnit_amber import run as r

    seen = {}
    monkeypatch.setattr(r, "execute", lambda artifact, ref, key, entry, store, **kw: seen.update(entry) or {})
    r.run(".", None, tmp_path / "k", None, None, ["sh", "-c", "echo hi > a.txt"])
    assert seen["run"] == {"command": "sh -c 'echo hi > a.txt'"}
    assert seen["_source"] == "inferred"


def test_claim_measures_stored_output_into_derived_bundle(tmp_path):
    from darnit_amber.claim import claim
    from darnit_amber.run import _canonical, write_blob

    class Store:  # local-fs shaped: <root>/<id>.intoto.json and <root>/<id>/outputs/<path>
        _root = tmp_path

        def write(self, bid, data, _ct):
            (tmp_path / f"{bid}.intoto.json").write_bytes(data)

    first = {
        "id": "b1",
        "statement": {
            "subject": [{"name": "x", "digest": {}}],
            "predicate": {
                "experiment": {
                    "command": "c",
                    "outputs": [{"path": "out/r.txt", "sha256": "s", "captured": True, "stored": True}],
                },
                "claims": [],
                "verdict": "NOT_COMPARABLE",
            },
        },
    }
    st = Store()
    st.write("b1", _canonical(first), "")
    write_blob(st, "b1", "out/r.txt", b"Queries/sec: 126.81\n")
    res = claim(
        st,
        "b1",
        {"id": "q", "threshold": ">= 100", "measure": {"file": "out/r.txt", "regex": r"Queries/sec: ([0-9.]+)"}},
    )
    assert res["derived_from"] == "b1" and res["verdict"] == "REPRODUCED"
    assert res["claim"]["measured"] == "126.81"
    assert (tmp_path / res["id"] / "outputs" / "out" / "r.txt").read_bytes().startswith(b"Queries")
    with pytest.raises(Exception, match="not an output"):
        claim(st, "b1", {"id": "q", "measure": {"file": "nope.txt", "regex": "x"}})


def test_default_key_is_generated_once_with_tight_permissions(tmp_path, monkeypatch):
    import os

    from darnit_amber.run import default_key, key_fingerprint

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    k = default_key()
    assert k == tmp_path / "darnit" / "amber" / "signing.key"
    assert k.is_file() and k.with_suffix(".pub").is_file()
    assert oct(os.stat(k).st_mode & 0o777) == "0o600"
    fp = key_fingerprint(k)
    assert fp.startswith("sha256:") and len(fp) == 71
    assert default_key() == k and key_fingerprint(k) == fp  # reused, not regenerated


def test_witness_adds_timestamp_flag_by_default(monkeypatch, tmp_path):
    from darnit_amber import run as r

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        raise FileNotFoundError  # stop before decoding

    monkeypatch.setattr(r.shutil, "which", lambda _: "/bin/witness")
    monkeypatch.setattr(r.subprocess, "run", fake_run)
    with pytest.raises(FileNotFoundError):
        r._witness("s", tmp_path / "k", tmp_path / "o", tmp_path, ["true"])
    assert seen["cmd"][seen["cmd"].index("-t") + 1] == r.TSA_URL
    with pytest.raises(FileNotFoundError):
        r._witness("s", tmp_path / "k", tmp_path / "o", tmp_path, ["true"], tsa=None)
    assert "-t" not in seen["cmd"]


def test_wrap_token_builds_a_granted_timestamp_response():
    from darnit_amber.rerun import _der_len, _wrap_token

    assert _der_len(5) == b"\x05" and _der_len(300) == b"\x82\x01\x2c"
    token = b"\x30\x02\x05\x00"
    out = _wrap_token(token)
    assert out == b"\x30\x09\x30\x03\x02\x01\x00" + token


def test_timestamps_reports_parse_errors_without_failing():
    from darnit_amber.rerun import _timestamps

    env = {
        "signatures": [
            {
                "sig": base64.b64encode(b"x").decode(),
                "timestamps": [{"type": "tsp", "data": base64.b64encode(b"junk").decode()}],
            }
        ]
    }
    [t] = _timestamps(env)
    assert t["type"] == "tsp" and "error" in t and "time" not in t


def test_tsa_chain_rejects_a_token_no_trusted_authority_signed(monkeypatch):
    """A self-made token parses but does not chain to Sigstore's timestamp authorities."""
    from darnit_amber import rerun as rr

    class Authority:
        validity_period_start = None
        validity_period_end = None

        def certificates(self, allow_expired=True):
            return []  # incomplete chain: skipped

    class Root:
        def get_timestamp_authorities(self):
            return [Authority()]

    monkeypatch.setattr(rr, "_TRUST_ROOT", Root())
    assert rr._tsa_chain(object(), b"sig") == "no trusted timestamp authority signed this token"


def test_trusted_root_falls_back_to_the_bundled_copy_offline(monkeypatch):
    from darnit_amber import rerun as rr

    monkeypatch.setattr(rr, "_TRUST_ROOT", None)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # no network: TUF refresh fails
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    root = rr._trusted_root()
    assert root.get_timestamp_authorities(), "sigstore's bundled trusted root has a timestamp authority"


# --- --identity (Fulcio): the verification path, with a chain made here instead of a login ---


def _make_chain(email="marc@example.edu", issuer="https://github.com/login/oauth"):
    """A root CA and a ten-minute leaf shaped like Fulcio's, valid around NOW."""
    from datetime import timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.now(UTC).replace(microsecond=0)
    root_key = ec.generate_private_key(ec.SECP256R1())
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test root")])
    root = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = _fulcio_shaped_leaf(leaf_key.public_key(), root, root_key, email, issuer, now)
    _ROOT_KEYS[root.public_bytes(serialization_pem())] = root_key
    return root, leaf, leaf_key, now


def _fulcio_shaped_leaf(public_key, issuer_cert, issuer_key, email, issuer, now, *, eku=True):
    """A ten-minute leaf like Fulcio's: empty subject, SAN email, issuer OID, code-signing EKU, SKI/AKI."""
    from datetime import timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import ExtendedKeyUsageOID, ObjectIdentifier

    der_utf8 = bytes([0x0C, len(issuer)]) + issuer.encode()
    b = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([]))
        .issuer_name(issuer_cert.subject)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=9))
        .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.RFC822Name(email)]), critical=True)
        .add_extension(x509.UnrecognizedExtension(ObjectIdentifier("1.3.6.1.4.1.57264.1.8"), der_utf8), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_cert.public_key()), critical=False)
    )
    if eku:
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
    return b.sign(issuer_key, hashes.SHA256())


def _identity_envelope(leaf, leaf_key):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from darnit_amber.identity import pae

    payload = b'{"hello":"world"}'
    sig = leaf_key.sign(pae("application/vnd.in-toto+json", payload), ec.ECDSA(hashes.SHA256()))
    pem = leaf.public_bytes(serialization.Encoding.PEM)
    return {
        "payloadType": "application/vnd.in-toto+json",
        "payload": base64.b64encode(payload).decode(),
        "signatures": [
            {"keyid": "", "sig": base64.b64encode(sig).decode(), "certificate": base64.b64encode(pem).decode()}
        ],
    }


def test_certificate_identity_reads_san_and_fulcio_issuer():
    from darnit_amber.identity import certificate_identity

    _root, leaf, _key, _now = _make_chain()
    who = certificate_identity(leaf)
    assert who["subject"] == "marc@example.edu"
    assert who["issuer"] == "https://github.com/login/oauth"
    assert len(who["certificate_sha256"]) == 64


def test_identity_signature_verifies_inside_the_window_against_the_trusted_root():
    from datetime import timedelta

    from darnit_amber.identity import verify_identity_signature

    root, leaf, key, now = _make_chain()
    env = _identity_envelope(leaf, key)
    sig = env["signatures"][0]
    good = verify_identity_signature(env, sig, now, [root])
    assert good["signature"] == "ok" and good["chain"] == "ok" and good["ok"] is True
    assert good["subject"] == "marc@example.edu"

    late = verify_identity_signature(env, sig, now + timedelta(hours=1), [root])
    assert late["signature"] == "ok" and late["ok"] is False and "no valid path" in late["chain"]

    other_root, _l, _k, _n = _make_chain()
    stranger = verify_identity_signature(env, sig, now, [other_root])
    assert stranger["ok"] is False and "no valid path" in stranger["chain"]

    untimed = verify_identity_signature(env, sig, None, [root])
    assert untimed["ok"] is False and untimed["chain"].startswith("skipped")


def test_identity_signature_rejects_a_tampered_payload():
    from darnit_amber.identity import verify_identity_signature

    root, leaf, key, now = _make_chain()
    env = _identity_envelope(leaf, key)
    env["payload"] = base64.b64encode(b'{"hello":"mars"}').decode()
    assert verify_identity_signature(env, env["signatures"][0], now, [root])["signature"].startswith("invalid")


def test_verify_reports_identity_from_the_envelope(monkeypatch, tmp_path):
    """An identity-signed bundle verifies with no --pubkey; the trusted time comes from its timestamp."""
    from darnit_amber import rerun as rr
    from darnit_amber.identity import certificate_identity

    root, leaf, key, now = _make_chain()
    env = _identity_envelope(leaf, key)
    stmt = {
        "subject": [{"name": "x", "digest": {}}],
        "predicate": {
            "signing": {
                "method": "identity",
                "certificates_sha256": {"amber-audit": certificate_identity(leaf)["certificate_sha256"]},
            },
            "witness_envelopes_sha256": {"amber-audit": hashlib.sha256(amber_run._canonical(env)).hexdigest()},
        },
    }
    bundle_id = hashlib.sha256(amber_run._canonical(stmt)).hexdigest()
    bundle = {"id": bundle_id, "statement": stmt, "witness_envelopes": {"amber-audit": env}}
    (tmp_path / f"{bundle_id}.intoto.json").write_bytes(amber_run._canonical(bundle))

    class Root:
        def get_fulcio_certs(self):
            return [root]

    class Store:
        _root = tmp_path

    monkeypatch.setattr(rr, "_TRUST_ROOT", Root())
    monkeypatch.setattr(
        rr,
        "_timestamps",
        lambda env: [{"signature": 0, "time": now.isoformat(), "covers_signature": True, "tsa_chain": "ok"}],
    )
    out = rr.verify(Store(), bundle_id, None)
    assert out["signatures"] == {"amber-audit": "see identity"}
    assert out["identity"]["amber-audit"][0]["subject"] == "marc@example.edu"
    assert out["identity_verified"] is True
    assert out["envelopes_match_statement"] is True
    assert out["signatures_verified"] is True
    assert out["verified"] is True

    # the same bundle with the envelope replaced by one signed by a different, honest certificate: not this bundle
    other_root, other_leaf, other_key, _ = _make_chain()
    swapped = {**bundle, "witness_envelopes": {"amber-audit": _identity_envelope(other_leaf, other_key)}}
    (tmp_path / f"{bundle_id}.intoto.json").write_bytes(amber_run._canonical(swapped))
    out = rr.verify(Store(), bundle_id, None)
    assert out["envelopes_match_statement"] is False and out["verified"] is False


def test_witness_signs_with_fulcio_when_given_a_token_file(monkeypatch, tmp_path):
    from darnit_amber import run as r

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        raise FileNotFoundError

    monkeypatch.setattr(r.shutil, "which", lambda _: "/bin/witness")
    monkeypatch.setattr(r.subprocess, "run", fake_run)
    with pytest.raises(FileNotFoundError):
        r._witness("s", None, tmp_path / "o", tmp_path, ["true"], token_path=tmp_path / "tok")
    cmd = seen["cmd"]
    assert "-k" not in cmd
    assert cmd[cmd.index("--signer-fulcio-url") + 1] == "https://fulcio.sigstore.dev"
    assert cmd[cmd.index("--signer-fulcio-token-path") + 1] == str((tmp_path / "tok").resolve())
    assert "--signer-fulcio-token" not in cmd  # the token itself never goes on the command line


def test_identity_token_prefers_the_environment(monkeypatch):
    from darnit_amber.identity import TOKEN_ENV, identity_token

    monkeypatch.setenv(TOKEN_ENV, " eyJ.token ")
    assert identity_token() == "eyJ.token"


def test_identity_without_timestamp_is_refused(tmp_path, capsys):
    rc = main(["run", str(tmp_path), "--identity", "--no-timestamp", "--out", str(tmp_path / "out")])
    assert rc == 1
    assert "needs a timestamp" in capsys.readouterr().err


# Real bundles made on the darnit VM (see the fixtures' README): verifiable forever because verify
# uses the timestamp's time, and offline because the trusted root is the copy sigstore-python ships.
FIXTURE_IDENTITY = "97e67cac94a6de720146c3a6e4002c14bc37caf4aacc074447ff5424c1c7cbf5"
FIXTURE_PUBLISHED = "7b3039f7e11b5dad4adad29901861c137c81e2003125cf820b6f31566c8ca844"
FIXTURE_PUBLISHED_LOG_INDEXES = {"amber-audit": 3599179102, "experiment": 3599180143}


@pytest.fixture
def offline_root(monkeypatch):
    from darnit_amber import rerun as rr
    from sigstore.models import ClientTrustConfig

    monkeypatch.setattr(rr, "_TRUST_ROOT", ClientTrustConfig.production(offline=True).trusted_root)


class FixtureStore:
    _root = Path(__file__).parent / "fixtures"


def test_real_identity_bundle_verifies_offline(offline_root):
    """A bundle signed with a real Fulcio certificate (GitHub login) and timestamped by Sigstore's TSA."""
    from darnit_amber import rerun as rr

    out = rr.verify(FixtureStore(), FIXTURE_IDENTITY, None, online=False)
    assert out["envelopes_match_statement"] is True
    assert out["signatures"] == {"amber-audit": "see identity", "experiment": "see identity"}
    for name in ("amber-audit", "experiment"):
        (who,) = out["identity"][name]
        assert who["issuer"] == "https://github.com/login/oauth"
        assert who["signature"] == "ok" and who["chain"] == "ok"
    assert out["timestamp_authority_trusted"] is True
    assert out["identity_verified"] is True
    assert out["verified"] is True


# --- --publish (Rekor) ---


def test_dsse_envelope_for_rekor_drops_witness_extras():
    from darnit_amber.publish import _dsse_envelope, _verifiers

    env = {
        "payload": "eA==",
        "payloadType": "t",
        "signatures": [{"keyid": "k", "sig": "c2ln", "certificate": "Q0VSVA==", "timestamps": [{"x": 1}]}],
    }
    assert json.loads(_dsse_envelope(env)) == {
        "payload": "eA==",
        "payloadType": "t",
        "signatures": [{"keyid": "k", "sig": "c2ln"}],
    }
    assert _verifiers(env, None) == ["Q0VSVA=="]  # the certificate is the verifier


def test_verifiers_for_a_key_signed_envelope_is_the_public_key(tmp_path, monkeypatch):
    from darnit_amber.publish import _verifiers

    monkeypatch.setattr("darnit.stores.defaults.platform_paths.user_data_root", lambda: tmp_path)
    key = amber_run.default_key()
    (verifier,) = _verifiers({"signatures": [{"sig": "c2ln"}]}, key)
    assert base64.b64decode(verifier).startswith(b"-----BEGIN PUBLIC KEY-----")
    with pytest.raises(ValueError):
        _verifiers({"signatures": [{"sig": "c2ln"}]}, None)


def _rekor_record(env, payload_hash=None, sigs=None):
    body = {
        "apiVersion": "0.0.1",
        "kind": "dsse",
        "spec": {
            "payloadHash": {
                "algorithm": "sha256",
                "value": payload_hash or hashlib.sha256(base64.b64decode(env["payload"])).hexdigest(),
            },
            "signatures": [{"signature": s, "verifier": "x"} for s in (sigs or [s["sig"] for s in env["signatures"]])],
        },
    }
    entry = {
        "body": base64.b64encode(json.dumps(body).encode()).decode(),
        "integratedTime": 1793000000,
        "logID": "ab",
        "logIndex": 7,
        "verification": {},
    }
    return {
        "log": "https://rekor.example",
        "uuid": "u",
        "log_index": 7,
        "integrated_time": 1793000000,
        "response": {"u": entry},
    }


def test_verify_publication_matches_entry_to_envelope_before_the_proof(monkeypatch):
    from darnit_amber import publish as pub

    env = {"payload": "eA==", "payloadType": "t", "signatures": [{"keyid": "k", "sig": "c2ln"}]}

    class Entry:
        @classmethod
        def _from_v1_response(cls, response):
            return cls()

        def _verify(self, keyring):
            return None

    class Root:
        def rekor_keyring(self, purpose):
            return object()

    monkeypatch.setattr("sigstore.models.TransparencyLogEntry", Entry)
    good = pub.verify_publication(env, _rekor_record(env), Root(), online=False)
    assert good["entry_matches_envelope"] is True and good["inclusion"] == "ok" and good["ok"] is True
    assert good["integrated_time"].startswith("2026-10-")
    assert good["online"] is None

    other = pub.verify_publication(env, _rekor_record(env, payload_hash="00" * 32), Root(), online=False)
    assert other["entry_matches_envelope"] is False and other["ok"] is False and other["inclusion"] is None

    forged = pub.verify_publication(env, _rekor_record(env, sigs=["b3RoZXI="]), Root(), online=False)
    assert forged["ok"] is False


def test_verify_publication_reports_a_bad_proof(monkeypatch):
    from darnit_amber import publish as pub

    env = {"payload": "eA==", "payloadType": "t", "signatures": [{"keyid": "k", "sig": "c2ln"}]}

    class Entry:
        @classmethod
        def _from_v1_response(cls, response):
            return cls()

        def _verify(self, keyring):
            raise ValueError("inclusion proof contains invalid root hash")

    class Root:
        def rekor_keyring(self, purpose):
            return object()

    monkeypatch.setattr("sigstore.models.TransparencyLogEntry", Entry)
    out = pub.verify_publication(env, _rekor_record(env), Root(), online=False)
    assert out["inclusion"].startswith("invalid: ValueError") and out["ok"] is False


def test_run_publishes_every_envelope_and_records_it(monkeypatch, tmp_path):
    """With --publish, each Witness envelope is sent once and the record lands in the predicate."""
    from darnit_amber import run as r

    env = {
        "payload": base64.b64encode(json.dumps({"predicate": {"attestations": []}}).encode()).decode(),
        "payloadType": "t",
        "signatures": [{"sig": "c2ln"}],
    }
    sent = []
    monkeypatch.setattr(r, "_witness", lambda *a, **k: (env, {"command-run": {"exitcode": 0}, "product": {}}))
    monkeypatch.setattr(r.Path, "exists", lambda self: True)
    monkeypatch.setattr(r, "_clone", lambda *a: tmp_path)
    (tmp_path / r.AUDIT_OUTPUT).write_text('{"results": []}')
    monkeypatch.setattr("darnit.stores.defaults.platform_paths.user_data_root", lambda: tmp_path)
    monkeypatch.setattr(
        "darnit_amber.publish.publish_envelope",
        lambda e, key, url: (
            sent.append(url) or {"log": url, "uuid": "u", "log_index": len(sent), "integrated_time": 1, "response": {}}
        ),
    )

    class Store:
        def write(self, *a):
            pass

    bundle = r.execute(
        str(tmp_path), None, None, {"run": {"command": "true"}}, Store(), publish="https://rekor.example"
    )
    assert sent == ["https://rekor.example", "https://rekor.example"]
    pub = bundle["statement"]["predicate"]["publication"]
    assert set(pub) == {"amber-audit", "experiment"}
    assert pub["experiment"]["log_index"] == 2


def test_real_published_bundle_verifies_offline(offline_root):
    """A key-signed bundle published to Rekor: signature with the fixture's public key, timestamp, inclusion proof."""
    from darnit_amber import rerun as rr

    out = rr.verify(FixtureStore(), FIXTURE_PUBLISHED, FixtureStore._root / "published-signing.pub", online=False)
    assert out["envelopes_match_statement"] is True
    assert out["signatures"] == {"amber-audit": "ok", "experiment": "ok"}
    assert out["signer_matches_statement"] is True
    assert out["timestamp_authority_trusted"] is True
    for name, index in FIXTURE_PUBLISHED_LOG_INDEXES.items():
        p = out["publication"][name]
        assert p["log_index"] == index
        assert p["entry_matches_envelope"] is True and p["inclusion"] == "ok" and p["online"] is None
    assert out["published"] is True
    assert out["verified"] is True


# --- cold-review findings (2026-10-30): forgery, unchecked signatures, unbound envelopes, paths ---

_ROOT_KEYS: dict = {}


def serialization_pem():
    from cryptography.hazmat.primitives import serialization

    return serialization.Encoding.PEM


def _root_key_of(root):
    return _ROOT_KEYS[root.public_bytes(serialization_pem())]


def test_identity_chain_rejects_a_leaf_issued_by_another_leaf():
    """Any Fulcio user could otherwise mint a certificate naming someone else and pass it as an intermediate."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from darnit_amber.identity import verify_identity_signature

    root, honest_leaf, honest_key, now = _make_chain(email="attacker@evil.example")
    forged_key = ec.generate_private_key(ec.SECP256R1())
    forged = _fulcio_shaped_leaf(forged_key.public_key(), honest_leaf, honest_key, "jcappos@nyu.edu", "https://x", now)
    env = _identity_envelope(forged, forged_key)
    sig = env["signatures"][0]
    sig["intermediates"] = [base64.b64encode(honest_leaf.public_bytes(serialization_pem())).decode()]
    out = verify_identity_signature(env, sig, now, [root])
    assert out["subject"] == "jcappos@nyu.edu"  # what the forged certificate claims
    assert out["signature"] == "ok"  # it is self-consistent
    assert out["ok"] is False and out["chain"] != "ok"  # but no CA issued it


def test_identity_chain_requires_the_code_signing_eku():
    from cryptography.hazmat.primitives.asymmetric import ec
    from darnit_amber.identity import verify_identity_signature

    root, _leaf, _key, now = _make_chain()
    key = ec.generate_private_key(ec.SECP256R1())
    no_eku = _fulcio_shaped_leaf(key.public_key(), root, _root_key_of(root), "a@b", "https://x", now, eku=False)
    env = _identity_envelope(no_eku, key)
    out = verify_identity_signature(env, env["signatures"][0], now, [root])
    assert out["ok"] is False and "key usage" in out["chain"]


def test_key_signed_bundle_without_pubkey_is_not_verified(tmp_path, monkeypatch):
    """Skipping the signature check must never produce verified: true."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from darnit_amber import rerun as rr
    from darnit_amber.identity import pae

    key = ec.generate_private_key(ec.SECP256R1())  # an EC key: Witness-generated keys are P-256, not ed25519
    payload = b'{"predicate":{"attestations":[]}}'
    sig = key.sign(pae("t", payload), ec.ECDSA(hashes.SHA256()))
    env = {
        "payloadType": "t",
        "payload": base64.b64encode(payload).decode(),
        "signatures": [{"sig": base64.b64encode(sig).decode()}],
    }
    pub = tmp_path / "k.pub"
    spki = serialization.PublicFormat.SubjectPublicKeyInfo
    pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, spki))
    der = key.public_key().public_bytes(serialization.Encoding.DER, spki)
    stmt = {
        "subject": [{"name": "x", "digest": {}}],
        "predicate": {
            "signing": {"method": "key", "key_fingerprint": "sha256:" + hashlib.sha256(der).hexdigest()},
            "witness_envelopes_sha256": {"amber-audit": hashlib.sha256(amber_run._canonical(env)).hexdigest()},
        },
    }
    bundle_id = hashlib.sha256(amber_run._canonical(stmt)).hexdigest()
    (tmp_path / f"{bundle_id}.intoto.json").write_bytes(
        amber_run._canonical({"id": bundle_id, "statement": stmt, "witness_envelopes": {"amber-audit": env}})
    )

    class Store:
        _root = tmp_path

    stamp = [{"signature": 0, "covers_signature": True, "tsa_chain": "ok", "time": "2026-01-01T00:00:00+00:00"}]
    monkeypatch.setattr(rr, "_timestamps", lambda env: stamp)
    without = rr.verify(Store(), bundle_id, None)
    assert without["signatures_verified"] is False and without["verified"] is False
    assert without["signatures"]["amber-audit"].startswith("not checked")

    with_key = rr.verify(Store(), bundle_id, pub)  # EC keys verify too (finding 4)
    assert with_key["signatures"]["amber-audit"] == "ok"
    assert with_key["signer_matches_statement"] is True and with_key["verified"] is True

    other = ec.generate_private_key(ec.SECP256R1())
    (tmp_path / "o.pub").write_bytes(other.public_key().public_bytes(serialization.Encoding.PEM, spki))
    wrong = rr.verify(Store(), bundle_id, tmp_path / "o.pub")
    assert wrong["signatures_verified"] is False and wrong["verified"] is False


def test_verify_fails_when_an_envelope_named_by_the_statement_is_missing(tmp_path):
    from darnit_amber import rerun as rr

    env = {"payloadType": "t", "payload": base64.b64encode(b"{}").decode(), "signatures": []}
    stmt = {
        "subject": [{"name": "x", "digest": {}}],
        "predicate": {
            "experiment": {"command": "true", "outputs": []},
            "witness_envelopes_sha256": {"amber-audit": "0" * 64, "experiment": "1" * 64},
        },
    }
    bundle_id = hashlib.sha256(amber_run._canonical(stmt)).hexdigest()
    (tmp_path / f"{bundle_id}.intoto.json").write_bytes(
        amber_run._canonical({"id": bundle_id, "statement": stmt, "witness_envelopes": {"amber-audit": env}})
    )

    class Store:
        _root = tmp_path

    out = rr.verify(Store(), bundle_id, None)
    assert out["envelopes_match_statement"] is False
    assert out["outputs_match_witness_products"] is False  # the experiment envelope is gone, not vacuously fine
    assert out["verified"] is False


def test_output_paths_stay_inside_the_checkout(tmp_path):
    from darnit_amber.run import safe_rel

    assert safe_rel("out/result.txt") == "out/result.txt"
    for bad in ("/etc/hostname", "../x", "a/../../x", "", "C:\\x"):
        with pytest.raises(amber_run.RunError):
            safe_rel(bad)

    class Store:
        _root = tmp_path

    with pytest.raises(amber_run.RunError):
        amber_run.read_blob(Store(), "id", "/etc/hostname")
    assert amber_run._infer_outputs({"ok.txt": {}, "/abs": {}, "../up": {}, ".git/x": {}}) == ["ok.txt"]


def test_s3_list_bundles_ignores_output_blobs():
    from darnit_amber.s3_store import S3AttestationStore

    pages = [
        {
            "Contents": [
                {"Key": "amber/runs/abc.intoto.json"},
                {"Key": "amber/runs/abc/outputs/result.txt"},
                {"Key": "amber/runs/notes.md"},
            ]
        }
    ]

    class Paginator:
        def paginate(self, **kw):
            return pages

    class Client:
        def get_paginator(self, _):
            return Paginator()

    store = S3AttestationStore.__new__(S3AttestationStore)
    store._client, store._bucket, store._prefix = Client(), "b", "amber/runs"
    assert store.list_bundles() == ["abc"]


def test_witness_environment_never_carries_the_oidc_token(monkeypatch, tmp_path):
    from darnit_amber import run as r
    from darnit_amber.identity import TOKEN_ENV

    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env")
        raise FileNotFoundError

    monkeypatch.setenv(TOKEN_ENV, "secret")
    monkeypatch.setattr(r.shutil, "which", lambda _: "/bin/witness")
    monkeypatch.setattr(r.subprocess, "run", fake_run)
    with pytest.raises(FileNotFoundError):
        r._witness("s", None, tmp_path / "o", tmp_path, ["true"], token_path=tmp_path / "tok")
    assert TOKEN_ENV not in seen["env"] and "PATH" in seen["env"]
