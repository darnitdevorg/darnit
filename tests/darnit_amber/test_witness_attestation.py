"""Tests for the network-access check over the Witness attestations of recorded runs (#553).

Which runs are read, and how they are verified, is `rerun.verify_commit_runs` (test_amber_runs.py runs it
end to end); here `verified_attestations` is replaced, and what is read from a verified attestation is tested.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from darnit_amber import witness_attestation as wa

from darnit.sieve.handler_registry import HandlerContext


def runtime_trace(
    network: Any = None, *, monitor_type: str = "https://tetragon.io/", with_network: bool = True
) -> dict:
    monitor_log: dict[str, Any] = {"process": [{"exec": "make"}]}
    if with_network:
        monitor_log["network"] = network
    return {
        "monitor": {"type": monitor_type, "tracePolicy": {}},
        "monitoredProcess": {"hostID": "runner"},
        "monitorLog": monitor_log,
    }


def statement(predicate_type: str, predicate: dict) -> dict:
    return {"_type": "https://in-toto.io/Statement/v1", "predicateType": predicate_type, "predicate": predicate}


def collection(*entries: tuple[str, dict]) -> dict:
    return statement(
        wa._WITNESS_COLLECTION_TYPE,
        {"name": "build", "attestations": [{"type": t, "attestation": a} for t, a in entries]},
    )


COMMAND_RUN = "https://witness.dev/attestations/command-run/v0.1"


class TestCheckWitnessAttestation:
    @pytest.fixture
    def runs(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
        """The verified attestations check_witness_attestation reads: set by each test."""
        statements: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            wa, "verified_attestations", lambda checkout: (statements, "" if statements else "no run", {"commit": "c"})
        )
        return statements

    def test_no_commit_surfaces_reason(self, tmp_path: Path) -> None:
        result = wa.check_witness_attestation(HandlerContext(local_path=str(tmp_path)))
        assert not result.verified and "no commit" in result.detail

    def test_no_verified_run_is_no_evidence(self, runs: list) -> None:
        result = wa.check_witness_attestation(HandlerContext(local_path="."))
        assert result.attempted and not result.verified and result.detail == "no run"

    def test_verified_clean_trace_is_not_a_claim_of_no_access(self, runs: list) -> None:
        runs.append(("a" * 64, statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([]))))
        result = wa.check_witness_attestation(HandlerContext(local_path="."))
        assert result.verified and result.network_recorded is False

    def test_a_later_run_recording_network_access_is_not_hidden(self, runs: list) -> None:
        runs.append(("a" * 64, statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([]))))
        runs.append(
            ("b" * 64, collection((COMMAND_RUN, {"processes": [{"program": "/usr/bin/curl", "cmdline": "curl -O x"}]})))
        )
        result = wa.check_witness_attestation(HandlerContext(local_path="."))
        assert result.network_recorded is True and result.evidence["artifact"] == "b" * 12


class TestNestedAttestations:
    def test_witness_collection_unwraps_attestations_array(self) -> None:
        stmt = collection(("command-run", {"processes": []}))
        assert wa._nested_attestations(stmt) == [{"type": "command-run", "attestation": {"processes": []}}]

    def test_non_collection_type_wraps_predicate_directly(self) -> None:
        stmt = statement(wa._RUNTIME_TRACE_TYPE, {"monitorLog": {}})
        assert wa._nested_attestations(stmt) == [{"type": wa._RUNTIME_TRACE_TYPE, "attestation": {"monitorLog": {}}}]

    def test_malformed_predicate_yields_nothing(self) -> None:
        assert wa._nested_attestations({"predicateType": wa._WITNESS_COLLECTION_TYPE, "predicate": []}) == []
        assert wa._nested_attestations(statement(wa._WITNESS_COLLECTION_TYPE, {"attestations": "x"})) == []


class TestCheckNetworkEvidence:
    def test_nonempty_network_log_records_network_access(self) -> None:
        stmt = statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([{"connect": "203.0.113.7:443"}]))
        recorded, detail, monitors = wa._check_network_evidence(stmt)
        assert recorded is True
        assert "1 network event" in detail
        assert monitors == ["https://tetragon.io/"]

    def test_empty_network_log_is_not_a_claim_of_no_access(self) -> None:
        recorded, detail, _ = wa._check_network_evidence(statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([])))
        assert recorded is False
        assert "no network events" in detail

    def test_absent_network_log_equals_empty(self) -> None:
        # The runtime-trace spec's own Tetragon example has no `network` field.
        stmt = statement(wa._RUNTIME_TRACE_TYPE, runtime_trace(with_network=False))
        assert wa._check_network_evidence(stmt)[0] is False

    def test_null_network_log_equals_empty(self) -> None:
        stmt = statement(wa._RUNTIME_TRACE_TYPE, runtime_trace(None))
        assert wa._check_network_evidence(stmt)[0] is False

    def test_network_key_on_another_predicate_type_is_ignored(self) -> None:
        stmt = statement("https://example.com/build-log/v1", {"network": [{"host": "evil.example.com"}]})
        assert wa._check_network_evidence(stmt)[0] is None

    def test_top_level_network_key_on_runtime_trace_is_not_read(self) -> None:
        predicate = runtime_trace(with_network=False)
        predicate["network"] = [{"host": "evil.example.com"}]
        assert wa._check_network_evidence(statement(wa._RUNTIME_TRACE_TYPE, predicate))[0] is False

    def test_predicate_type_must_match_exactly(self) -> None:
        stmt = statement("https://example.com/attestation/runtime-trace/v0.1", runtime_trace([{"x": 1}]))
        assert wa._check_network_evidence(stmt)[0] is None

    def test_network_log_that_is_not_a_list_decides_nothing(self) -> None:
        stmt = statement(wa._RUNTIME_TRACE_TYPE, runtime_trace({"events": 3}))
        assert wa._check_network_evidence(stmt)[0] is None

    def test_nested_runtime_trace_entry_is_read(self) -> None:
        stmt = collection((wa._RUNTIME_TRACE_TYPE, runtime_trace([{"x": 1}, {"y": 2}])))
        recorded, detail, _ = wa._check_network_evidence(stmt)
        assert recorded is True
        assert "2 network event" in detail

    def test_nested_entry_type_must_match_exactly(self) -> None:
        stmt = collection(("https://witness.dev/attestations/runtime-trace/v0.1", runtime_trace([{"x": 1}])))
        assert wa._check_network_evidence(stmt)[0] is None

    def test_command_run_with_suspicious_cmdline_records_network_access(self) -> None:
        stmt = collection((COMMAND_RUN, {"processes": [{"program": "/usr/bin/curl", "cmdline": "curl https://x"}]}))
        recorded, detail, _ = wa._check_network_evidence(stmt)
        assert recorded is True
        assert "curl" in detail

    def test_command_run_with_clean_processes_shows_nothing(self) -> None:
        stmt = collection((COMMAND_RUN, {"processes": [{"program": "/usr/bin/make", "cmdline": "make build"}]}))
        recorded, detail, _ = wa._check_network_evidence(stmt)
        assert recorded is None
        assert "no runtime-trace network log" in detail

    def test_recorded_access_wins_over_an_earlier_clean_entry(self) -> None:
        stmt = collection(
            (wa._RUNTIME_TRACE_TYPE, runtime_trace([])),
            (COMMAND_RUN, {"processes": [{"program": "/usr/bin/wget", "cmdline": "wget https://x"}]}),
        )
        assert wa._check_network_evidence(stmt)[0] is True
