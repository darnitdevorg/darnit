"""Fixtures and helpers for tests/darnit/cli/ (feature 024 E2E baseline).

Provides:
- ``minimal_repo_tree`` / ``malformed_project_tree``: fixture-tree copies to tmp
- ``_MUST_NOT_BE_CALLED`` / ``_SUBPROCESS_STUBS``: the two-tier stub registry
- ``deterministic_run``: fixture that applies both stub tiers to guarantee
  no LLM/MCP call and no real subprocess call escape cmd_run's codepath
- ``invoke_cmd_run``: in-process argparse-and-dispatch helper

See specs/024-cmd-run-e2e-tests/data-model.md for the canonical shapes.
"""

from __future__ import annotations

import shutil
import subprocess
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Stub registries (see data-model.md section 4)
# ---------------------------------------------------------------------------

# Tier 1: entry points that must never be called from cmd_run's codepath.
# Each entry is (module_path, attr_name); patched with side_effect=RuntimeError.
# Currently empty: grep confirms no LLM SDK or MCP client is imported from the
# transitive closure of cmd_run. The tuple is wired so future accidental
# introduction surfaces as a named failure. Add e.g. ("openai", "ChatCompletion")
# here if that import ever becomes reachable.
_MUST_NOT_BE_CALLED: tuple[tuple[str, str], ...] = ()

# Tier 2: subprocess call sites reachable from cmd_run.
# Each entry is (module_path, attr_name) naming the module-scoped ``subprocess``
# reference; the deterministic_run fixture replaces each with a namespace object
# whose .run returns a canned subprocess.CompletedProcess.
_SUBPROCESS_STUBS: tuple[tuple[str, str], ...] = (
    ("darnit.core.utils", "subprocess"),
    ("darnit.sieve.builtin_handlers", "subprocess"),
)


# ---------------------------------------------------------------------------
# Collection-time guard (T006): every registry entry must resolve to a real
# attribute. If a production rename breaks the mapping, produce a clear
# collection error rather than a silent bypass.
# ---------------------------------------------------------------------------


def _assert_registry_resolves(registry: tuple[tuple[str, str], ...], label: str) -> None:
    for module_path, attr_name in registry:
        try:
            mod = import_module(module_path)
        except ImportError as exc:
            raise pytest.UsageError(f"{label} references missing module {module_path!r}: {exc}") from exc
        if not hasattr(mod, attr_name):
            raise pytest.UsageError(f"{label} references missing attribute {module_path}.{attr_name}")


_assert_registry_resolves(_MUST_NOT_BE_CALLED, "_MUST_NOT_BE_CALLED")
_assert_registry_resolves(_SUBPROCESS_STUBS, "_SUBPROCESS_STUBS")


# ---------------------------------------------------------------------------
# Fixture-tree helpers
# ---------------------------------------------------------------------------


def _copy_and_init(src: Path, dest: Path) -> Path:
    """Copy a fixture tree into ``dest`` and initialise it as a git repo."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    # Real subprocess here (before deterministic_run patches). We don't want
    # this init call routed through the stub -- fixture prep must be real.
    subprocess.run(
        ["git", "init", "--initial-branch=main", "-q"],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    # Configure a local user so commit works without touching global git config.
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "init",
        ],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    # Add a fake origin remote so detect_repo_from_git can extract owner/repo
    # without doing a real network call. The URL is bogus but well-formed.
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/fake-owner/fake-repo.git"],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    return dest


@pytest.fixture
def minimal_repo_tree(tmp_path: Path) -> Path:
    """Copy the MinimalRepo fixture to tmp and git-init it."""
    return _copy_and_init(FIXTURES_DIR / "minimal_repo", tmp_path / "minimal_repo")


@pytest.fixture
def malformed_project_tree(tmp_path: Path) -> Path:
    """Copy the MalformedProjectYaml fixture to tmp and git-init it."""
    return _copy_and_init(
        FIXTURES_DIR / "malformed_project",
        tmp_path / "malformed_project",
    )


@pytest.fixture
def failing_repo_tree(tmp_path: Path) -> Path:
    """Copy the failing_repo fixture (produces >=1 FAIL) and git-init it.

    Used to pin the "Failed > 0 -> exit 1" branch of the exit-code rule
    (SC-002). Without a fixture that produces FAILs, always-return-0
    perturbations of cmd_run would slip past golden-path assertions.
    """
    return _copy_and_init(FIXTURES_DIR / "failing_repo", tmp_path / "failing_repo")


# ---------------------------------------------------------------------------
# Subprocess stub factory
# ---------------------------------------------------------------------------


def _make_fake_subprocess() -> SimpleNamespace:
    """Build a namespace object that stands in for the ``subprocess`` module.

    Exposes .run (canned success), .PIPE / .STDOUT constants, and
    .CalledProcessError / .TimeoutExpired / .CompletedProcess types so any
    caller that uses these still works.

    All calls go to ``fake_run`` which by default returns exit 0 with empty
    stdout. Tests that need a specific canned response can monkeypatch this
    fake before invoking cmd_run.
    """
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        # Normalise cmd to a list for recording
        recorded = list(cmd) if isinstance(cmd, (list, tuple)) else [str(cmd)]
        calls.append(recorded)

        # `git remote get-url <name>`: return a canned GitHub URL for
        # `origin` so detect_repo_from_git succeeds under stubs (matches the
        # real fixture's origin), exit-2 for anything else.
        if len(recorded) >= 4 and recorded[0] == "git" and recorded[1] == "remote" and recorded[2] == "get-url":
            if recorded[3] == "origin":
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="https://github.com/fake-owner/fake-repo.git\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=2,
                stdout="",
                stderr="fatal: No such remote\n",
            )

        # `gh repo view ...` -> canned "not found" so _gh_enrich returns empty.
        if recorded[0] == "gh":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr="gh: not found\n",
            )

        # Everything else -> canned success. Sieve exec-handler controls that
        # shell out get an empty-but-successful response; testchecks doesn't
        # exercise this today.
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    ns = SimpleNamespace(
        run=fake_run,
        PIPE=subprocess.PIPE,
        STDOUT=subprocess.STDOUT,
        DEVNULL=subprocess.DEVNULL,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired,
        CompletedProcess=subprocess.CompletedProcess,
        # Expose the recorder so tests can assert on argv shapes.
        _recorded_calls=calls,
    )
    return ns


@pytest.fixture
def deterministic_run(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Apply both stub tiers.

    Returns the fake-subprocess namespace so tests can inspect
    ``fake._recorded_calls`` to verify argv shapes.
    """
    # Tier 1: LLM/MCP entry points must not be called.
    for module_path, attr_name in _MUST_NOT_BE_CALLED:
        mod = import_module(module_path)
        stub = MagicMock(
            side_effect=RuntimeError(
                f"must not be called: {module_path}.{attr_name}",
            ),
        )
        monkeypatch.setattr(mod, attr_name, stub)

    # Tier 2: subprocess call sites get a shared canned-success fake so all
    # patched sites route to the same recorder and can be asserted together.
    fake = _make_fake_subprocess()
    for module_path, attr_name in _SUBPROCESS_STUBS:
        mod = import_module(module_path)
        monkeypatch.setattr(mod, attr_name, fake)

    return fake


# ---------------------------------------------------------------------------
# cmd_run invocation helper (T007)
# ---------------------------------------------------------------------------


def invoke_cmd_run(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    """Parse ``argv`` through darnit's argparse wiring and dispatch to cmd_run.

    Returns ``(exit_code, stdout, stderr)``. The stdout/stderr capture is
    per-test via pytest's capsys fixture.

    ``argv`` should be the args AFTER the subcommand name -- this helper
    prepends "run" itself, so a caller passes e.g.
    ``[str(fixture_path), "--feedback", "noninteractive"]``.

    Bypasses ``darnit.cli.main()`` and dispatches through ``create_parser()``
    directly so ``configure_logging()`` is NOT called (that side effect leaks
    handler state into other tests -- see tests/darnit/core/test_logging.py
    which asserts on the default NullHandler shape).
    """
    import logging

    from darnit.cli import create_parser

    parser = create_parser()

    exit_code: int | None = None
    darnit_logger = logging.getLogger("darnit")
    # Snapshot the darnit logger state and restore it after the invocation so
    # `logger.info(...)` calls inside cmd_run's codepath don't add handlers
    # or mutate level in a way that leaks into subsequent tests.
    saved_handlers = list(darnit_logger.handlers)
    saved_level = darnit_logger.level
    saved_disabled = darnit_logger.disabled

    try:
        args = parser.parse_args(["run", *argv])
    except SystemExit as exc:
        # Argparse calls sys.exit on invalid input. Preserve the code and
        # skip dispatch.
        code = exc.code
        exit_code = 0 if code is None else int(code)  # type: ignore[arg-type]
        captured = capsys.readouterr()
        return exit_code, captured.out, captured.err

    try:
        if args.command is None:
            exit_code = 0
        else:
            exit_code = args.func(args)
    except SystemExit as exc:
        code = exc.code
        exit_code = 0 if code is None else int(code)  # type: ignore[arg-type]
    finally:
        darnit_logger.handlers[:] = saved_handlers
        darnit_logger.setLevel(saved_level)
        darnit_logger.disabled = saved_disabled

    captured = capsys.readouterr()
    assert exit_code is not None
    return exit_code, captured.out, captured.err
