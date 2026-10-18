"""The adversarial corpus gate (feature 041 US4, FR-017, FR-018, FR-019).

Runs the OpenSSF Baseline controls against every fixture in this directory,
offline, and fails on any false PASS by a step allowed to conclude PASS that
is not in ``known_false_pass.toml``, and on any entry there that no longer
occurs.
"""

from __future__ import annotations

import json

import pytest

from tests.darnit_baseline.corpus.runner import (
    SUPERSEDED_COMMANDS,
    CorpusReport,
    corpus_version,
    fixture_dirs,
    gate,
    load_fixture,
    load_fixtures,
    load_framework,
    load_known_false_pass,
    measure,
    run_corpus,
    run_fixture,
    with_tool_command,
)

FRAMEWORK = "openssf-baseline"
ZIZMOR_CONTROLS = ("OSPS-AC-04.02", "OSPS-BR-01.01")
# zizmor must not read anything the audited repository supplies, and must
# report a workflow-level write-all (framework-design.md 14.6).
ZIZMOR_REQUIRED_FLAGS = ("--no-config", "--no-ignores", "--collect=all", "--persona=pedantic")


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


def test_recorded_tools_cover_every_call(report: CorpusReport) -> None:
    """A recorded stand-in answers only calls it recorded; re-record after changing a command."""
    unrecorded = {
        name: meta["unrecorded_calls"] for name, meta in report.fixtures.items() if "unrecorded_calls" in meta
    }
    assert not unrecorded, (
        f"calls with no recording (run scripts/record_corpus_tools.py, see the corpus README): {unrecorded}"
    )


def test_every_recorded_tool_has_a_recording() -> None:
    for fixture in load_fixtures():
        for tool in fixture.recorded_tools():
            recording = json.loads(fixture.recording_path(tool).read_text(encoding="utf-8"))
            assert recording["tool"] == tool and recording["calls"], fixture.name


def test_zizmor_steps_ignore_repository_configuration() -> None:
    framework = load_framework(FRAMEWORK)
    by_id = {c.control_id: c for c in framework.controls}
    for control_id in ZIZMOR_CONTROLS:
        step = by_id[control_id].metadata["handler_invocations"][0]
        command = (step.model_extra or {})["command"]
        assert command[0] == "zizmor", control_id
        missing = [flag for flag in ZIZMOR_REQUIRED_FLAGS if flag not in command]
        assert not missing, f"{control_id}: zizmor runs without {missing}"


def test_zizmor_evidence_records_command_and_version() -> None:
    fixture = load_fixture(next(p for p in fixture_dirs() if p.name == "write-all-workflow"))
    run = run_fixture(fixture, load_framework(FRAMEWORK))

    evidence = run.results["OSPS-AC-04.02"]["evidence"]
    recording = json.loads(fixture.recording_path("zizmor").read_text(encoding="utf-8"))
    assert set(ZIZMOR_REQUIRED_FLAGS) <= set(evidence["command"])
    assert recording["version"].split()[-1] in evidence["stderr"].splitlines()[0]


def test_superseded_zizmor_command_fails_the_gate() -> None:
    """The corpus catches the zizmor measurement that read the repository's own configuration."""
    framework = load_framework(FRAMEWORK)
    fixtures = [f for f in load_fixtures() if "zizmor" in f.recorded_tools()]
    expected = {
        ("write-all-workflow", "OSPS-AC-04.02"),
        *(
            (name, control_id)
            for name in ("zizmor-config-suppression", "zizmor-gitignored-workflow", "zizmor-inline-ignore")
            for control_id in ZIZMOR_CONTROLS
        ),
    }
    for command in SUPERSEDED_COMMANDS["zizmor"]:
        report = measure(with_tool_command(framework, "zizmor", command), fixtures, corpus_version())

        unexpected, _stale = gate(report, load_known_false_pass())
        assert {(v.fixture, v.control_id) for v in unexpected} == expected, command
        assert not any("unrecorded_calls" in meta for meta in report.fixtures.values()), command
