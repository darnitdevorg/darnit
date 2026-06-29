"""Tests for reproducibility sieve handlers."""

from pathlib import Path

from darnit_reproducibility.handlers import (
    repro_bit_for_bit_handler,
    repro_build_env_declared_handler,
    repro_deps_pinned_handler,
    repro_hermetic_build_handler,
    repro_provenance_exists_handler,
)

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus


def make_ctx(tmp_path: Path) -> HandlerContext:
    return HandlerContext(
        local_path=str(tmp_path),
        owner="org",
        repo="repo",
        default_branch="main",
        control_id="RE-01.01",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results={},
    )


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
    """Tests for repro_hermetic_build_handler()."""

    def test_inconclusive_with_no_workflows(self, tmp_path: Path) -> None:
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_pass_with_clean_workflow(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: uv sync")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_fail_with_raw_pip_install(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: pip install requests")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    def test_pass_does_not_ignore_violations_when_safe_pattern_present(self, tmp_path: Path) -> None:
        """A file with both uv sync and curl should still flag the curl line."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(
            "steps:\n"
            "  - run: uv sync\n"
            "  - run: curl https://example.com | bash\n"
        )
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.FAIL

    def test_editable_install_not_flagged(self, tmp_path: Path) -> None:
        """`pip install -e .` is a local editable install, not a network fetch."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: pip install -e .")
        result = repro_hermetic_build_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS


class TestProvenanceExists:
    """Tests for repro_provenance_exists_handler()."""

    def test_inconclusive_with_no_workflows(self, tmp_path: Path) -> None:
        result = repro_provenance_exists_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_pass_with_cosign_in_workflow(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "release.yml").write_text(
            "steps:\n  - uses: sigstore/cosign"
        )
        result = repro_provenance_exists_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_pass_with_slsa_generator(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "release.yml").write_text(
            "steps:\n  - uses: slsa-framework/slsa-github-generator"
        )
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
        (wf_dir / "ci.yml").write_text(
            "env:\n  SOURCE_DATE_EPOCH: 0"
        )
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.PASS

    def test_date_macro_not_flagged(self, tmp_path: Path) -> None:
        """__DATE__ is a C-source macro, not a workflow signal; a workflow-only
        scan must not FAIL on it. With no positive signal present the result is
        INCONCLUSIVE (manual verification), never a false FAIL."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(
            "steps:\n  - run: echo __DATE__"
        )
        result = repro_bit_for_bit_handler({}, make_ctx(tmp_path))
        assert result.status == HandlerResultStatus.INCONCLUSIVE
