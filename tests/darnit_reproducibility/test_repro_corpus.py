"""SC-007: the reproducibility corpus, as an explicit expectation (feature 038).

The table below is written by hand rather than captured. This feature's claim is
"these specific verdicts changed", which a reviewer should be able to read and
disagree with; a captured baseline would only assert that the code agrees with
itself.

Feature 037 needed a captured baseline because its claim was the opposite --
"nothing changed" across 213 controls. It also learned that a stored golden of
control statuses is not portable: statuses depend on whether `gh` is
authenticated. The handlers measured here make no network call (#553 moved the
only one, Witness attestation verification, into its own step), so every
verdict is a pure filesystem function. The attestation step is measured below
against verified statements, with fetching and verification faked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from darnit_reproducibility import witness_attestation as wa
from darnit_reproducibility.handlers import (
    repro_bit_for_bit_handler,
    repro_build_env_declared_handler,
    repro_deps_pinned_handler,
    repro_hermetic_build_handler,
    repro_witness_attestation_handler,
)

from .conftest import repro_ctx

DIGEST = "sha256:" + "a" * 64

# (fixture name, files) -> expected verdict per control.
CORPUS: dict[str, dict[str, str]] = {
    "pinned_container": {"Dockerfile": f"FROM alpine@{DIGEST}\n"},
    "floating_container": {"Dockerfile": "FROM alpine:latest\n"},
    "flake_only": {"flake.nix": "{ outputs = {}; }\n"},
    "signals_only": {".github/workflows/ci.yml": "env:\n  SOURCE_DATE_EPOCH: 0\n"},
    "go_installer": {".github/workflows/ci.yml": "steps:\n  - run: go install example.com/t@latest\n"},
    "native_flags": {"Makefile": "build:\n\tgcc -march=native -o app main.c\n"},
    "empty": {},
}

# These are handler outcomes, not control verdicts. Feature 044 (FR-010): the
# reproducibility step types register the ceiling `{fail}`, so a "pass" below is
# evidence for the control's later steps and the control does not conclude PASS
# on it (test_no_pass_from_signals.py). "signals_only" and "floating_container"
# were "warn" until feature 044 (FR-011): a WARN concludes under `{fail}`, which
# kept the signal from the later steps.
EXPECTED: dict[str, dict[str, str]] = {
    "pinned_container": {"RE-01.02": "pass"},
    "floating_container": {"RE-01.02": "inconclusive"},
    "flake_only": {"RE-01.02": "pass"},
    "signals_only": {"RE-03.01": "inconclusive"},
    "go_installer": {"RE-02.01": "fail"},
    "native_flags": {"RE-02.01": "fail"},
    "empty": {"RE-01.02": "inconclusive", "RE-03.01": "inconclusive"},
}

HANDLERS = {
    "RE-01.01": repro_deps_pinned_handler,
    "RE-01.02": repro_build_env_declared_handler,
    "RE-02.01": repro_hermetic_build_handler,
    "RE-03.01": repro_bit_for_bit_handler,
}

#: The only controls this feature is permitted to move (FR-013).
CHANGED_BY_THIS_FEATURE = {"RE-01.02", "RE-02.01", "RE-03.01"}


def _build(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name", sorted(CORPUS))
def test_corpus_matches_expected_verdicts(tmp_path: Path, fixture_name: str) -> None:
    repo = _build(tmp_path, CORPUS[fixture_name])
    ctx = repro_ctx(repo)
    for control_id, expected in EXPECTED[fixture_name].items():
        result = HANDLERS[control_id]({}, ctx)
        assert result.status.value == expected, (
            f"{fixture_name}: {control_id} expected {expected}, got {result.status.value} -- {result.message}"
        )


@pytest.mark.unit
def test_expectations_only_cover_controls_this_feature_may_change() -> None:
    """FR-013. A verdict asserted here for RE-01.01 would mean this feature
    moved a control it promised not to touch."""
    asserted = {c for verdicts in EXPECTED.values() for c in verdicts}
    assert asserted <= CHANGED_BY_THIS_FEATURE | {"RE-01.01"}
    changed = asserted - {"RE-01.01"}
    assert changed <= CHANGED_BY_THIS_FEATURE


@pytest.mark.unit
def test_deps_pinned_is_untouched_by_this_feature(tmp_path: Path) -> None:
    """FR-013 positively: RE-01.01 keeps feature 037's verdict and message.

    Feature 044 (FR-011) changed only its status, from "warn" to
    "inconclusive": a WARN concludes under `{fail}` and kept the signal from
    the later steps.
    """
    repo = _build(tmp_path, {"requirements.txt": "numpy==1.26.4\n"})
    result = repro_deps_pinned_handler({}, repro_ctx(repo))
    assert result.status.value == "inconclusive"
    assert "transitive" in result.message


# #553: verified attestation statements -> the repro_witness_attestation outcome.
# Only recorded network access decides, and it decides FAIL. A clean or absent
# network log is what a monitor that does not trace sockets also records, so it
# is evidence and never "pass".
_RUNTIME_TRACE = "https://in-toto.io/attestation/runtime-trace/v0.1"
_COLLECTION = "https://witness.dev/attestation-collection/v0.1"
_COMMAND_RUN = "https://witness.dev/attestations/command-run/v0.1"


def _trace(monitor_log: dict) -> dict:
    return {"monitor": {"type": "https://tetragon.io/", "tracePolicy": {}}, "monitorLog": monitor_log}


def _collection(entry_type: str, attestation: dict) -> dict:
    return {
        "predicateType": _COLLECTION,
        "predicate": {"attestations": [{"type": entry_type, "attestation": attestation}]},
    }


ATTESTATION_CORPUS: dict[str, tuple[dict, str]] = {
    "trace_with_network_events": (
        {"predicateType": _RUNTIME_TRACE, "predicate": _trace({"network": [{"connect": "203.0.113.7:443"}]})},
        "fail",
    ),
    "trace_with_empty_network_log": (
        {"predicateType": _RUNTIME_TRACE, "predicate": _trace({"network": []})},
        "inconclusive",
    ),
    # The runtime-trace spec's own Tetragon example: a `connect` policy, no `network` field.
    "trace_without_network_field": (
        {"predicateType": _RUNTIME_TRACE, "predicate": _trace({"process": [{"exec": "make"}]})},
        "inconclusive",
    ),
    "collection_trace_with_network_events": (_collection(_RUNTIME_TRACE, _trace({"network": [{}, {}]})), "fail"),
    "collection_command_run_installer": (
        _collection(_COMMAND_RUN, {"processes": [{"program": "/usr/bin/curl", "cmdline": "curl -O https://x"}]}),
        "fail",
    ),
    "collection_command_run_clean": (
        _collection(_COMMAND_RUN, {"processes": [{"program": "/usr/bin/make", "cmdline": "make"}]}),
        "inconclusive",
    ),
    "other_predicate_with_network_key": (
        {"predicateType": "https://slsa.dev/provenance/v1", "predicate": {"network": [{"host": "x"}]}},
        "inconclusive",
    ),
}


@pytest.mark.unit
@pytest.mark.parametrize("case", sorted(ATTESTATION_CORPUS))
def test_attestation_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    verified, expected = ATTESTATION_CORPUS[case]
    artifact = tmp_path / "build.att.json"
    artifact.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
    monkeypatch.setattr(wa, "_head_commit", lambda local_path: ("a" * 40, None))
    monkeypatch.setattr(wa, "_successful_run_ids", lambda owner, repo, sha: (["1"], None))
    monkeypatch.setattr(wa, "_fetch_candidate_files", lambda owner, repo, run_ids, scratch: ([artifact], None))
    monkeypatch.setattr(wa, "_verify_bundle", lambda raw, owner, repo, sha: verified)

    result = repro_witness_attestation_handler({}, repro_ctx(tmp_path))

    assert result.status.value == expected, f"{case}: {result.message}"
    assert result.evidence["witness_attestation"]["verified"] is True
