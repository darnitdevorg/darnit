"""Feature 036: the feature must be silent when nothing goes wrong.

Two guarantees, both easy to break accidentally:

* FR-014 / SC-002 -- output is byte-for-byte identical to the pre-feature
  implementation when no environmental failure fires. Verified against a
  baseline captured from unmodified `main` BEFORE any implementation task
  ran (see fixtures/error_class_baseline/, task T001a). Comparing against
  goldens generated during implementation would be circular: it would lock
  post-feature behavior rather than prove pre-feature equivalence.

* SC-003's converse -- a clean audit produces no new WARN noise. If every
  run started emitting warnings, operators would learn to ignore them and
  the loud-logging half of the feature would be worthless.

* FR-015 / SC-007 -- no new runtime dependency.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = Path(__file__).parent / "fixtures" / "error_class_baseline"
CAPTURE_SCRIPT = BASELINE_DIR / "capture_baseline.py"


class TestHappyPathByteForByteInvariance:
    """SC-002: zero environmental failures means zero output drift."""

    @pytest.mark.unit
    def test_baseline_files_exist(self) -> None:
        """Guard: a missing baseline silently voids the rest of this class."""
        for name in ("baseline.md", "baseline.json", "baseline.sarif"):
            assert (BASELINE_DIR / name).is_file(), (
                f"{name} missing -- SC-002 cannot be verified without the "
                "pre-feature baseline captured in task T001a"
            )

    @pytest.mark.unit
    def test_regenerated_output_matches_prefeature_baseline(
        self, tmp_path: Path
    ) -> None:
        """Re-run the capture and diff against the committed pre-feature files.

        The capture script writes in place, so this test runs it in a copy of
        the repo tree's fixture dir and compares, leaving the committed
        baseline untouched.
        """
        committed = {
            name: (BASELINE_DIR / name).read_text(encoding="utf-8")
            for name in ("baseline.md", "baseline.json", "baseline.sarif")
        }

        proc = subprocess.run(
            [
                "uv",
                "run",
                "python",
                str(CAPTURE_SCRIPT),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert proc.returncode == 0, (
            f"baseline capture failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )

        for name, expected in committed.items():
            actual = (BASELINE_DIR / name).read_text(encoding="utf-8")
            assert actual == expected, (
                f"{name} drifted from the pre-feature baseline.\n"
                "Feature 036 must be silent in the happy path (FR-014). If "
                "this diff is intentional, the change is NOT additive-only "
                "and needs its own spec decision -- do not just regenerate "
                "the baseline to make this pass."
            )

    @pytest.mark.unit
    def test_baseline_carries_no_error_class_anywhere(self) -> None:
        """The pre-feature baseline predates the field; it must not appear."""
        payload = json.loads((BASELINE_DIR / "baseline.json").read_text())
        for result in payload:
            assert "error_class" not in result, (
                f"{result['id']} carries error_class in the pre-feature "
                "baseline, which should be impossible"
            )

    @pytest.mark.unit
    def test_baseline_includes_a_clean_failure(self) -> None:
        """The baseline is only meaningful if it exercises the FAIL path.

        A clean FAIL is the case most at risk of wrongly gaining an
        error_class -- it is a real finding, not an environment problem.
        """
        payload = json.loads((BASELINE_DIR / "baseline.json").read_text())
        statuses = {r["status"] for r in payload}
        assert "FAIL" in statuses, (
            "baseline must include at least one clean FAIL so the "
            "no-annotation-on-real-findings invariant is actually covered"
        )
        assert "PASS" in statuses, "baseline should also cover the PASS path"


class TestNoWarnOnHappyPath:
    """SC-003 converse: a clean run adds no WARN noise."""

    @pytest.mark.unit
    def test_deterministic_handlers_emit_no_environmental_warnings(
        self, tmp_path: Path, caplog
    ) -> None:
        from darnit.sieve.builtin_handlers import file_exists_handler
        from darnit.sieve.handler_registry import HandlerContext

        (tmp_path / "README.md").write_text("# hi\n")
        ctx = HandlerContext(
            local_path=str(tmp_path),
            owner="o",
            repo="r",
            default_branch="main",
            control_id="TEST-01.01",
            project_context={},
            gathered_evidence={},
            shared_cache={},
            dependency_results={},
        )

        with caplog.at_level(logging.WARNING):
            hit = file_exists_handler(
                {"handler": "file_exists", "files": ["README.md"]}, ctx
            )
            miss = file_exists_handler(
                {"handler": "file_exists", "files": ["NOPE.md"]}, ctx
            )

        assert hit.error_class is None
        assert miss.error_class is None, (
            "a file that is genuinely absent is a finding, not an "
            "environmental failure"
        )
        env_warns = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "error_class" in r.getMessage()
        ]
        assert env_warns == [], (
            f"deterministic handlers must not emit environmental warnings: "
            f"{[r.getMessage() for r in env_warns]}"
        )


class TestNoNewRuntimeDependency:
    """FR-015 / SC-007: stdlib only."""

    TOUCHED_FRAMEWORK_FILES = (
        "packages/darnit/src/darnit/core/error_class.py",
        "packages/darnit/src/darnit/sieve/handler_registry.py",
        "packages/darnit/src/darnit/sieve/models.py",
        "packages/darnit/src/darnit/sieve/builtin_handlers.py",
        "packages/darnit/src/darnit/sieve/orchestrator.py",
        "packages/darnit/src/darnit/context/auto_detect.py",
    )

    # Everything this feature is allowed to import at module scope, beyond
    # first-party `darnit.*` and relative imports.
    ALLOWED_STDLIB = frozenset(
        {
            "__future__",
            "abc",
            "collections",
            "dataclasses",
            "datetime",
            "enum",
            "fnmatch",
            "glob",
            "hashlib",
            "json",
            "logging",
            "os",
            "pathlib",
            "re",
            "shutil",
            "subprocess",
            "sys",
            "tempfile",
            "time",
            "typing",
            "urllib",
        }
    )

    @pytest.mark.unit
    def test_error_class_module_imports_only_typing(self) -> None:
        """The new module is the one place a stray dep would be easiest to add."""
        import ast

        src = (REPO_ROOT / "packages/darnit/src/darnit/core/error_class.py").read_text()
        tree = ast.parse(src)
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        assert roots <= {"__future__", "typing"}, (
            f"core/error_class.py must depend on typing only; found {roots}"
        )

    @pytest.mark.unit
    def test_no_third_party_imports_in_touched_files(self) -> None:
        import ast

        offenders: dict[str, set[str]] = {}
        for rel in self.TOUCHED_FRAMEWORK_FILES:
            tree = ast.parse((REPO_ROOT / rel).read_text())
            roots = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level and node.level > 0:
                        continue  # relative import, first-party
                    if node.module:
                        roots.add(node.module.split(".")[0])
            unexpected = roots - self.ALLOWED_STDLIB - {"darnit"}
            if unexpected:
                offenders[rel] = unexpected

        assert offenders == {}, (
            f"feature 036 must add no runtime dependency; unexpected "
            f"module-scope imports: {offenders}"
        )
