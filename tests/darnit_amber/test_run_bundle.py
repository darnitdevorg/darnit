"""Tests for ``darnit-amber run`` / ``verify`` / ``claim`` / ``rerun`` (issue #677). No witness binary needed."""

import base64
import hashlib
import io
import json
import os
import subprocess
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


# --- claims: measured only from what the experiment produced, compared only when that makes sense ---


def _claim(**kw):
    base = {
        "id": "c",
        "threshold": "== 3",
        "expected_verdict": "REPRODUCED",
        "measure": {"file": "out.txt", "regex": r"value=(\S+)"},
    }
    base.update(kw)
    return amber_run._claims({"claims": [base]})[0]


def _outputs(**files: str):
    """A reader over the outputs the experiment produced: what ``measure_claim`` gets instead of the checkout."""
    data = {k: v.encode() for k, v in files.items()}
    return data.get


def test_measure_reproduced() -> None:
    c = _claim()
    amber_run.measure_claim(c, _outputs(**{"out.txt": "value=3\n"}))
    assert (c["measured"], c["verdict"]) == ("3", "REPRODUCED")


def test_measure_not_reproduced_and_tolerance() -> None:
    read = _outputs(**{"out.txt": "value=3.2\n"})
    c = _claim()
    amber_run.measure_claim(c, read)
    assert c["verdict"] == "NOT_REPRODUCED"
    c = _claim(tolerance=0.5)
    amber_run.measure_claim(c, read)
    assert c["verdict"] == "REPRODUCED"


def test_measure_string_and_operators() -> None:
    c = _claim(threshold="== falsified")
    amber_run.measure_claim(c, _outputs(**{"out.txt": "value=falsified\n"}))
    assert c["verdict"] == "REPRODUCED"
    c = _claim(threshold="<= 0.6")
    amber_run.measure_claim(c, _outputs(**{"out.txt": "value=0.59\n"}))
    assert c["verdict"] == "REPRODUCED"


def test_ordering_needs_two_numbers_and_never_raises() -> None:
    """'9 ms' against '> 10' was REPRODUCED by string comparison, and '>= 10' crashed after the run (review B3)."""
    read = _outputs(**{"out.txt": "value=9 ms\n"})
    for threshold in (">= 10", "> 10", "< 10", "<= 10"):
        c = _claim(threshold=threshold, measure={"file": "out.txt", "regex": "value=(.+)"})
        amber_run.measure_claim(c, read)
        assert c["verdict"] == "NOT_COMPARABLE" and "needs two numbers" in c["reason"], threshold
        assert c["measured"] == "9 ms"
    c = _claim(threshold="> 10", tolerance=2)
    amber_run.measure_claim(c, _outputs(**{"out.txt": "value=9\n"}))
    assert c["verdict"] == "REPRODUCED" and "tolerance" in c["reason"]  # ordering operators honour the tolerance
    c = _claim(measure={"file": "out.txt", "regex": "value=(("})  # a bad regex is a failed measurement, not a crash
    amber_run.measure_claim(c, read)
    assert c["verdict"] == "NOT_COMPARABLE" and c["reason"].startswith("measurement failed")
    c = _claim(measure={"file": "out.txt", "regex": r"value=(\S+)", "scale": 100})
    amber_run.measure_claim(c, _outputs(**{"out.txt": "value=abc\n"}))
    assert c["verdict"] == "NOT_COMPARABLE" and "not a number" in c["reason"]


def test_measure_not_comparable_cases() -> None:
    c = _claim()
    amber_run.measure_claim(c, _outputs())
    assert c["verdict"] == "NOT_COMPARABLE" and "not produced" in c["reason"]
    c = _claim()
    amber_run.measure_claim(c, _outputs(**{"out.txt": "nothing here\n"}))
    assert "did not match" in c["reason"]
    c = _claim(
        measure={
            "file": "out.txt",
            "regex": r"value=(\S+)",
            "scale": 100,
            "comparable": False,
            "reason": "other quantity",
        }
    )
    amber_run.measure_claim(c, _outputs(**{"out.txt": "value=0.71\n"}))
    assert (c["measured"], c["verdict"], c["reason"]) == ("71.0", "NOT_COMPARABLE", "other quantity")


def test_measure_file_is_confined_to_the_checkout() -> None:
    """``measure.file`` comes from an untrusted entry: /etc/hosts and ../ were read and recorded (review)."""
    seen = []

    def read(path):
        seen.append(path)
        return b"x"

    for bad in ("/etc/hosts", "../../etc/hosts", ""):
        c = _claim(measure={"file": bad, "regex": "(x)"})
        amber_run.measure_claim(c, read)
        assert c["verdict"] == "NOT_COMPARABLE" and "not a relative path" in c["reason"]
    assert seen == []


def test_overall_verdict() -> None:
    """A claim that could not be measured is not reproduced: it counts against the run (review)."""
    v = amber_run.overall_verdict
    assert v([{"verdict": "REPRODUCED"}, {"verdict": "NOT_COMPARABLE"}]) == "NOT_COMPARABLE"
    assert v([{"verdict": "REPRODUCED"}, {"verdict": "REPRODUCED"}]) == "REPRODUCED"
    assert v([{"verdict": "REPRODUCED"}, {"verdict": "NOT_REPRODUCED"}]) == "NOT_REPRODUCED"
    assert v([{"verdict": "NOT_COMPARABLE"}]) == "NOT_COMPARABLE"
    assert v([]) == "NOT_COMPARABLE"


def test_public_url_drops_credentials() -> None:
    """A token in a clone URL went verbatim into subject.name (review B5)."""
    pu = amber_run.public_url
    assert pu("https://x-access-token:ghp_abc@github.com/o/r.git") == "https://github.com/o/r.git"
    assert pu("https://user@github.com:8443/o/r.git") == "https://github.com:8443/o/r.git"
    assert pu("ssh://git:pw@github.com/o/r.git") == "ssh://git@github.com/o/r.git"
    assert pu("https://github.com/o/r.git") == "https://github.com/o/r.git"
    assert pu("git@github.com:o/r.git") == "git@github.com:o/r.git"
    assert pu("/home/me/artifact") == "/home/me/artifact"


def test_environment_is_an_allowlist_and_witness_does_not_attest_it(monkeypatch) -> None:
    """Witness's environment attestor stored a fake credential verbatim, plus hostname and user (review B5)."""
    monkeypatch.setenv("RESEARCH_SERVICE_CREDENTIAL", "hunter2")
    monkeypatch.setenv("OMP_NUM_THREADS", "4")
    env = amber_run._environment()
    assert env["variables"]["OMP_NUM_THREADS"] == "4"
    assert "RESEARCH_SERVICE_CREDENTIAL" not in env["variables"]
    assert not {"HOME", "PWD", "USER", "HOSTNAME", "PATH"} & set(env["variables"])  # PATH names the home directory
    assert "environment" not in amber_run.WITNESS_ATTESTORS.split(",")
    assert "darnit" in env  # looked up as darnit-core, the distribution's real name


def test_wrap_command_records_the_exit_status_of_a_failing_command(tmp_path) -> None:
    """Witness writes no attestation for a failing command; the wrapper records the status and exits 0 (review)."""
    exit_file = tmp_path / "exit"
    r = subprocess.run(["sh", "-c", amber_run.wrap_command("echo out; exit 3"), str(exit_file)], capture_output=True)
    assert r.returncode == 0 and r.stdout == b"out\n"
    assert exit_file.read_text() == "3"
    r = subprocess.run(["sh", "-c", amber_run.wrap_command("true"), str(exit_file)], capture_output=True)
    assert exit_file.read_text() == "0"


def test_infer_outputs_drops_git_files_and_paths_outside_the_checkout():
    from darnit_amber.run import _infer_outputs

    prods = {"amber-audit.json": {}, ".git/index": {}, "out/b.txt": {}, "out/a.txt": {}, "/abs": {}, "../up": {}}
    assert _infer_outputs(prods) == ["amber-audit.json", "out/a.txt", "out/b.txt"]


def test_run_command_after_dashdash_builds_inferred_entry(monkeypatch, tmp_path):
    from darnit_amber import run as r

    seen = {}
    monkeypatch.setattr(r, "execute", lambda artifact, ref, key, entry, store, **kw: seen.update(entry) or {})
    r.run(".", None, tmp_path / "k", None, None, ["sh", "-c", "echo hi > a.txt"])
    assert seen["run"] == {"command": "sh -c 'echo hi > a.txt'"}
    assert seen["_source"] == "inferred"


# --- execute, with Witness replaced: what the predicate records ---


class _FsStore:
    """local-fs shaped: <root>/<id>.intoto.json and <root>/<id>/outputs/<path>."""

    def __init__(self, root):
        self._root = root

    def write(self, bid, data, _ct):
        (self._root / f"{bid}.intoto.json").write_bytes(data)


def _fake_witness(products: dict[str, bytes], exit_code: int = 0):
    """Stand in for ``_witness``: the experiment step writes ``products`` into the checkout and the exit file."""

    def fake(step, key, out, cwd, cmd, tsa=None):
        env = {
            "payload": base64.b64encode(b'{"predicate":{"attestations":[]}}').decode(),
            "payloadType": "t",
            "signatures": [{"sig": "c2ln"}],
        }

        # Like Witness: files the command created inside cwd are products, with their digests; the two
        # records darnit asks for (.amber/audit.json, .amber/exit) are among them.
        def written(extra: dict[str, bytes]) -> dict[str, dict]:
            return {p: {"digest": {"sha256": hashlib.sha256(d).hexdigest()}} for p, d in extra.items()}

        if step == "amber-audit":
            report = b'{"results": [{"id": "RE-01.01", "status": "FAIL"}]}'
            (cwd / amber_run.AUDIT_RECORD).parent.mkdir(parents=True, exist_ok=True)
            (cwd / amber_run.AUDIT_RECORD).write_bytes(report)
            return env, {
                "command-run": {"exitcode": 0, "cmd": cmd},
                "product": written({amber_run.AUDIT_RECORD: report}),
            }
        for path, data in products.items():
            (cwd / path).parent.mkdir(parents=True, exist_ok=True)
            (cwd / path).write_bytes(data)
        status = str(exit_code).encode()
        (cwd / cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        (cwd / cmd[-1]).write_bytes(status)
        prod = written({**products, cmd[-1]: status})
        return env, {"command-run": {"exitcode": 0, "cmd": cmd}, "product": prod}

    return fake


def _execute(repo, store, products, entry, **kw):
    from darnit_amber import run as r

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(r, "_witness", _fake_witness(products, kw.pop("exit_code", 0)))
        mp.setattr(r, "_witness_bin", lambda: "witness")  # execute checks for the binary before it clones
        store._root.mkdir(exist_ok=True)
        return r.execute(str(repo), None, None, entry, store, tsa=None, **kw)


def test_claims_are_measured_only_from_what_the_experiment_produced(repo, no_signing):
    """A committed results/table.txt measured 2.4, REPRODUCED, when the experiment only wrote a log (review B2)."""
    entry = {
        "run": {"command": "echo skipping > logs/run.log"},
        "claims": [
            {"id": "table3", "threshold": ">= 2", "measure": {"file": "results/table.txt", "regex": r"speedup: (\S+)"}}
        ],
    }
    bundle = _execute(repo, no_signing, {"logs/run.log": b"benchmark binary not found; skipping\n"}, entry)
    pred = bundle["statement"]["predicate"]
    (c,) = pred["claims"]
    assert (
        c["measured"] is None and c["verdict"] == "NOT_COMPARABLE" and "not produced by the experiment" in c["reason"]
    )
    assert pred["verdict"] == "NOT_COMPARABLE"
    assert [o["path"] for o in pred["experiment"]["outputs"]] == ["logs/run.log"]
    assert pred["entry"]["artifact"]["dirty"] is False and bundle["statement"]["subject"][0]["digest"]["gitCommit"]
    assert bundle["publication"] is None and bundle["statement_envelope"]["payloadType"] == "stmt"


def test_failing_experiment_still_yields_a_bundle(repo, no_signing):
    bundle = _execute(repo, no_signing, {"o.txt": b"partial\n"}, {"run": {"command": "exit 3"}}, exit_code=3)
    assert bundle["statement"]["predicate"]["experiment"]["exit_code"] == 3
    assert (no_signing._root / f"{bundle['id']}.intoto.json").is_file()


def test_dirty_checkout_is_refused_unless_allowed(repo, no_signing):
    (repo / "results" / "table.txt").write_text("speedup: 9\n")
    with pytest.raises(amber_run.RunError, match="uncommitted changes"):
        _execute(repo, no_signing, {}, {"run": {"command": "true"}})
    bundle = _execute(repo, no_signing, {}, {"run": {"command": "true"}}, allow_dirty=True)
    assert bundle["statement"]["subject"][0]["digest"] == {}
    artifact = bundle["statement"]["predicate"]["entry"]["artifact"]
    assert artifact == {"clone": f"local/{repo.name}", "ref": None, "dirty": True}  # no path of the researcher's disk


# --- claim and rerun ---


def test_claim_measures_stored_output_into_a_signed_derived_bundle(tmp_path, monkeypatch):
    from darnit_amber.claim import claim
    from darnit_amber.run import _canonical, write_blob

    data = b"Queries/sec: 126.81\n"
    first = {
        "id": "b1",
        "statement": {
            "subject": [{"name": "x", "digest": {}}],
            "predicate": {
                "signing": {"method": "key", "key_fingerprint": "sha256:aa"},
                "experiment": {
                    "command": "c",
                    "outputs": [
                        {
                            "path": "out/r.txt",
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "captured": True,
                            "stored": True,
                        }
                    ],
                },
                "claims": [],
                "verdict": "NOT_COMPARABLE",
            },
        },
        "witness_envelopes": {},
    }
    st = _FsStore(tmp_path)
    st.write("b1", _canonical(first), "")
    write_blob(st, "b1", "out/r.txt", data)
    signed = []
    monkeypatch.setattr(
        "darnit_amber.claim.sign_statement", lambda stmt, key, tsa: signed.append((stmt, key)) or {"signed": True}
    )
    res = claim(
        st,
        "b1",
        {"id": "q", "threshold": ">= 100", "measure": {"file": "out/r.txt", "regex": r"Queries/sec: ([0-9.]+)"}},
        tsa=None,
    )
    assert res["derived_from"] == "b1" and res["verdict"] == "REPRODUCED"
    assert res["claim"]["measured"] == "126.81"
    assert (tmp_path / res["id"] / "outputs" / "out" / "r.txt").read_bytes() == data
    stored = json.loads((tmp_path / f"{res['id']}.intoto.json").read_bytes())
    assert stored["statement_envelope"] == {"signed": True} and stored["publication"] is None
    pred = stored["statement"]["predicate"]
    assert pred["claim_signer"]["method"] == "key" and pred["claim_signer"]["key_fingerprint"].startswith("sha256:")
    assert pred["signing"] == {"method": "key", "key_fingerprint": "sha256:aa"}  # the run's signer, untouched
    assert signed[0][0] == stored["statement"]
    with pytest.raises(amber_run.RunError, match="not an output"):
        claim(st, "b1", {"id": "q", "measure": {"file": "nope.txt", "regex": "x"}}, tsa=None)


def test_claim_refuses_a_stored_output_that_does_not_match_its_digest(tmp_path, monkeypatch):
    """Writing 'score: 99' into the store gave REPRODUCED with no JSON edit at all (review B4)."""
    from darnit_amber.claim import claim
    from darnit_amber.run import _canonical, write_blob

    first = {
        "id": "b1",
        "statement": {
            "subject": [{"name": "x", "digest": {}}],
            "predicate": {
                "experiment": {
                    "command": "c",
                    "outputs": [{"path": "result.txt", "sha256": "11" * 32, "captured": True, "stored": True}],
                },
                "claims": [],
            },
        },
    }
    st = _FsStore(tmp_path)
    st.write("b1", _canonical(first), "")
    write_blob(st, "b1", "result.txt", b"score: 99\n")
    with pytest.raises(amber_run.RunError, match="does not match the digest"):
        claim(
            st,
            "b1",
            {"id": "x", "threshold": ">= 50", "measure": {"file": "result.txt", "regex": "score: ([0-9]+)"}},
            tsa=None,
        )


def test_rerun_verifies_first_and_needs_consent(monkeypatch, tmp_path):
    """A bundle with no envelopes and an edited command still executed on the host (review B7)."""
    from darnit_amber import rerun as rr

    first = {
        "id": "first",
        "statement": {
            "subject": [{"name": "https://x/y.git", "digest": {"gitCommit": "abc"}}],
            "predicate": {"experiment": {"command": "cat ~/.ssh/id_ed25519 > o.txt", "outputs": []}, "claims": []},
        },
    }

    class Store:
        def read(self, _id):
            return json.dumps(first).encode()

    executed = []
    monkeypatch.setattr(rr, "execute", lambda *a, **k: executed.append(a) or {})
    monkeypatch.setattr(
        rr, "verify", lambda *a, **k: {"verified": False, "statement_signed": False, "id_matches_statement": True}
    )
    with pytest.raises(amber_run.RunError, match="does not verify \\(statement_signed\\); rerun executes nothing"):
        rr.rerun(Store(), "first", tmp_path / "k", consent=lambda c: True)
    monkeypatch.setattr(rr, "verify", lambda *a, **k: {"verified": True})
    with pytest.raises(amber_run.RunError, match="not confirmed"):
        rr.rerun(Store(), "first", tmp_path / "k")
    shown = []
    with pytest.raises(amber_run.RunError, match="not confirmed"):
        rr.rerun(Store(), "first", tmp_path / "k", consent=lambda c: shown.append(c) and False)
    assert shown == ["cat ~/.ssh/id_ed25519 > o.txt"]
    assert executed == []


def test_rerun_compares_claims_not_just_files_and_clones_the_recorded_commit(monkeypatch, tmp_path):
    from darnit_amber import rerun as rr

    first = {
        "id": "first",
        "statement": {
            "subject": [{"name": str(tmp_path), "digest": {"gitCommit": "abc"}}],
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
        seen.update(entry=entry, ref=ref, kw=kw)
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

    monkeypatch.setattr(rr, "execute", fake_execute)
    monkeypatch.setattr(rr, "verify", lambda *a, **k: {"verified": True})
    out = rr.rerun(Store(), "first", tmp_path / "k", consent=lambda c: True)
    assert seen["entry"]["claims"][0]["measure"]["file"] == "t.txt"
    assert "measured" not in seen["entry"]["claims"][0]
    assert seen["ref"] == "abc" and "clone_local" not in seen["kw"]  # the recorded commit; execute always clones
    assert out["outputs"][0]["result"] == "changed"
    assert out["claims"][0] == {
        "id": "c",
        "first": {"measured": "1", "verdict": "NOT_COMPARABLE"},
        "rerun": {"measured": "2", "verdict": "NOT_COMPARABLE"},
        "result": "same",
    }
    assert out["drift"] is False
    assert out["id"] == "second"


def test_default_key_is_generated_once_with_tight_permissions(tmp_path, monkeypatch):
    import os

    from darnit_amber.run import default_key, key_fingerprint

    monkeypatch.setattr("darnit_amber.run.user_data_root", lambda: tmp_path)  # not XDG: macOS ignores it
    k = default_key()
    assert k == tmp_path / "amber" / "signing.key"
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
    assert seen["cmd"][seen["cmd"].index("--attestations") + 1] == "git"
    with pytest.raises(FileNotFoundError):
        r._witness("s", tmp_path / "k", tmp_path / "o", tmp_path, ["true"], tsa=None)
    assert "-t" not in seen["cmd"]


def test_sign_statement_runs_witness_sign_over_the_canonical_statement(monkeypatch, tmp_path):
    from darnit_amber import run as r

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        src = Path(cmd[cmd.index("-f") + 1])
        Path(cmd[cmd.index("-o") + 1]).write_text(
            json.dumps(
                {
                    "payloadType": cmd[cmd.index("-t") + 1],
                    "payload": base64.b64encode(src.read_bytes()).decode(),
                    "signatures": [{"sig": "x"}],
                }
            )
        )

        class R:
            returncode = 0
            stderr = ""

        return R()

    monkeypatch.setattr(r.shutil, "which", lambda _: "/bin/witness")
    monkeypatch.setattr(r.subprocess, "run", fake_run)
    env = r.sign_statement({"b": 1, "a": 2}, tmp_path / "k", r.TSA_URL)
    assert env["payloadType"] == r.STATEMENT_TYPE
    assert base64.b64decode(env["payload"]) == b'{"a":2,"b":1}'
    cmd = seen["cmd"]
    assert cmd[1] == "sign" and cmd[cmd.index("--timestamp-servers") + 1] == r.TSA_URL and "-k" in cmd


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


# --- verify: bundles built here, signed with keys and chains made here ---

STAMP_TIME = "2026-01-01T00:00:00+00:00"


def _stamps_for(env):
    """Every signature on ``env`` covered by a trusted timestamp (``_timestamps`` is replaced by this in tests)."""
    return [
        {"signature": i, "time": STAMP_TIME, "covers_signature": True, "tsa_chain": "ok"}
        for i in range(len(env.get("signatures") or []))
    ]


def _key_envelope(key, payload: bytes, payload_type="application/vnd.in-toto+json", certificate=None):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from darnit_amber.dsse import pae

    sig = key.sign(pae(payload_type, payload), ec.ECDSA(hashes.SHA256()))
    s = {"keyid": "", "sig": base64.b64encode(sig).decode()}
    if certificate is not None:
        s["certificate"] = base64.b64encode(certificate.public_bytes(serialization.Encoding.PEM)).decode()
    return {"payloadType": payload_type, "payload": base64.b64encode(payload).decode(), "signatures": [s]}


def _write_pub(key, path):
    from cryptography.hazmat.primitives import serialization

    spki = serialization.PublicFormat.SubjectPublicKeyInfo
    path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, spki))
    der = key.public_key().public_bytes(serialization.Encoding.DER, spki)
    return "sha256:" + hashlib.sha256(der).hexdigest()


def _bundle(tmp_path, predicate, sign_statement, witness, outputs=None):
    """Assemble a bundle: the statement names the envelopes, then gets signed, then stored with its outputs."""
    from darnit_amber.run import STATEMENT_TYPE, _canonical, write_blob

    predicate = {
        **predicate,
        "witness_envelopes_sha256": {n: hashlib.sha256(_canonical(e)).hexdigest() for n, e in witness.items()},
    }
    stmt = {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": "x", "digest": {}}],
        "predicateType": "p",
        "predicate": predicate,
    }
    bundle_id = hashlib.sha256(_canonical(stmt)).hexdigest()
    bundle = {
        "id": bundle_id,
        "statement": stmt,
        "statement_envelope": sign_statement(_canonical(stmt)),
        "witness_envelopes": witness,
        "publication": None,
    }
    store = _FsStore(tmp_path)
    store.write(bundle_id, _canonical(bundle), "")
    for path, data in (outputs or {}).items():
        write_blob(store, bundle_id, path, data)
    return store, bundle


def _witness_experiment_envelope(sign, command, products: dict[str, bytes]):
    from darnit_amber.run import wrap_command

    payload = json.dumps(
        {
            "predicate": {
                "attestations": [
                    {
                        "type": "https://witness.dev/attestations/command-run/v0.1",
                        "attestation": {"cmd": ["sh", "-c", wrap_command(command), "/tmp/x"], "exitcode": 0},
                    },
                    {
                        "type": "https://witness.dev/attestations/product/v0.1",
                        "attestation": {
                            p: {"digest": {"sha256": hashlib.sha256(d).hexdigest()}} for p, d in products.items()
                        },
                    },
                ]
            }
        }
    ).encode()
    return sign(payload)


def _key_bundle(tmp_path, products=None, claims=None, verdict="NOT_COMPARABLE", exit_code=3):
    """A key-signed bundle with an experiment, like ``run`` makes with a local key.

    Like a real run, the experiment's exit status and the audit report are
    Witness products under ``.amber/`` and stored blobs, so ``verify`` can
    read them back against the digests Witness recorded.
    """
    from cryptography.hazmat.primitives.asymmetric import ec
    from darnit_amber.run import AUDIT_RECORD, EXIT_RECORD, audit_command, audit_results

    key = ec.generate_private_key(ec.SECP256R1())  # Witness-generated keys are P-256
    fp = _write_pub(key, tmp_path / "k.pub")
    products = products if products is not None else {"result.txt": b"score: 7\n"}
    exit_blob = str(exit_code).encode()
    report = b'{"results": [{"id": "RE-01.01", "status": "FAIL"}]}'
    sign = lambda payload: _key_envelope(key, payload)  # noqa: E731
    audit_payload = json.dumps(
        {
            "predicate": {
                "attestations": [
                    {
                        "type": "https://witness.dev/attestations/command-run/v0.1",
                        "attestation": {"cmd": ["sh", "-c", audit_command()], "exitcode": 0},
                    },
                    {
                        "type": "https://witness.dev/attestations/product/v0.1",
                        "attestation": {AUDIT_RECORD: {"digest": {"sha256": hashlib.sha256(report).hexdigest()}}},
                    },
                ]
            }
        }
    ).encode()
    witness = {
        "amber-audit": sign(audit_payload),
        "experiment": _witness_experiment_envelope(sign, "./run.sh", {**products, EXIT_RECORD: exit_blob}),
    }
    predicate = {
        "signing": {"method": "key", "key_fingerprint": fp},
        "audit": {
            "framework": "amber",
            "command": ["sh", "-c", audit_command()],
            "exit_code": 0,
            "report": {"path": AUDIT_RECORD, "sha256": hashlib.sha256(report).hexdigest()},
            "results": audit_results(json.loads(report)),
        },
        "experiment": {
            "command": "./run.sh",
            "exit_code": exit_code,
            "exit_status": {"path": EXIT_RECORD, "sha256": hashlib.sha256(exit_blob).hexdigest()},
            "outputs": [
                {"path": p, "sha256": hashlib.sha256(d).hexdigest(), "captured": True, "stored": True}
                for p, d in products.items()
            ],
        },
        "claims": claims or [],
        "verdict": verdict,
    }
    from darnit_amber.run import STATEMENT_TYPE

    store, bundle = _bundle(
        tmp_path,
        predicate,
        lambda c: _key_envelope(key, c, STATEMENT_TYPE),
        witness,
        {**products, EXIT_RECORD: exit_blob, AUDIT_RECORD: report},
    )
    return store, bundle, key, tmp_path / "k.pub"


def test_key_signed_bundle_verifies_only_with_its_key(tmp_path, stamped):
    """Skipping the signature check must never produce verified: true; the wrong key fails too."""
    from darnit_amber import rerun as rr

    store, bundle, key, pub = _key_bundle(tmp_path)
    bid = bundle["id"]
    without = rr.verify(store, bid, None)
    assert without["signatures_verified"] is False and without["verified"] is False
    assert without["signatures"]["statement"]["signature"].startswith("not checked")

    good = rr.verify(store, bid, pub)
    assert good["statement_signed"] is True and good["timestamps_trusted"] is True
    assert {n: s["signature"] for n, s in good["signatures"].items()} == {
        "statement": "ok",
        "amber-audit": "ok",
        "experiment": "ok",
    }
    assert good["stored_outputs_match"] is True and good["command_matches_witness"] is True
    assert good["verified"] is True

    from cryptography.hazmat.primitives.asymmetric import ec

    _write_pub(ec.generate_private_key(ec.SECP256R1()), tmp_path / "o.pub")
    wrong = rr.verify(store, bid, tmp_path / "o.pub")
    assert wrong["signatures"]["statement"]["signature"] == "--pubkey is not the key the statement names"
    assert wrong["verified"] is False


def test_edited_predicate_is_not_verified_even_with_the_id_recomputed(tmp_path, stamped):
    """Adding a REPRODUCED claim, setting the verdict and recomputing the id verified (review B1)."""
    import copy

    from darnit_amber import rerun as rr
    from darnit_amber.run import _canonical

    store, bundle, key, pub = _key_bundle(tmp_path)
    forged = copy.deepcopy(bundle)
    pred = forged["statement"]["predicate"]
    pred["claims"] = [{"id": "speedup", "measured": "2.4", "verdict": "REPRODUCED", "reason": "measured 2.4 >= 2"}]
    pred["verdict"] = "REPRODUCED"
    forged["id"] = hashlib.sha256(_canonical(forged["statement"])).hexdigest()
    store.write(forged["id"], _canonical(forged), "")
    for path in ("result.txt",):
        amber_run.write_blob(store, forged["id"], path, b"score: 7\n")
    out = rr.verify(store, forged["id"], pub)
    assert out["id_matches_statement"] is True  # the id is only a name
    assert out["statement_signed"] is False  # the researcher never signed this statement
    assert out["verified"] is False


def test_tampered_stored_output_is_not_verified(tmp_path, stamped):
    from darnit_amber import rerun as rr

    store, bundle, key, pub = _key_bundle(tmp_path)
    assert rr.verify(store, bundle["id"], pub)["verified"] is True
    (tmp_path / bundle["id"] / "outputs" / "result.txt").write_bytes(b"score: 99\n")
    out = rr.verify(store, bundle["id"], pub)
    assert out["stored_outputs_match"] is False and out["verified"] is False


def test_every_signature_needs_a_trusted_timestamp(tmp_path, monkeypatch):
    """One envelope's timestamp stripped and the id recomputed still verified: all() over what existed (review)."""
    from darnit_amber import rerun as rr

    store, bundle, key, pub = _key_bundle(tmp_path)

    def one_missing(env):
        return (
            []
            if env["payloadType"] == "application/vnd.in-toto+json"
            and b"command-run" in base64.b64decode(env["payload"])
            else _stamps_for(env)
        )

    monkeypatch.setattr(rr, "_timestamps", one_missing)
    out = rr.verify(store, bundle["id"], pub)
    assert out["timestamps_trusted"] is False and out["verified"] is False


def test_claimed_bundle_is_verified_against_the_claimer_key(tmp_path, stamped):
    """A derived bundle's statement is signed by the claimer; its Witness envelopes stay the researcher's."""
    import copy

    from cryptography.hazmat.primitives.asymmetric import ec
    from darnit_amber import rerun as rr
    from darnit_amber.run import STATEMENT_TYPE, _canonical

    store, bundle, researcher, pub = _key_bundle(tmp_path)
    claimer = ec.generate_private_key(ec.SECP256R1())
    claimer_fp = _write_pub(claimer, tmp_path / "claimer.pub")
    derived = copy.deepcopy(bundle)
    pred = derived["statement"]["predicate"]
    pred["claims"] = [{"id": "s", "measured": "7", "verdict": "REPRODUCED", "reason": "measured 7 >= 5"}]
    pred["verdict"] = "REPRODUCED"
    pred["derived_from"] = bundle["id"]
    pred["claim_signer"] = {"method": "key", "key_fingerprint": claimer_fp}
    derived["id"] = hashlib.sha256(_canonical(derived["statement"])).hexdigest()
    derived["statement_envelope"] = _key_envelope(claimer, _canonical(derived["statement"]), STATEMENT_TYPE)
    store.write(derived["id"], _canonical(derived), "")
    for path in ("result.txt", ".amber/exit", ".amber/audit.json"):  # what claim() carries over
        amber_run.write_blob(store, derived["id"], path, amber_run.read_blob(store, bundle["id"], path))
    # Two signers, two expectations (review, Nov 11): the researcher's key for the Witness envelopes, the claimer's
    # for the statement. One key alone cannot pass both, and the report says which one is missing.
    both = rr.verify(store, derived["id"], pub, claimer_pubkey=tmp_path / "claimer.pub")
    assert rr.failed_checks(both) == [], both
    assert both["verified"] is True and both["claim_signer"]["key_fingerprint"] == claimer_fp
    assert all(v["ok"] for v in both["signatures"].values())
    with_researcher = rr.verify(store, derived["id"], pub)
    assert with_researcher["verified"] is False and with_researcher["signatures"]["experiment"]["ok"] is True
    assert "--claimer-pubkey" in with_researcher["signatures"]["statement"]["signature"]
    with_claimer = rr.verify(store, derived["id"], tmp_path / "claimer.pub")
    assert (
        with_claimer["signatures"]["statement"]["ok"] is True
        and with_claimer["signatures"]["experiment"]["ok"] is False
    )
    assert with_claimer["verified"] is False
    swapped = rr.verify(store, derived["id"], tmp_path / "claimer.pub", claimer_pubkey=pub)
    assert swapped["verified"] is False


def test_claim_records_which_signer_stands_behind_each_claim(tmp_path, monkeypatch):
    from darnit_amber.claim import claim
    from darnit_amber.run import _canonical, write_blob

    data = b"score: 7\n"
    first = {
        "id": "b1",
        "statement": {
            "subject": [{"name": "x", "digest": {}}],
            "predicate": {
                "signing": {"method": "key", "key_fingerprint": "sha256:aa"},
                "experiment": {
                    "command": "c",
                    "outputs": [
                        {"path": "r.txt", "sha256": hashlib.sha256(data).hexdigest(), "captured": True, "stored": True}
                    ],
                },
                "claims": [{"id": "first", "measured": "1", "verdict": "REPRODUCED", "reason": "measured 1 == 1"}],
            },
        },
    }
    st = _FsStore(tmp_path)
    st.write("b1", _canonical(first), "")
    write_blob(st, "b1", "r.txt", data)
    monkeypatch.setattr("darnit_amber.claim.sign_statement", lambda stmt, key, tsa: {"payload": "", "signatures": []})
    monkeypatch.setattr("darnit_amber.claim.key_fingerprint", lambda key: "sha256:bb")
    out = claim(
        st,
        "b1",
        {"id": "score", "threshold": ">= 5", "measure": {"file": "r.txt", "regex": r"score: (\d+)"}},
        key=tmp_path / "k",
    )
    derived = json.loads((tmp_path / f"{out['id']}.intoto.json").read_bytes())
    claims = {c["id"]: c["signed_by"] for c in derived["statement"]["predicate"]["claims"]}
    assert claims == {"first": "signing", "score": "claim_signer"}


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
    out = rr.verify(_FsStore(tmp_path), bundle_id, None)
    assert out["envelopes_match_statement"] is False
    assert out["outputs_match_witness_products"] is False  # the experiment envelope is gone, not vacuously fine
    assert out["statement_signed"] is False
    assert out["verified"] is False


def test_output_paths_stay_inside_the_checkout(tmp_path):
    from darnit_amber.run import safe_rel

    assert safe_rel("out/result.txt") == "out/result.txt"
    for bad in ("/etc/hostname", "../x", "a/../../x", "", "C:\\x"):
        with pytest.raises(amber_run.RunError):
            safe_rel(bad)

    with pytest.raises(amber_run.RunError):
        amber_run.read_blob(_FsStore(tmp_path), "id", "/etc/hostname")


# --- CLI ---


def test_cli_reports_errors_instead_of_tracebacks(tmp_path, capsys, monkeypatch):
    rc = main(
        ["run", str(tmp_path), "--claims", str(tmp_path / "missing.yaml"), "--out", str(tmp_path / "out"), "--", "true"]
    )
    assert rc == 1 and "missing.yaml" in capsys.readouterr().err
    rc = main(["verify", "nope", "--out", str(tmp_path / "out")])
    assert rc == 1 and "nope" in capsys.readouterr().err


def test_cli_reports_a_store_failure_in_one_line(monkeypatch, capsys):
    """A store that cannot be reached raised through the CLI as a traceback (VM, Nov 13): StoreError is reported."""
    from darnit_amber import cli

    from darnit.stores.errors import StoreOperationError

    class Unreachable:
        def read(self, bundle_id):
            raise StoreOperationError("s3: read of s3://b/x.intoto.json failed: connection refused")

    monkeypatch.setattr(cli, "_make_store", lambda a: Unreachable())
    rc = cli.main(["verify", "x"])
    out, err = capsys.readouterr()
    assert (
        rc == 1
        and out == ""
        and err.strip() == "darnit-amber: s3: read of s3://b/x.intoto.json failed: connection refused"
    )


def test_cli_rerun_refuses_without_a_terminal_or_yes(monkeypatch, capsys):
    from darnit_amber.cli import _consent

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert _consent(False)("rm -rf /") is False
    assert "pass --yes" in capsys.readouterr().err
    assert _consent(True)("true") is True
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert _consent(False)("true") is True
    out, err = capsys.readouterr()
    assert out == "", "the consent prompt must not reach stdout, which carries the JSON report"
    assert "run it?" in err


def test_untracked_files_make_the_checkout_dirty(repo, no_signing):
    """An untracked results/ file read by the experiment is input the commit does not contain (review, Nov 11)."""
    (repo / "precomputed.bin").write_bytes(b"\x00")
    with pytest.raises(amber_run.RunError, match="untracked files.*precomputed.bin"):
        _execute(repo, no_signing, {}, {"run": {"command": "true"}})


def test_clean_local_checkout_runs_from_a_fresh_clone_without_ignored_files(repo, no_signing, monkeypatch):
    """Files git ignores (caches, data, precomputed results) are not in the clone the experiment runs in."""
    from darnit_amber import run as r

    (repo / ".gitignore").write_text("data/\n")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    ident = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "ignore data"],
        check=True,
        env={**ident, "PATH": "/usr/bin:/bin"},
    )
    (repo / "data").mkdir()
    (repo / "data" / "input.bin").write_bytes(b"\x00")
    assert amber_run._git_dirty(repo) == []
    seen = {}
    inner = _fake_witness({}, 0)

    def spy(step, key, out, cwd, cmd, *args, **kw):
        if step == "experiment":  # the clone is gone once execute returns, so look while it is there
            seen["cwd"] = cwd
            seen["files"] = sorted(str(p.relative_to(cwd)) for p in cwd.rglob("*") if ".git" not in p.parts)
        return inner(step, key, out, cwd, cmd, *args, **kw)

    monkeypatch.setattr(r, "_witness", spy)
    monkeypatch.setattr(r, "_witness_bin", lambda: "witness")
    no_signing._root.mkdir(exist_ok=True)
    bundle = r.execute(str(repo), None, None, {"run": {"command": "true"}}, no_signing, tsa=None)
    assert Path(seen["cwd"]).resolve() != repo.resolve()
    assert "results/table.txt" in seen["files"] and "data/input.bin" not in seen["files"]
    subject = bundle["statement"]["subject"][0]
    assert subject["name"] == f"local/{repo.name}" and subject["digest"]["gitCommit"]
    assert str(repo) not in json.dumps(bundle["statement"])


def test_environment_paths_are_relative_to_home_or_checkout(tmp_path, monkeypatch):
    """VIRTUAL_ENV, CONDA_PREFIX and PYTHONPATH carried the researcher's home path (review, Nov 11)."""
    home = tmp_path / "home" / "someone"
    checkout = tmp_path / "work" / "proj"
    (home / "miniconda3" / "envs" / "x").mkdir(parents=True)
    checkout.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("VIRTUAL_ENV", str(home / "proj" / ".venv"))
    monkeypatch.setenv("CONDA_PREFIX", str(home / "miniconda3" / "envs" / "x"))
    monkeypatch.setenv("PYTHONPATH", f"{checkout / 'src'}:/usr/lib/python3/dist-packages")
    env = amber_run._environment(checkout)
    assert env["recorded_by"] == "darnit-amber"
    assert env["variables"]["VIRTUAL_ENV"] == "$HOME/proj/.venv"
    assert env["variables"]["CONDA_PREFIX"] == "$HOME/miniconda3/envs/x"
    assert env["variables"]["PYTHONPATH"] == "$CHECKOUT/src:/usr/lib/python3/dist-packages"
    assert "someone" not in json.dumps(env)
    # Outside the home directory and the checkout, a system prefix stays and anything else keeps only its last name.
    monkeypatch.setenv("PYTHONPATH", "/scratch/someone/proj/src:/opt/conda/lib:relative/dir:/Volumes/USB/x")
    assert (
        amber_run._environment(checkout)["variables"]["PYTHONPATH"]
        == "$ELSEWHERE/src:/opt/conda/lib:relative/dir:$ELSEWHERE/x"
    )


def test_public_url_drops_query_and_fragment():
    """A token in ?access_token= passed through (review, Nov 11); a clone URL needs no query at all."""
    assert amber_run.public_url("https://host/o/r.git?access_token=abc") == "https://host/o/r.git"
    assert amber_run.public_url("https://u:p@host:8443/o/r.git?x=1#f") == "https://host:8443/o/r.git"
    assert amber_run.public_url("https://host/o/r.git") == "https://host/o/r.git"


@pytest.mark.parametrize("bad", ["inf", "-inf", "nan", "1_000", "0x10", "1e400", "", "seven", float("inf")])
def test_values_must_be_finite_plain_decimals(bad):
    assert amber_run._number(bad) is None


@pytest.mark.parametrize(
    "good,value", [("70", 70.0), ("-0.5", -0.5), ("1e3", 1000.0), (".5", 0.5), ("+7", 7.0), (3, 3.0)]
)
def test_plain_decimals_parse(good, value):
    assert amber_run._number(good) == value


def test_tolerance_must_be_finite_and_bounds_are_honest():
    """An infinite tolerance made any claim REPRODUCED and a measured inf passed >= 70 (review, Nov 11)."""
    assert amber_run.compare("1", ">= 70", "inf")[0] is None
    assert amber_run.compare("1", ">= 70", -1)[0] is None
    assert amber_run.compare("inf", ">= 70", 0)[0] is None
    assert amber_run.compare("1_000", ">= 70", 0)[0] is None
    holds, reason = amber_run.compare("11", "< 10", 2)
    assert holds is True and "holds only with tolerance 2" in reason
    holds, reason = amber_run.compare("9", "< 10", 2)
    assert holds is True and reason.endswith("(tolerance 2.0)")
    assert amber_run.compare("70", ">= 70", 0) == (True, "measured 70 >= 70")
    # Equality falls back to text only for text that is not number-like: nan == nan must not be REPRODUCED.
    for bad in ("nan", "inf", "1_000", "0x10", "1e400", "Infinity"):
        holds, reason = amber_run.compare(bad, f"== {bad}", 0)
        assert holds is None and "plain decimal" in reason, bad
    assert amber_run.compare("passed", "== passed", 0) == (True, "measured 'passed' == 'passed'")
    assert amber_run.compare("7", "== seven", 0)[0] is False


def test_predicate_says_what_witness_observed_and_what_the_tool_wrote_down(repo, no_signing):
    bundle = _execute(repo, no_signing, {"o.txt": b"x"}, {"run": {"command": "true", "outputs": ["o.txt"]}})
    pred = bundle["statement"]["predicate"]
    prov = pred["provenance"]

    def present(key):  # "experiment.exit_code" names a nested field
        obj = pred
        for part in key.split("."):
            assert part in obj, key
            obj = obj[part]

    for key in prov["observed"] + prov["self_reported"]:
        present(key)
    assert set(prov["observed"]).isdisjoint(prov["self_reported"])
    # Only what verify checks against a Witness envelope is "observed". The exit status and the audit report
    # are written under .amber/ inside the checkout so Witness hashes them; verify reads the stored copies
    # back against those digests and recomputes exit_code and audit.results from them.
    assert set(prov["observed"]) == {
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
    }
    assert set(prov["self_reported"]) == {"started_at", "environment", "signing", "entry", "claims", "verdict"}
    assert pred["environment"]["recorded_by"] == "darnit-amber"
    assert all(c["signed_by"] == "signing" for c in pred["claims"])
    assert pred["experiment"]["exit_status"]["path"] == ".amber/exit"
    assert pred["audit"]["report"]["path"] == ".amber/audit.json"
    assert ".amber/exit" in pred["experiment"]["products"]
    assert not any(o["path"].startswith(".amber/") for o in pred["experiment"]["outputs"])


def test_exit_status_and_audit_report_are_stored_and_verified_against_witness(tmp_path, stamped):
    """A forged exit_code or audit result no longer matches the record Witness hashed (was self-reported)."""
    from darnit_amber import rerun as rr

    store, bundle, _researcher, pub = _key_bundle(tmp_path)
    out = rr.verify(store, bundle["id"], pub)
    assert out["verified"] is True
    assert out["exit_status_matches_witness"] is True
    assert out["audit_report_matches_witness"] is True and out["audit_command_matches_witness"] is True
    from darnit_amber.run import exit_status, read_blob, write_blob

    pred = bundle["statement"]["predicate"]
    assert exit_status(read_blob(store, bundle["id"], ".amber/exit")) == pred["experiment"]["exit_code"] == 3
    # The stored exit record edited to say the experiment succeeded: digest no longer matches Witness.
    write_blob(store, bundle["id"], ".amber/exit", b"0")
    tampered = rr.verify(store, bundle["id"], pub)
    assert tampered["exit_status_matches_witness"] is False and tampered["verified"] is False
    # The stored audit report rewritten to PASS: same.
    write_blob(store, bundle["id"], ".amber/audit.json", b'{"results": [{"id": "RE-01.01", "status": "PASS"}]}')
    assert rr.verify(store, bundle["id"], pub)["audit_report_matches_witness"] is False


def test_records_leave_nothing_in_the_checkout(repo, no_signing):
    """.amber/ exists only while a Witness step runs; an --allow-dirty in-place run must leave the tree as it was."""
    (repo / "scratch.txt").write_text("uncommitted\n")
    _execute(repo, no_signing, {"o.txt": b"x"}, {"run": {"command": "true", "outputs": ["o.txt"]}}, allow_dirty=True)
    assert not os.path.exists(repo / ".amber")  # os.path: the no_signing fixture patches Path.exists


def test_rerun_needs_an_artifact_for_a_local_subject(monkeypatch, tmp_path, stamped):
    from darnit_amber import rerun as rr

    store, bundle, _researcher, pub = _key_bundle(tmp_path)
    bundle["statement"]["subject"][0] = {"name": "local/proj", "digest": {"gitCommit": "abc"}}
    store.write(bundle["id"], amber_run._canonical(bundle), "")
    monkeypatch.setattr(rr, "verify", lambda *a, **k: {"verified": True})
    with pytest.raises(amber_run.RunError, match="pass --artifact"):
        rr.rerun(store, bundle["id"], None, pubkey=pub, consent=lambda c: True)
    with pytest.raises(amber_run.RunError, match="is not a directory"):
        rr.rerun(store, bundle["id"], None, pubkey=pub, consent=lambda c: True, artifact=str(tmp_path / "nope"))
