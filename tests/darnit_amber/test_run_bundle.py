"""Tests for ``darnit-amber run`` (issue #677, PR A). No witness binary needed."""

import json
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

    def fake_execute(artifact, ref, key, entry, store, rerun_of=None):
        seen["entry"] = entry
        return {
            "statement": {
                "subject": first["statement"]["subject"],
                "predicate": {
                    "experiment": {"command": "true", "exit_code": 0, "outputs": [{"path": "t.txt", "sha256": "bbb"}]},
                    "claims": [{"id": "c", "measured": "2", "verdict": "NOT_COMPARABLE"}],
                    "verdict": "NOT_COMPARABLE",
                },
            }
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
