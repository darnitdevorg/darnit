"""Tests for the Witness / in-toto runtime-trace attestation check (#553).

``sigstore`` is an optional extra and is not installed in every environment, so
verification is exercised with fakes installed into the module (``raising=False``
lets them stand in for names the failed import never bound). The one test that
needs the real library is skipped without it -- install the `attestation` extra
(``uv sync --extra attestation``) to run it.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from darnit_reproducibility import witness_attestation as wa

from darnit.sieve.handler_registry import HandlerContext

needs_sigstore = pytest.mark.skipif(
    not wa.SIGSTORE_VERIFY_AVAILABLE,
    reason="sigstore not installed — run `uv sync --extra attestation`",
)

SHA = "0123456789abcdef0123456789abcdef01234567"


def make_ctx(local_path: str = ".", owner: str = "org", repo: str = "repo") -> HandlerContext:
    return HandlerContext(local_path=local_path, owner=owner, repo=repo, default_branch="main")


def fake_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


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


def git_repo(path: Path) -> str:
    """A real checkout with one commit; returns its HEAD."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "x"],
        cwd=path,
        check=True,
        env=env,
    )
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True).stdout.strip()


class FakePolicy:
    def __init__(self, *args: Any) -> None:
        self.args = args

    def __repr__(self) -> str:
        return f"{type(self).__name__}{self.args}"


class FakeAllOf(FakePolicy):
    pass


class FakeOIDCIssuer(FakePolicy):
    pass


class FakeRepository(FakePolicy):
    pass


class FakeWorkflowSHA(FakePolicy):
    pass


class FakeBundle:
    @staticmethod
    def from_json(raw: bytes) -> FakeBundle:
        return FakeBundle()


@pytest.fixture
def fake_sigstore(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stand-ins for the sigstore names; ``state["result"]`` is what verify_dsse returns."""
    state: dict[str, Any] = {"policies": [], "result": ("application/vnd.in-toto+json", b"{}")}

    class FakeVerifier:
        def verify_dsse(self, bundle: Any, policy: Any) -> tuple[str, bytes]:
            state["policies"].append(policy)
            if isinstance(state["result"], Exception):
                raise state["result"]
            return state["result"]

    monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
    monkeypatch.setattr(wa, "Bundle", FakeBundle, raising=False)
    monkeypatch.setattr(wa, "Verifier", type("V", (), {"production": staticmethod(FakeVerifier)}), raising=False)
    monkeypatch.setattr(wa, "AllOf", FakeAllOf, raising=False)
    monkeypatch.setattr(wa, "OIDCIssuer", FakeOIDCIssuer, raising=False)
    monkeypatch.setattr(wa, "GitHubWorkflowRepository", FakeRepository, raising=False)
    monkeypatch.setattr(wa, "GitHubWorkflowSHA", FakeWorkflowSHA, raising=False)
    return state


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


class TestHeadCommit:
    def test_returns_head_of_the_audited_checkout(self, tmp_path: Path) -> None:
        head = git_repo(tmp_path)
        assert wa._head_commit(str(tmp_path)) == (head, None)

    def test_checkout_without_commits_has_no_commit(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        sha, reason = wa._head_commit(str(tmp_path))
        assert sha is None
        assert "no commit" in reason

    def test_missing_directory_has_no_commit(self, tmp_path: Path) -> None:
        sha, reason = wa._head_commit(str(tmp_path / "absent"))
        assert sha is None
        assert "not a directory" in reason

    def test_git_missing_sets_reason(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_not_found(*args: Any, **kwargs: Any) -> None:
            raise FileNotFoundError("git")

        monkeypatch.setattr(wa.subprocess, "run", raise_not_found)
        sha, reason = wa._head_commit(str(tmp_path))
        assert sha is None
        assert "git not found" in reason

    def test_output_that_is_not_a_commit_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa.subprocess, "run", lambda *a, **kw: fake_proc(stdout="HEAD\n"))
        sha, _ = wa._head_commit(str(tmp_path))
        assert sha is None


class TestSuccessfulRunIds:
    def test_gh_unavailable_propagates_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(None, "gh CLI not found in PATH"))
        assert wa._successful_run_ids("org", "repo", SHA) == ([], "gh CLI not found in PATH")

    def test_auth_failure_propagates_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            wa,
            "_run_gh",
            lambda args: wa._GhOutcome(None, "gh is not authenticated for this repository (run `gh auth login`)"),
        )
        run_ids, reason = wa._successful_run_ids("org", "repo", SHA)
        assert run_ids == []
        assert "not authenticated" in reason

    def test_empty_stdout_returns_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(stdout="")))
        run_ids, reason = wa._successful_run_ids("org", "repo", SHA)
        assert run_ids == []
        assert "no output" in reason

    def test_invalid_json_returns_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(stdout="not json")))
        run_ids, reason = wa._successful_run_ids("org", "repo", SHA)
        assert run_ids == []
        assert "unparseable" in reason

    def test_no_runs_names_the_commit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(stdout="[]")))
        run_ids, reason = wa._successful_run_ids("org", "repo", SHA)
        assert run_ids == []
        assert f"no successful CI run found for commit {SHA[:12]}" == reason

    def test_returns_every_run_id_as_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [{"databaseId": 1}, {"databaseId": 2}, {}]
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(stdout=json.dumps(rows))))
        assert wa._successful_run_ids("org", "repo", SHA) == (["1", "2"], None)

    def test_queries_successful_runs_of_the_audited_commit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, list[str]] = {}

        def spy(args: list[str]) -> wa._GhOutcome:
            captured["args"] = args
            return wa._GhOutcome(fake_proc(stdout=json.dumps([{"databaseId": 1}])))

        monkeypatch.setattr(wa, "_run_gh", spy)
        wa._successful_run_ids("kusari-oss", "darnit", SHA)
        args = captured["args"]
        assert args[args.index("--repo") + 1] == "kusari-oss/darnit"
        assert args[args.index("--commit") + 1] == SHA
        assert args[args.index("--status") + 1] == "success"
        assert args[args.index("--limit") + 1] == "5"
        assert "--branch" not in args


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

    def test_priority_suffixes_come_first(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "a-log.json").write_text("{}")
        (tmp_path / "z.att.json").write_text("{}")
        monkeypatch.setattr(wa, "_run_gh", lambda args: wa._GhOutcome(fake_proc(returncode=0)))

        files, _ = wa._download_candidate_artifacts("org", "repo", "123", tmp_path)
        assert [f.name for f in files] == ["z.att.json", "a-log.json"]


class TestFetchCandidateFiles:
    def test_downloads_each_run_into_its_own_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, Path]] = []

        def spy(owner: str, repo: str, run_id: str, dest: Path) -> tuple[list[Path], str | None]:
            calls.append((run_id, dest))
            return [dest / f"{run_id}.json"], None

        monkeypatch.setattr(wa, "_download_candidate_artifacts", spy)
        files, reason = wa._fetch_candidate_files("org", "repo", ["1", "2"], tmp_path)
        assert calls == [("1", tmp_path / "1"), ("2", tmp_path / "2")]
        assert [f.name for f in files] == ["1.json", "2.json"]
        assert reason is None

    def test_a_run_without_artifacts_does_not_hide_another(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def spy(owner: str, repo: str, run_id: str, dest: Path) -> tuple[list[Path], str | None]:
            if run_id == "1":
                return [], "run 1 has no artifacts matching '*witness*'"
            return [dest / "a.json"], None

        monkeypatch.setattr(wa, "_download_candidate_artifacts", spy)
        files, reason = wa._fetch_candidate_files("org", "repo", ["1", "2"], tmp_path)
        assert [f.name for f in files] == ["a.json"]
        assert reason is None

    def test_no_artifacts_in_any_run_returns_the_reasons(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            wa, "_download_candidate_artifacts", lambda o, r, run_id, d: ([], f"run {run_id} has no artifacts")
        )
        files, reason = wa._fetch_candidate_files("org", "repo", ["1", "2"], tmp_path)
        assert files == []
        assert reason == "run 1 has no artifacts; run 2 has no artifacts"


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
        assert wa._verify_bundle(b"{}", "org", "repo", SHA) is None

    @needs_sigstore
    def test_invalid_bundle_bytes_returns_none(self) -> None:
        assert wa._verify_bundle(b"not a sigstore bundle", "org", "repo", SHA) is None

    def test_policy_binds_issuer_repository_and_commit(self, fake_sigstore: dict[str, Any]) -> None:
        wa._verify_bundle(b"{}", "kusari-oss", "darnit", SHA)
        (policy,) = fake_sigstore["policies"]
        assert isinstance(policy, FakeAllOf)
        (members,) = policy.args
        assert [(type(m), m.args) for m in members] == [
            (FakeOIDCIssuer, (wa.GITHUB_ACTIONS_OIDC_ISSUER,)),
            (FakeRepository, ("kusari-oss/darnit",)),
            (FakeWorkflowSHA, (SHA,)),
        ]

    def test_verification_failure_returns_none(self, fake_sigstore: dict[str, Any]) -> None:
        fake_sigstore["result"] = RuntimeError("certificate is for another commit")
        assert wa._verify_bundle(b"{}", "org", "repo", SHA) is None

    def test_non_intoto_payload_type_returns_none(self, fake_sigstore: dict[str, Any]) -> None:
        fake_sigstore["result"] = ("application/octet-stream", b"{}")
        assert wa._verify_bundle(b"{}", "org", "repo", SHA) is None

    def test_successful_verification_returns_statement(self, fake_sigstore: dict[str, Any]) -> None:
        inner = statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([]))
        fake_sigstore["result"] = ("application/vnd.in-toto+json", json.dumps(inner).encode())
        assert wa._verify_bundle(b"{}", "org", "repo", SHA) == inner


class TestCheckWitnessAttestation:
    @pytest.fixture
    def offline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sigstore present, the audited commit known, one successful run."""
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
        monkeypatch.setattr(wa, "_head_commit", lambda local_path: (SHA, None))
        monkeypatch.setattr(wa, "_successful_run_ids", lambda owner, repo, sha: (["7"], None))

    def _candidates(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *names: str) -> list[Path]:
        files = []
        for name in names:
            f = tmp_path / name
            f.write_text(name)
            files.append(f)
        monkeypatch.setattr(wa, "_fetch_candidate_files", lambda owner, repo, run_ids, scratch: (files, None))
        return files

    def _statements(self, monkeypatch: pytest.MonkeyPatch, by_name: dict[str, dict | None]) -> None:
        monkeypatch.setattr(wa, "_verify_bundle", lambda raw, owner, repo, sha: by_name[raw.decode()])

    def test_sigstore_unavailable_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", False)
        result = wa.check_witness_attestation(make_ctx())
        assert result.attempted is False
        assert result.verified is False
        assert "sigstore not installed" in result.detail

    def test_missing_repository_identity_makes_no_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
        monkeypatch.setattr(wa.subprocess, "run", lambda *a, **kw: pytest.fail("no subprocess expected"))
        result = wa.check_witness_attestation(make_ctx(owner=""))
        assert result.verified is False
        assert "owner/name not available" in result.detail

    def test_no_commit_surfaces_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
        monkeypatch.setattr(wa, "_head_commit", lambda local_path: (None, "audited path has no commit"))
        monkeypatch.setattr(wa, "_run_gh", lambda args: pytest.fail("gh must not run without a commit"))
        result = wa.check_witness_attestation(make_ctx())
        assert result.verified is False
        assert result.detail == "audited path has no commit"

    def test_no_runs_for_the_commit_surfaces_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wa, "SIGSTORE_VERIFY_AVAILABLE", True)
        monkeypatch.setattr(wa, "_head_commit", lambda local_path: (SHA, None))
        monkeypatch.setattr(
            wa, "_successful_run_ids", lambda o, r, sha: ([], f"no successful CI run found for commit {sha[:12]}")
        )
        result = wa.check_witness_attestation(make_ctx())
        assert result.verified is False
        assert SHA[:12] in result.detail
        assert result.evidence["commit"] == SHA

    def test_no_candidates_found_surfaces_specific_reason(self, offline: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            wa,
            "_fetch_candidate_files",
            lambda o, r, run_ids, scratch: ([], "gh is not authenticated for this repository (run `gh auth login`)"),
        )
        result = wa.check_witness_attestation(make_ctx())
        assert result.attempted is True
        assert result.verified is False
        assert "not authenticated" in result.detail
        assert result.evidence["runs"] == ["7"]

    def test_candidates_found_but_none_verify(
        self, offline: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._candidates(monkeypatch, tmp_path, "attestation.json")
        self._statements(monkeypatch, {"attestation.json": None})
        result = wa.check_witness_attestation(make_ctx())
        assert result.verified is False
        assert "none verified" in result.detail
        assert result.evidence["checked_files"] == ["attestation.json"]

    def test_verification_is_bound_to_the_audited_commit(
        self, offline: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._candidates(monkeypatch, tmp_path, "a.json")
        seen: list[tuple[str, str, str]] = []

        def spy(raw: bytes, owner: str, repo: str, sha: str) -> None:
            seen.append((owner, repo, sha))

        monkeypatch.setattr(wa, "_verify_bundle", spy)
        wa.check_witness_attestation(make_ctx())
        assert seen == [("org", "repo", SHA)]

    def test_verified_clean_trace_is_not_a_claim_of_no_access(
        self, offline: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._candidates(monkeypatch, tmp_path, "a.json")
        self._statements(monkeypatch, {"a.json": statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([]))})
        result = wa.check_witness_attestation(make_ctx())
        assert result.verified is True
        assert result.network_recorded is False
        assert result.evidence["artifact"] == "a.json"
        assert result.evidence["monitor_types"] == ["https://tetragon.io/"]
        assert result.evidence["commit"] == SHA

    def test_a_later_file_recording_network_access_is_not_hidden(
        self, offline: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._candidates(monkeypatch, tmp_path, "clean.json", "dirty.json")
        self._statements(
            monkeypatch,
            {
                "clean.json": statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([])),
                "dirty.json": statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([{"connect": "x"}])),
            },
        )
        result = wa.check_witness_attestation(make_ctx())
        assert result.network_recorded is True
        assert result.evidence["artifact"] == "dirty.json"
        assert result.evidence["verified_artifacts"] == ["clean.json", "dirty.json"]

    def test_verified_attestation_without_a_trace_has_no_network_signal(
        self, offline: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._candidates(monkeypatch, tmp_path, "a.json")
        self._statements(monkeypatch, {"a.json": statement("https://slsa.dev/provenance/v1", {"network": [1]})})
        result = wa.check_witness_attestation(make_ctx())
        assert result.verified is True
        assert result.network_recorded is None


class TestCommitBindingEndToEnd:
    """From the checkout's HEAD to the run query and the signing policy, with only gh and sigstore faked."""

    def test_head_reaches_the_run_query_and_the_policy(
        self, tmp_path: Path, fake_sigstore: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "checkout"
        repo.mkdir()
        head = git_repo(repo)
        fake_sigstore["result"] = (
            "application/vnd.in-toto+json",
            json.dumps(statement(wa._RUNTIME_TRACE_TYPE, runtime_trace([{"connect": "x"}]))).encode(),
        )
        gh_calls: list[list[str]] = []

        def fake_gh(args: list[str]) -> wa._GhOutcome:
            gh_calls.append(args)
            if args[:2] == ["run", "list"]:
                return wa._GhOutcome(fake_proc(stdout=json.dumps([{"databaseId": 42}])))
            dest = Path(args[args.index("--dir") + 1])
            (dest / "witness").mkdir(parents=True, exist_ok=True)
            (dest / "witness" / "build.att.json").write_text("{}")
            return wa._GhOutcome(fake_proc())

        monkeypatch.setattr(wa, "_run_gh", fake_gh)
        result = wa.check_witness_attestation(make_ctx(local_path=str(repo)))

        list_args, download_args = gh_calls
        assert list_args[list_args.index("--commit") + 1] == head
        assert download_args[:3] == ["run", "download", "42"]
        (policy,) = fake_sigstore["policies"]
        assert any(isinstance(m, FakeWorkflowSHA) and m.args == (head,) for m in policy.args[0])
        assert result.network_recorded is True
        assert result.evidence["commit"] == head
        assert result.evidence["artifact"] == "build.att.json"
