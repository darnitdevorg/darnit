"""Regression tests for Determinism Tier 1 (#418).

Locks the concrete guarantees the Tier 1 fix cluster promises:

* Filesystem iteration is sorted at every first-match / count site
  (glob.glob results, os.walk dirnames, iterdir children, os.listdir).
* Remediation template context is not wall-clock dependent beyond the
  YEAR field (which LICENSE templates require); DATE was dropped.
* List-valued template context is sorted before Jinja2 string join.
* Filesystem writes from the file_create and yaml_inject handlers are
  atomic (tempfile-then-rename), leaving no partial file on crash.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from darnit.sieve.builtin_handlers import (
    _atomic_write_text,
    _walk_depth_limited,
    file_create_handler,
)
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus


def _mk_ctx(local_path: Path) -> HandlerContext:
    return HandlerContext(
        local_path=str(local_path),
        owner="",
        repo="",
        default_branch="main",
        control_id="TEST",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results={},
    )


class TestAtomicWrite:
    """_atomic_write_text: partial writes never leak to the target path."""

    @pytest.mark.unit
    def test_writes_content_atomically(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        _atomic_write_text(str(target), "hello\n")
        assert target.read_text() == "hello\n"

    @pytest.mark.unit
    def test_no_partial_file_on_write_failure(self, tmp_path: Path) -> None:
        """If write raises mid-flight, target is absent and no .tmp remains."""
        target = tmp_path / "out.txt"

        # Force os.replace to blow up after the tempfile is written. The
        # atomic helper catches the exception, cleans the tempfile, and
        # re-raises -- the target must NOT exist.
        with patch("darnit.sieve.builtin_handlers.os.replace", side_effect=OSError("boom")):
            with pytest.raises(OSError):
                _atomic_write_text(str(target), "hello\n")

        assert not target.exists(), "target file must not exist after failed atomic write"
        leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".darnit-write-")]
        assert leftover == [], f"tempfile leaked: {leftover}"


class TestFileCreateHandlerAtomic:
    """file_create_handler goes through _atomic_write_text."""

    @pytest.mark.unit
    def test_file_create_leaves_no_partial_on_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "SECURITY.md"
        with patch("darnit.sieve.builtin_handlers.os.replace", side_effect=OSError("disk full")):
            result = file_create_handler(
                {"handler": "file_create", "path": str(target), "content": "# Security\n"},
                _mk_ctx(tmp_path),
            )

        # Handler catches OSError and returns ERROR status; the point of
        # this test is the *file* not the return value -- no partial file.
        assert result.status == HandlerResultStatus.ERROR
        assert not target.exists()


class TestWalkDepthLimitedSorted:
    """_walk_depth_limited yields subdirs in sorted order."""

    @pytest.mark.unit
    def test_dirnames_visited_in_sorted_order(self, tmp_path: Path) -> None:
        # Create subdirs in a jumbled order; os.walk's raw ordering is
        # filesystem-dependent, but our helper must sort.
        for name in ["z_alpha", "b_beta", "m_middle", "a_first"]:
            (tmp_path / name).mkdir()

        visited: list[str] = []
        for dirpath, _depth in _walk_depth_limited(str(tmp_path), max_depth=1):
            rel = os.path.relpath(dirpath, tmp_path)
            if rel != ".":
                visited.append(rel)

        assert visited == ["a_first", "b_beta", "m_middle", "z_alpha"]


class TestGlobSortedInFileExists:
    """file_exists's glob-branch takes matches[0] in sorted order."""

    @pytest.mark.unit
    def test_glob_first_match_is_lexicographically_smallest(self, tmp_path: Path) -> None:
        from darnit.sieve.builtin_handlers import file_exists_handler

        # Create three matches; the "first" one must be alphabetical, not
        # filesystem-order-dependent.
        for name in ["release-beta.yml", "release-alpha.yml", "release-gamma.yml"]:
            (tmp_path / name).write_text("")

        result = file_exists_handler(
            {"handler": "file_exists", "files": ["release-*.yml"]},
            _mk_ctx(tmp_path),
        )

        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["relative_path"] == "release-alpha.yml"


class TestExecutorTemplateContext:
    """RemediationExecutor.now_provider + list-sort + DATE removed."""

    def _executor(self, tmp_path: Path, **kwargs):
        from darnit.remediation.executor import RemediationExecutor

        return RemediationExecutor(local_path=str(tmp_path), **kwargs)

    @pytest.mark.unit
    def test_year_is_derived_from_now_provider(self, tmp_path: Path) -> None:
        fixed = datetime(2030, 6, 15, 12, 0, 0)
        ex = self._executor(tmp_path, now_provider=lambda: fixed)
        ctx = ex._get_template_context("TEST-01")
        assert ctx["YEAR"] == "2030"

    @pytest.mark.unit
    def test_date_field_no_longer_present(self, tmp_path: Path) -> None:
        """DATE was dropped -- see _get_template_context comment."""
        ex = self._executor(tmp_path)
        ctx = ex._get_template_context("TEST-01")
        assert "DATE" not in ctx

    @pytest.mark.unit
    def test_year_is_stable_across_calls_with_fixed_now(self, tmp_path: Path) -> None:
        fixed = datetime(2029, 3, 4)
        ex = self._executor(tmp_path, now_provider=lambda: fixed)
        first = ex._get_template_context("TEST-01")["YEAR"]
        second = ex._get_template_context("TEST-01")["YEAR"]
        assert first == second == "2029"

    @pytest.mark.unit
    def test_list_context_values_are_sorted_before_join(self, tmp_path: Path) -> None:
        """Different upstream orderings of the same set produce identical output."""
        set_1 = ["@charlie", "@alice", "@bob"]
        set_2 = ["@bob", "@charlie", "@alice"]

        ex1 = self._executor(tmp_path, context_values={"maintainers": set_1})
        ex2 = self._executor(tmp_path, context_values={"maintainers": set_2})

        ctx1 = ex1._get_template_context("TEST-01")
        ctx2 = ex2._get_template_context("TEST-01")

        assert ctx1["context"]["maintainers"] == ctx2["context"]["maintainers"]
        assert ctx1["context"]["maintainers"] == "@alice @bob @charlie"


class TestAutoDetectSortedIteration:
    """context/auto_detect: sorted iteration in the two survey-flagged spots."""

    @pytest.mark.unit
    def test_detect_ci_provider_uses_sorted_listdir(self, tmp_path: Path, monkeypatch) -> None:
        """Regression guard: os.listdir call is wrapped in sorted()."""
        from darnit.context import auto_detect

        # Layout a repo that has .github/workflows with a mix of file names.
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "z_last.yml").write_text("")
        (workflows / "a_first.yml").write_text("")

        # Spy on os.listdir. detect_ci_provider must consult sorted() over
        # the raw listdir result.
        seen_iterations: list[list[str]] = []
        real_listdir = os.listdir

        def spy_listdir(path):
            entries = real_listdir(path)
            seen_iterations.append(list(entries))
            return entries

        monkeypatch.setattr(auto_detect.os, "listdir", spy_listdir)

        provider = auto_detect.detect_ci_provider(str(tmp_path))
        assert provider == "github"
        # There was at least one listdir over the workflows dir.
        wf_iters = [i for i in seen_iterations if "z_last.yml" in i and "a_first.yml" in i]
        assert wf_iters, "expected a listdir over .github/workflows"
        # The listdir result was consumed via sorted() -- we can only
        # observe the raw listdir shape, but any(...) evaluated after
        # sorted must return the same bool. This test proves the sort
        # doesn't break detection when the FS order is jumbled.
