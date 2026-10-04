"""The adversarial corpus gate (feature 041 US4, FR-017, FR-018, FR-019).

Runs the OpenSSF Baseline controls against every fixture in this directory,
offline, and fails on any false PASS by a step allowed to conclude PASS that
is not in ``known_false_pass.toml``, and on any entry there that no longer
occurs.
"""

from __future__ import annotations

import pytest

from tests.darnit_baseline.corpus.runner import (
    CorpusReport,
    fixture_dirs,
    gate,
    load_framework,
    load_known_false_pass,
    run_corpus,
)

FRAMEWORK = "openssf-baseline"


@pytest.fixture(scope="module")
def report() -> CorpusReport:
    return run_corpus(load_framework(FRAMEWORK))


def test_no_unexpected_false_pass(report: CorpusReport) -> None:
    unexpected, _stale = gate(report, load_known_false_pass())
    assert not unexpected, "false PASS on the corpus:\n" + "\n".join(v.describe() for v in unexpected)


def test_known_false_pass_list_only_shrinks(report: CorpusReport) -> None:
    _unexpected, stale = gate(report, load_known_false_pass())
    assert not stale, "remove entries that no longer occur from known_false_pass.toml:\n" + "\n".join(
        f"{k.framework} {k.control_id} step {k.step_index} ({k.handler}) on '{k.fixture}'" for k in stale
    )


def test_labels_name_framework_controls(report: CorpusReport) -> None:
    assert not report.unknown_labels, f"labels for controls the framework does not define: {report.unknown_labels}"


def test_every_fixture_is_measured(report: CorpusReport) -> None:
    measured = {c.fixture for c in report.controls}
    missing = sorted(p.name for p in fixture_dirs() if p.name not in measured)
    assert not missing, f"fixtures with no measured control: {missing}"


def test_report_counts_every_step_and_outcome(report: CorpusReport) -> None:
    assert report.rows, "no step was measured"
    for row in report.rows:
        conclusions = row.correct + row.incorrect
        if row.outcome in ("PASS", "FAIL", "WARN"):
            assert conclusions == row.observed, row
        else:
            assert conclusions == 0, row
        assert row.false_pass <= row.incorrect


def test_plugin_redefining_a_step_type_is_refused(report: CorpusReport) -> None:
    """Feature 044 FR-013: the corpus case for a plugin redefining ``manual`` (SC-002)."""
    assert report.fixtures["plugin-redefines-manual"]["refused_registrations"] == ["manual"]
