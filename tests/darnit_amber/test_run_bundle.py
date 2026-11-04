"""Tests for ``darnit-amber run`` / ``verify`` / ``claim`` / ``rerun`` (issue #677). No witness binary needed."""

import base64
import hashlib
import json
import subprocess
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

    def fake(step, key, out, cwd, cmd, tsa=None, token_path=None):
        env = {
            "payload": base64.b64encode(b'{"predicate":{"attestations":[]}}').decode(),
            "payloadType": "t",
            "signatures": [{"sig": "c2ln"}],
        }
        if step == "amber-audit":
            Path(cmd[-1].rsplit("> ", 1)[1]).write_text('{"results": [{"id": "RE-01.01", "status": "FAIL"}]}')
            return env, {"command-run": {"exitcode": 0, "cmd": cmd}}
        for path, data in products.items():
            (cwd / path).parent.mkdir(parents=True, exist_ok=True)
            (cwd / path).write_bytes(data)
        Path(cmd[-1]).write_text(str(exit_code))
        prod = {p: {"digest": {"sha256": hashlib.sha256(d).hexdigest()}} for p, d in products.items()}
        return env, {"command-run": {"exitcode": 0, "cmd": cmd}, "product": prod}

    return fake


@pytest.fixture
def repo(tmp_path):
    """A clean git checkout with one committed results file: the precomputed-results case."""
    r = tmp_path / "artifact"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / "results").mkdir()
    (r / "results" / "table.txt").write_text("speedup: 2.4\n")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(["git", "-C", str(r), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(r), "commit", "-q", "-m", "init"], check=True, env={**env, "PATH": "/usr/bin:/bin"}
    )
    return r


@pytest.fixture
def no_signing(monkeypatch, tmp_path):
    from darnit_amber import run as r

    monkeypatch.setattr(r.Path, "exists", lambda self: True)  # the darnit CLI next to the interpreter
    monkeypatch.setattr(
        r,
        "sign_statement",
        lambda stmt, key, tsa, token_path=None: {
            "payloadType": "stmt",
            "payload": base64.b64encode(r._canonical(stmt)).decode(),
            "signatures": [],
        },
    )
    return _FsStore(tmp_path / "store")


def _execute(repo, store, products, entry, **kw):
    from darnit_amber import run as r

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(r, "_witness", _fake_witness(products, kw.pop("exit_code", 0)))
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
    assert bundle["statement"]["predicate"]["entry"]["artifact"] == {"clone": str(repo), "ref": None, "dirty": True}


def test_publish_failure_keeps_the_stored_bundle(repo, no_signing, monkeypatch):
    """A failed --publish lost the whole run (review): now the bundle is stored first and the error names it."""

    def boom(env, key, url):
        raise ConnectionError("rekor down")

    monkeypatch.setattr("darnit_amber.publish.publish_envelope", boom)
    with pytest.raises(amber_run.RunError, match=r"bundle (\w+) is stored; publishing to .* failed: ConnectionError"):
        _execute(repo, no_signing, {"o.txt": b"x"}, {"run": {"command": "true"}}, publish="https://rekor.example")
    (stored,) = list(no_signing._root.glob("*.intoto.json"))
    assert json.loads(stored.read_bytes())["publication"] is None


def test_run_publishes_the_statement_and_every_envelope(repo, no_signing, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "darnit_amber.publish.publish_envelope",
        lambda e, key, url: (
            sent.append(url) or {"log": url, "uuid": "u", "log_index": len(sent), "integrated_time": 1, "response": {}}
        ),
    )
    bundle = _execute(repo, no_signing, {"o.txt": b"x"}, {"run": {"command": "true"}}, publish="https://rekor.example")
    assert sent == ["https://rekor.example"] * 3
    assert set(bundle["publication"]) == {"statement", "amber-audit", "experiment"}
    assert "publication" not in bundle["statement"]["predicate"]  # outside the signed statement: stored first
    stored = json.loads((no_signing._root / f"{bundle['id']}.intoto.json").read_bytes())
    assert stored["publication"]["experiment"]["log_index"] == 3


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
    assert seen["ref"] == "abc" and seen["kw"]["clone_local"] is True  # the recorded commit, not the working tree
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
    from darnit_amber.identity import pae

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


@pytest.fixture
def stamped(monkeypatch):
    from darnit_amber import rerun as rr

    monkeypatch.setattr(rr, "_timestamps", _stamps_for)


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


def _key_bundle(tmp_path, products=None, claims=None, verdict="NOT_COMPARABLE"):
    """A key-signed bundle with an experiment, like ``run`` makes with a local key."""
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())  # Witness-generated keys are P-256
    fp = _write_pub(key, tmp_path / "k.pub")
    products = products if products is not None else {"result.txt": b"score: 7\n"}
    sign = lambda payload: _key_envelope(key, payload)  # noqa: E731
    witness = {
        "amber-audit": sign(b'{"predicate":{"attestations":[]}}'),
        "experiment": _witness_experiment_envelope(sign, "./run.sh", products),
    }
    predicate = {
        "signing": {"method": "key", "key_fingerprint": fp},
        "experiment": {
            "command": "./run.sh",
            "outputs": [
                {"path": p, "sha256": hashlib.sha256(d).hexdigest(), "captured": True, "stored": True}
                for p, d in products.items()
            ],
        },
        "claims": claims or [],
        "verdict": verdict,
    }
    from darnit_amber.run import STATEMENT_TYPE

    store, bundle = _bundle(tmp_path, predicate, lambda c: _key_envelope(key, c, STATEMENT_TYPE), witness, products)
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
    amber_run.write_blob(store, derived["id"], "result.txt", b"score: 7\n")
    # The verifier must hold the claimer's key for the statement; the Witness envelopes were signed by the researcher,
    # whose key it then does not hold, so a one-key verify cannot pass both: that is the honest answer.
    with_claimer = rr.verify(store, derived["id"], tmp_path / "claimer.pub")
    assert (
        with_claimer["signatures"]["statement"]["ok"] is True
        and with_claimer["claim_signer"]["key_fingerprint"] == claimer_fp
    )
    assert with_claimer["signatures"]["experiment"]["ok"] is False and with_claimer["verified"] is False
    with_researcher = rr.verify(store, derived["id"], pub)
    assert with_researcher["signatures"]["statement"]["ok"] is False and with_researcher["verified"] is False


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


# --- --identity (Fulcio): the verification path, with a chain made here instead of a login ---

_ROOT_KEYS: dict = {}


def serialization_pem():
    from cryptography.hazmat.primitives import serialization

    return serialization.Encoding.PEM


def _root_key_of(root):
    return _ROOT_KEYS[root.public_bytes(serialization_pem())]


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


def _identity_envelope(leaf, leaf_key, payload=b'{"hello":"world"}', payload_type="application/vnd.in-toto+json"):
    return _key_envelope(leaf_key, payload, payload_type, certificate=leaf)


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


def _identity_bundle(tmp_path, monkeypatch, email="marc@example.edu"):
    from darnit_amber import rerun as rr
    from darnit_amber.identity import certificate_identity
    from darnit_amber.run import STATEMENT_TYPE

    root, leaf, key, now = _make_chain(email=email)
    monkeypatch.setattr(rr, "_timestamps", lambda env: [{**s, "time": now.isoformat()} for s in _stamps_for(env)])

    class Root:
        def get_fulcio_certs(self):
            return [root]

    monkeypatch.setattr(rr, "_TRUST_ROOT", Root())
    env = _identity_envelope(leaf, key)
    predicate = {
        "signing": {
            "method": "identity",
            "identity": email,
            "issuer": "https://github.com/login/oauth",
            "certificates_sha256": {"amber-audit": certificate_identity(leaf)["certificate_sha256"]},
        }
    }
    store, bundle = _bundle(
        tmp_path, predicate, lambda c: _identity_envelope(leaf, key, c, STATEMENT_TYPE), {"amber-audit": env}
    )
    return store, bundle, root, leaf, key


def test_identity_bundle_needs_the_expected_identity(monkeypatch, tmp_path):
    """Anyone pinning a researcher's identity accepted a bundle from any Fulcio identity (review B8)."""
    from darnit_amber import rerun as rr

    store, bundle, root, leaf, key = _identity_bundle(tmp_path, monkeypatch)
    bid = bundle["id"]
    unpinned = rr.verify(store, bid, None)
    assert unpinned["signatures"]["statement"]["subject"] == "marc@example.edu"
    assert "no expected identity" in unpinned["signatures"]["statement"]["signature"]
    assert unpinned["verified"] is False

    good = rr.verify(
        store, bid, None, expect_identity="marc@example.edu", expect_issuer="https://github.com/login/oauth"
    )
    assert all(s["ok"] for s in good["signatures"].values())
    assert good["statement_signed"] is True and good["signatures_verified"] is True and good["verified"] is True

    stranger = rr.verify(
        store, bid, None, expect_identity="someone@else.edu", expect_issuer="https://github.com/login/oauth"
    )
    assert (
        stranger["verified"] is False
        and "not the expected identity" in stranger["signatures"]["statement"]["signature"]
    )

    # --pubkey on a certificate-signed bundle was ignored: now it must be the key in the certificate
    from cryptography.hazmat.primitives.asymmetric import ec

    _write_pub(ec.generate_private_key(ec.SECP256R1()), tmp_path / "unrelated.pub")
    with_key = rr.verify(
        store,
        bid,
        tmp_path / "unrelated.pub",
        expect_identity="marc@example.edu",
        expect_issuer="https://github.com/login/oauth",
    )
    assert (
        with_key["verified"] is False
        and "--pubkey is not the key in the certificate" in with_key["signatures"]["statement"]["signature"]
    )


def test_identity_in_the_statement_must_match_the_certificate(monkeypatch, tmp_path):
    """signing.identity was rewritten to another address next to the real certificate, and nothing compared them (review B1)."""
    from darnit_amber import rerun as rr

    store, bundle, root, leaf, key = _identity_bundle(tmp_path, monkeypatch)
    bundle["statement"]["predicate"]["signing"]["identity"] = "jcappos@nyu.edu"
    bundle["id"] = hashlib.sha256(amber_run._canonical(bundle["statement"])).hexdigest()
    store.write(bundle["id"], amber_run._canonical(bundle), "")
    out = rr.verify(
        store, bundle["id"], None, expect_identity="jcappos@nyu.edu", expect_issuer="https://github.com/login/oauth"
    )
    assert out["statement_signed"] is False  # the signed payload is the original statement
    assert "different identity" in out["signatures"]["amber-audit"]["signature"]
    assert out["verified"] is False


def test_swapped_envelope_from_another_honest_identity_is_not_this_bundle(monkeypatch, tmp_path):
    from darnit_amber import rerun as rr

    store, bundle, root, leaf, key = _identity_bundle(tmp_path, monkeypatch)
    _other_root, other_leaf, other_key, _ = _make_chain()
    swapped = {**bundle, "witness_envelopes": {"amber-audit": _identity_envelope(other_leaf, other_key)}}
    store.write(bundle["id"], amber_run._canonical(swapped), "")
    out = rr.verify(
        store, bundle["id"], None, expect_identity="marc@example.edu", expect_issuer="https://github.com/login/oauth"
    )
    assert out["envelopes_match_statement"] is False and out["verified"] is False


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
    assert TOKEN_ENV not in seen["env"]
    assert seen["env"]["PATH"].split(":")[0] == str(Path(r.sys.executable).parent)  # darnit's own bin dir leads PATH


# --- CLI ---


def test_cli_reports_errors_instead_of_tracebacks(tmp_path, capsys, monkeypatch):
    rc = main(
        ["run", str(tmp_path), "--claims", str(tmp_path / "missing.yaml"), "--out", str(tmp_path / "out"), "--", "true"]
    )
    assert rc == 1 and "missing.yaml" in capsys.readouterr().err
    rc = main(["verify", "nope", "--out", str(tmp_path / "out")])
    assert rc == 1 and "nope" in capsys.readouterr().err


def test_cli_rerun_refuses_without_a_terminal_or_yes(monkeypatch, capsys):
    from darnit_amber.cli import _consent

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert _consent(False)("rm -rf /") is False
    assert "pass --yes" in capsys.readouterr().err
    assert _consent(True)("true") is True


# --- real bundles made on the darnit VM (see the fixtures' README): verifiable forever because verify uses the
# timestamp's time, and offline because the trusted root is the copy sigstore-python ships ---

FIXTURE_IDENTITY = "fcaecc716ae5ebc4acc2ca53b5e823bc4743978633e257a823a4f0152bfb4aef"
FIXTURE_IDENTITY_SUBJECT = ("md6796@nyu.edu", "https://github.com/login/oauth")
FIXTURE_PUBLISHED = "c3e2fda5054fc34e3dc2b3f7f6596f0a14055064e9206b9a87705dfa399a35f4"
FIXTURE_PUBLISHED_LOG_INDEXES = {"statement": 3691869540, "amber-audit": 3691869544, "experiment": 3691869564}


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

    email, issuer = FIXTURE_IDENTITY_SUBJECT
    out = rr.verify(FixtureStore(), FIXTURE_IDENTITY, None, online=False, expect_identity=email, expect_issuer=issuer)
    assert out["statement_signed"] is True and out["envelopes_match_statement"] is True
    for name in ("statement", "amber-audit", "experiment"):
        who = out["signatures"][name]
        assert who["subject"] == email and who["issuer"] == issuer
        assert who["signature"] == "ok" and who["chain"] == "ok" and who["ok"] is True
    assert out["timestamps_trusted"] is True
    assert out["verified"] is True
    assert rr.verify(FixtureStore(), FIXTURE_IDENTITY, None, online=False)["verified"] is False  # identity not pinned


def test_real_published_bundle_verifies_offline(offline_root):
    """A key-signed bundle published to Rekor: signature with the fixture's public key, timestamp, inclusion proof."""
    from darnit_amber import rerun as rr

    out = rr.verify(FixtureStore(), FIXTURE_PUBLISHED, FixtureStore._root / "published-signing.pub", online=False)
    assert out["statement_signed"] is True and out["envelopes_match_statement"] is True
    assert {n: s["signature"] for n, s in out["signatures"].items()} == {
        "statement": "ok",
        "amber-audit": "ok",
        "experiment": "ok",
    }
    assert out["timestamps_trusted"] is True
    for name, index in FIXTURE_PUBLISHED_LOG_INDEXES.items():
        p = out["publication"][name]
        assert p["log_index"] == index
        assert p["entry_matches_envelope"] is True and p["inclusion"] == "ok" and p["online"] is None
    assert out["published"] is True
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

    monkeypatch.setattr("darnit_amber.run.user_data_root", lambda: tmp_path)
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


def test_s3_list_bundles_ignores_output_blobs():
    pytest.importorskip("boto3")
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
