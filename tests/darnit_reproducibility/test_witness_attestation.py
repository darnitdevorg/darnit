"""Tests for the Witness/runtime-trace attestation verification helper.

Sigstore-dependent tests (``_verify_bundle`` success/failure paths) are
skipped when ``sigstore`` isn't installed — install the `attestation` extra
(``uv sync --extra attestation``) to run them.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from darnit.sieve.handler_registry import HandlerContext
from darnit_reproducibility import witness_attestation as wa

needs_sigstore = pytest.mark.skipif(
    not wa.SIGSTORE_VERIFY_AVAILABLE,
    reason="sigstore not installed — run `uv sync --extra attestation`",
)


def make_ctx(owner: str = "org", repo: str = "repo", branch: str = "main") -> HandlerContext:
    return HandlerContext(local_path=".", owner=owner, repo=repo, default_branch=branch)


def fake_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestRunGh:
    def test_returns_outcome_with_proc_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa.subprocess, "run", lambda *a, **kw: fake_proc(stdout="ok"))
        outcome = wa._run_gh(["run", "list"])
        assert outcome.proc is not None
        assert outcome.proc.stdout == "ok"
        assert outcome.reason is None

    def test_missing_binary_sets_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_not_found(*args: Any, **kwargs: Any) -> None:
            raise FileNotFoundError("gh not found")

        monkeypatch.setattr(wa.subprocess, "run", raise_not_found)
        outcome = wa._run_gh(["run", "list"])
        assert outcome.proc is None
        assert "not found in PATH" in outcome.reason

    def test_timeout_sets_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_timeout(*args: Any, **kwargs: Any) -> None:
            raise subprocess.TimeoutExpired(cmd="gh", timeout=60)

        monkeypatch.setattr(wa.subprocess, "run", raise_timeout)
        outcome = wa._run_gh(["run", "list"])
        assert outcome.proc is None
        assert "timed out" in outcome.reason

    def test_auth_failure_stderr_is_recognized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            wa.subprocess,
            "run",
            lambda *a, **kw: fake_proc(returncode=1, stderr="To use GitHub CLI, please run `gh auth login`."),
        )
        outcome = wa._run_gh(["run", "list"])
        assert outcome.proc is None
        assert "not authenticated" in outcome.reason

    def test_other_failure_includes_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            wa.subprocess, "run", lambda *a, **kw: fake_proc(returncode=1, stderr="repository not found")
        )
        outcome = wa._run_gh(["run", "list"])
        assert outcome.proc is None
        assert "gh exited 1" in outcome.reason
        assert "repository not found" in outcome.reason


class TestLatestSuccessfulRunId:
    def test_gh_unavailable_propagates_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(None, "gh CLI not found in PATH"))
        run_id, reason = wa._latest_successful_run_id("org", "repo", "main")
        assert run_id is None
        assert reason == "gh CLI not found in PATH"

    def test_auth_failure_propagates_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            wa,
            "_run_gh",
            lambda args: wa._GhOutcome(None, "gh is not authenticated for this repository (run `gh auth login`)"),
        )
        run_id, reason = wa._latest_successful_run_id("org", "repo", "main")
        assert run_id is None
        assert "not authenticated" in reason

    def test_empty_stdout_returns_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(stdout="")))
        run_id, reason = wa._latest_successful_run_id("org", "repo", "main")
        assert run_id is None
        assert "no output" in reason

    def test_invalid_json_returns_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(stdout="not json")))
        run_id, reason = wa._latest_successful_run_id("org", "repo", "main")
        assert run_id is None
        assert "unparseable" in reason

    def test_empty_list_returns_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(stdout="[]")))
        run_id, reason = wa._latest_successful_run_id("org", "repo", "main")
        assert run_id is None
        assert "no successful CI run" in reason

    def test_valid_run_returns_id_as_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(stdout=json.dumps([{"databaseId": 123456}])))
        )
        run_id, reason = wa._latest_successful_run_id("org", "repo", "main")
        assert run_id == "123456"
        assert reason is None

    def test_requests_the_right_repo_and_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, list[str]] = {}

        def spy(args: list[str]) -> wa._GhOutcome:
            captured["args"] = args
            return wa._GhOutcome(fake_proc(stdout=json.dumps([{"databaseId": 1}])))

        monkeypatch.setattr(wa, "_run_gh", spy)
        wa._latest_successful_run_id("kusari-oss", "darnit", "main")
        assert "kusari-oss/darnit" in captured["args"]
        assert "main" in captured["args"]
        assert "success" in captured["args"]


class TestDownloadCandidateArtifacts:
    def test_gh_failure_propagates_reason(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(None, "gh CLI not found in PATH"))
        files, reason = wa._download_candidate_artifacts("org", "repo", "123", tmp_path)
        assert files == []
        assert reason == "gh CLI not found in PATH"

    def test_finds_downloaded_json_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # `gh run download` would have written these as a side effect; the
        # mock only needs to report success and leave them in place.
        nested = tmp_path / "witness-attestation"
        nested.mkdir()
        (nested / "attestation.json").write_text("{}")
        (nested / "readme.txt").write_text("not json")
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(returncode=0)))

        files, reason = wa._download_candidate_artifacts("org", "repo", "123", tmp_path)
        assert [f.name for f in files] == ["attestation.json"]
        assert reason is None

    def test_no_matching_artifacts_returns_reason(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # gh succeeded but nothing matched the *witness* pattern.
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(returncode=0)))
        files, reason = wa._download_candidate_artifacts("org", "repo", "123", tmp_path)
        assert files == []
        assert "no artifacts matching" in reason

    def test_caps_at_max_artifact_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for i in range(wa._MAX_ARTIFACT_FILES + 3):
            (tmp_path / f"attestation-{i}.json").write_text("{}")
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(returncode=0)))

        files, _ = wa._download_candidate_artifacts("org", "repo", "123", tmp_path)
        assert len(files) == wa._MAX_ARTIFACT_FILES


class TestFetchCandidateFiles:
    def test_missing_owner_returns_reason(self, tmp_path: Path) -> None:
        ctx = make_ctx(owner="")
        files, reason = wa._fetch_candidate_files(ctx, tmp_path)
        assert files == []
        assert "owner/name not available" in reason

    def test_missing_repo_returns_reason(self, tmp_path: Path) -> None:
        ctx = make_ctx(repo="")
        files, reason = wa._fetch_candidate_files(ctx, tmp_path)
        assert files == []
        assert "owner/name not available" in reason

    def test_no_run_found_propagates_reason(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_latest_successful_run_id", lambda owner, repo, branch: (None, "no successful CI run found on branch 'main'"))
        files, reason = wa._fetch_candidate_files(make_ctx(), tmp_path)
        assert files == []
        assert "no successful CI run" in reason

    def test_delegates_to_download_with_run_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_latest_successful_run_id", lambda owner, repo, branch: ("999", None))
        captured: dict[str, Any] = {}

        def spy(owner: str, repo: str, run_id: str, dest: Path) -> tuple[list[Path], str | None]:
            captured.update(owner=owner, repo=repo, run_id=run_id)
            return [dest / "attestation.json"], None

        monkeypatch.setattr(wa, "_download_candidate_artifacts", spy)
        files, reason = wa._fetch_candidate_files(make_ctx(owner="org", repo="repo"), tmp_path)
        assert captured == {"owner": "org", "repo": "repo", "run_id": "999"}
        assert files == [tmp_path / "attestation.json"]
        assert reason is None


class TestNestedAttestations:
    def test_witness_collection_unwraps_attestations_array(self) -> None:
        statement = {
            "predicateType": wa._WITNESS_COLLECTION_TYPE,
            "predicate": {"attestations": [{"type": "command-run", "attestation": {"processes": []}}]},
        }
        result = wa._nested_attestations(statement)
        assert result == [{"type": "command-run", "attestation": {"processes": []}}]

    def test_non_collection_type_wraps_predicate_directly(self) -> None:
        statement = {
            "predicateType": wa._RUNTIME_TRACE_TYPE,
            "predicate": {"network": []},
        }
        result = wa._nested_attestations(statement)
        assert result == [{"type": wa._RUNTIME_TRACE_TYPE, "attestation": {"network": []}}]


class TestCheckNetworkCleanliness:
    def test_empty_runtime_trace_network_array_is_clean(self) -> None:
        statement = {"predicateType": wa._RUNTIME_TRACE_TYPE, "predicate": {"network": []}}
        clean, detail = wa._check_network_cleanliness(statement)
        assert clean is True
        assert "empty network log" in detail

    def test_nonempty_runtime_trace_network_array_is_dirty(self) -> None:
        statement = {
            "predicateType": wa._RUNTIME_TRACE_TYPE,
            "predicate": {"network": [{"host": "evil.example.com"}]},
        }
        clean, detail = wa._check_network_cleanliness(statement)
        assert clean is False
        assert "1 network event" in detail

    def test_network_under_monitor_log_is_recognized(self) -> None:
        statement = {
            "predicateType": wa._RUNTIME_TRACE_TYPE,
            "predicate": {"monitorLog": {"network": []}},
        }
        clean, _ = wa._check_network_cleanliness(statement)
        assert clean is True

    def test_command_run_with_suspicious_cmdline_is_dirty(self) -> None:
        statement = {
            "predicateType": wa._WITNESS_COLLECTION_TYPE,
            "predicate": {
                "attestations": [
                    {
                        "type": "https://witness.dev/attestations/command-run/v0.1",
                        "attestation": {"processes": [{"program": "/usr/bin/curl", "cmdline": "curl https://x"}]},
                    }
                ]
            },
        }
        clean, detail = wa._check_network_cleanliness(statement)
        assert clean is False
        assert "curl" in detail

    def test_command_run_with_clean_processes_has_no_authoritative_signal(self) -> None:
        statement = {
            "predicateType": wa._WITNESS_COLLECTION_TYPE,
            "predicate": {
                "attestations": [
                    {
                        "type": "https://witness.dev/attestations/command-run/v0.1",
                        "attestation": {"processes": [{"program": "/usr/bin/make", "cmdline": "make build"}]},
                    }
                ]
            },
        }
        clean, detail = wa._check_network_cleanliness(statement)
        assert clean is None
        assert "no authoritative" in detail

    def test_no_recognized_attestations_has_no_authoritative_signal(self) -> None:
        statement = {"predicateType": "https://example.com/something-else/v1", "predicate": {}}
        clean, _ = wa._check_network_cleanliness(statement)
        assert clean is None

    def test_witness_takes_runtime_trace_over_command_run_when_both_present(self) -> None:
        # A collection could in principle carry both a command-run entry and a
        # runtime-trace entry; the authoritative network signal must win even
        # if it's not first in the list.
        statement = {
            "predicateType": wa._WITNESS_COLLECTION_TYPE,
            "predicate": {
                "attestations": [
                    {
                        "type": "https://witness.dev/attestations/command-run/v0.1",
                        "attestation": {"processes": [{"program": "/usr/bin/make", "cmdline": "make build"}]},
                    },
                    {"type": wa._RUNTIME_TRACE_TYPE, "attestation": {"network": []}},
                ]
            },
        }
        clean, _ = wa._check_network_cleanliness(statement)
        assert clean is True


class TestDecodeRawDsse:
    def test_valid_envelope_decodes_payload(self) -> None:
        inner = {"predicateType": "x", "predicate": {}}
        payload_b64 = base64.b64encode(json.dumps(inner).encode()).decode()
        envelope = json.dumps({"payload": payload_b64, "payloadType": "application/vnd.in-toto+json"}).encode()
        assert wa._decode_raw_dsse(envelope) == inner

    def test_missing_payload_returns_none(self) -> None:
        assert wa._decode_raw_dsse(json.dumps({}).encode()) is None

    def test_invalid_json_returns_none(self) -> None:
        assert wa._decode_raw_dsse(b"not json") is None

    def test_invalid_base64_returns_none(self) -> None:
        envelope = json.dumps({"payload": "not-valid-base64!!!"}).encode()
        assert wa._decode_raw_dsse(envelope) is None


class TestVerifyBundle:
    def test_sigstore_unavailable_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", False)
        assert wa._verify_bundle(b"{}", "org", "repo") is None

    @needs_sigstore
    def test_invalid_bundle_bytes_returns_none(self) -> None:
        assert wa._verify_bundle(b"not a sigstore bundle", "org", "repo") is None

    @needs_sigstore
    def test_verification_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeBundle:
            @staticmethod
            def from_json(raw: bytes) -> FakeBundle:
                return FakeBundle()

        class FakeVerifier:
            def verify_dsse(self, bundle: Any, policy: Any) -> tuple[str, bytes]:
                raise RuntimeError("boom")

        monkeypatch.setattr(wa, "Bundle", FakeBundle)
        monkeypatch.setattr(wa, "Verifier", type("V", (), {"production": staticmethod(lambda: FakeVerifier())}))
        assert wa._verify_bundle(b"{}", "org", "repo") is None

    @needs_sigstore
    def test_non_intoto_payload_type_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeBundle:
            @staticmethod
            def from_json(raw: bytes) -> FakeBundle:
                return FakeBundle()

        class FakeVerifier:
            def verify_dsse(self, bundle: Any, policy: Any) -> tuple[str, bytes]:
                return "application/octet-stream", b"{}"

        monkeypatch.setattr(wa, "Bundle", FakeBundle)
        monkeypatch.setattr(wa, "Verifier", type("V", (), {"production": staticmethod(lambda: FakeVerifier())}))
        assert wa._verify_bundle(b"{}", "org", "repo") is None

    @needs_sigstore
    def test_successful_verification_returns_statement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        inner_statement = {"predicateType": wa._RUNTIME_TRACE_TYPE, "predicate": {"network": []}}

        class FakeBundle:
            @staticmethod
            def from_json(raw: bytes) -> FakeBundle:
                return FakeBundle()

        class FakeVerifier:
            def verify_dsse(self, bundle: Any, policy: Any) -> tuple[str, bytes]:
                return "application/vnd.in-toto+json", json.dumps(inner_statement).encode()

        monkeypatch.setattr(wa, "Bundle", FakeBundle)
        monkeypatch.setattr(wa, "Verifier", type("V", (), {"production": staticmethod(lambda: FakeVerifier())}))
        result = wa._verify_bundle(b"{}", "org", "repo")
        assert result == inner_statement


class TestCheckWitnessAttestation:
    def test_sigstore_unavailable_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", False)
        result = wa.check_witness_attestation(make_ctx())
        assert result.attempted is False
        assert result.verified is False

    def test_no_candidates_found_surfaces_specific_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
        monkeypatch.setattr(
            wa,
            "_fetch_candidate_files",
            lambda ctx, scratch_dir: ([], "gh is not authenticated for this repository (run `gh auth login`)"),
        )
        result = wa.check_witness_attestation(make_ctx())
        assert result.attempted is True
        assert result.verified is False
        assert "not authenticated" in result.detail

    def test_no_candidates_found_falls_back_to_generic_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
        monkeypatch.setattr(wa, "_fetch_candidate_files", lambda ctx, scratch_dir: ([], None))
        result = wa.check_witness_attestation(make_ctx())
        assert result.attempted is True
        assert result.verified is False
        assert "no Witness attestation artifacts" in result.detail

    def test_candidates_found_but_none_verify(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        f = tmp_path / "attestation.json"
        f.write_text("{}")
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
        monkeypatch.setattr(wa, "_fetch_candidate_files", lambda ctx, scratch_dir: ([f], None))
        monkeypatch.setattr(wa, "_verify_bundle", lambda raw, owner, repo: None)
        result = wa.check_witness_attestation(make_ctx())
        assert result.attempted is True
        assert result.verified is False
        assert result.evidence["checked_files"] == ["attestation.json"]

    def test_verified_clean_attestation_short_circuits_remaining_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = tmp_path / "a.json"
        first.write_text("{}")
        second = tmp_path / "b.json"
        second.write_text("{}")
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
        monkeypatch.setattr(wa, "_fetch_candidate_files", lambda ctx, scratch_dir: ([first, second], None))

        statement = {"predicateType": wa._RUNTIME_TRACE_TYPE, "predicate": {"network": []}}

        def fake_verify(raw: bytes, owner: str, repo: str) -> dict[str, Any]:
            return statement

        monkeypatch.setattr(wa, "_verify_bundle", fake_verify)
        result = wa.check_witness_attestation(make_ctx())
        assert result.verified is True
        assert result.network_clean is True
        assert result.evidence["artifact"] == "a.json"
        # only the first candidate's bytes should have been read/verified
        assert result.evidence["checked_files"] == ["a.json"]
