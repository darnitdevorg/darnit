"""The false-PASS corpus gate for the reproducibility framework (feature 044, FR-013, SC-006).

Runs the reproducibility controls against every fixture under ``corpus/`` with
the Baseline corpus runner (``tests/darnit_baseline/corpus/README.md``) and fails
on any false PASS by a step allowed to conclude PASS. ``text-signals-only`` is the
#453 reproduction: its handlers still report the signals they see, and no
control concludes PASS on them (FR-010).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.darnit_baseline.corpus.runner import CorpusReport, fixture_dirs, gate, load_framework, run_corpus

CORPUS_ROOT = Path(__file__).resolve().parent / "corpus"


@pytest.fixture(scope="module")
def report() -> CorpusReport:
    return run_corpus(load_framework("reproducibility"), CORPUS_ROOT)


def test_no_false_pass(report: CorpusReport) -> None:
    unexpected, _stale = gate(report, [])
    assert not unexpected, "false PASS on the corpus:\n" + "\n".join(v.describe() for v in unexpected)
    assert not [c for c in report.controls if c.verdict == "false_pass"]


def test_labels_name_framework_controls(report: CorpusReport) -> None:
    assert not report.unknown_labels, f"labels for controls the framework does not define: {report.unknown_labels}"


def test_every_fixture_is_measured(report: CorpusReport) -> None:
    measured = {c.fixture for c in report.controls}
    missing = sorted(p.name for p in fixture_dirs(CORPUS_ROOT) if p.name not in measured)
    assert not missing, f"fixtures with no measured control: {missing}"


def test_text_signal_is_evidence_not_a_verdict(report: CorpusReport) -> None:
    rows = [r for r in report.rows if r.control_id == "RE-02.02" and r.handler == "repro_provenance_exists"]
    assert [(r.outcome, r.may_conclude_pass, r.concluded) for r in rows] == [("PASS", False, 0)]
