"""SC-008 corpus definition and capture (feature 037).

No per-framework control corpus existed before this feature.
`tests/darnit/parity/fixtures/` holds repo directories, but each `parity.toml`
scopes the comparison to three OSPS controls plus one STAGE1 control; and
`tests/darnit/sieve/fixtures/` holds only a mock MCP server. So the corpus is
defined here explicitly rather than borrowed.

Two things this module exists to work around, both pre-existing:

1. Control registration is process-global and leaks across frameworks. A
   `reproducibility` audit returns 5 controls in a clean process and 71 (65 of
   them OSPS baseline) if an `openssf-baseline` audit ran earlier in the same
   process. Each pair therefore runs in a fresh subprocess. Filed as #442.

2. `run_checks` writes a `.project/` directory into the repository it audits.
   Fixtures are copied into scratch space first; auditing them in place leaves
   untracked files in the source tree, which is what broke CI on #435.

The corpus is deliberately narrower than "every framework x every fixture". The
full cross product did not finish in 12 minutes, because every exec handler
that shells out to `gh` pays a network timeout per control. What is kept is
what SC-008 needs: `reproducibility` is the framework this feature changes, and
`openssf-baseline` is the largest control set and exercises the most handler
dispatch paths.

Note that this module captures; it does not compare against a stored golden.
Control statuses depend on the environment as much as on the code, so
`test_control_status_baseline.py` captures twice in one environment and diffs
those instead.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_FIXTURES = REPO_ROOT / "tests" / "darnit" / "parity" / "fixtures"
# Deliberately narrower than "every framework x every fixture". The full cross
# product was tried first and abandoned: 5 frameworks x 5 repos x 2 runs of a
# level-3 audit did not finish in 12 minutes, because every exec handler that
# shells out to `gh` pays a network timeout per control. A baseline nobody will
# re-run is not a baseline.
#
# What is kept is what SC-008 actually needs. `reproducibility` is the framework
# this feature changes; `openssf-baseline` is the largest control set and the
# one exercising the most handler dispatch paths. The network-dependent controls
# that were dropped are precisely the ones the two-run diff would have excluded
# as nondeterministic anyway, so their coverage was illusory.
FRAMEWORK_NAMES = ("reproducibility", "openssf-baseline")
FIXTURE_NAMES = ("all_pass_repo", "mixed_repo")


def repo_inputs(scratch: Path) -> dict[str, Path]:
    """The repo inputs, each COPIED into scratch space before being audited.

    Auditing a fixture in place is not read-only: `run_checks` writes a
    `.project/` directory (project.yaml, darnit.yaml) into the repository it
    audits. Pointing the capture at `tests/darnit/parity/fixtures/` directly
    therefore leaves untracked files in the source tree -- the same pollution
    that broke CI on PR #435, where feature 028's product-source guard tripped
    on a stray `.project/` under a parity fixture.

    Copying is not defensive tidiness. Without it, running this capture dirties
    the working tree of whoever runs it.
    """
    inputs: dict[str, Path] = {}
    for name in FIXTURE_NAMES:
        source = PARITY_FIXTURES / name
        if not source.exists():
            continue
        destination = scratch / name
        shutil.copytree(source, destination)
        inputs[name] = destination

    empty = scratch / "empty_repo"
    empty.mkdir()
    inputs["empty_repo"] = empty
    return inputs


def framework_names() -> list[str]:
    """The corpus frameworks that are actually installed."""
    from darnit.core.discovery import discover_implementations

    installed = discover_implementations()
    return [name for name in FRAMEWORK_NAMES if name in installed]


def _control_id(result: Any) -> str:
    """run_checks returns dicts in some paths and objects in others."""
    if isinstance(result, dict):
        return str(result.get("id") or result.get("control_id") or "?")
    return str(getattr(result, "control_id", "?"))


def _status(result: Any) -> str:
    raw = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
    return raw.value if hasattr(raw, "value") else str(raw)


def _neutral_env(scratch: Path) -> dict[str, str]:
    """Environment in which `gh`-dependent controls behave the same everywhere.

    Without this the baseline pins properties of the machine rather than of the
    code. Seven OSPS controls resolve FAIL on a developer laptop with an
    authenticated `gh` and WARN on a CI runner without one, so a baseline
    captured in one environment can never pass in the other -- which is exactly
    how this test first failed in CI while passing locally.

    A `gh` shim that always fails, placed first on PATH, makes those controls
    deterministic. The rest of PATH is left intact because other handlers
    legitimately need `git` and friends.
    """
    shim_dir = scratch / "_neutral_bin"
    if not shim_dir.exists():
        shim_dir.mkdir()
        gh = shim_dir / "gh"
        gh.write_text(
            "#!/bin/sh\necho 'gh unavailable (baseline capture)' >&2\nexit 1\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    # Any of these would let an authenticated path re-enter through the API.
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "ANTHROPIC_API_KEY"):
        env.pop(name, None)
    return env


def _neutralize_warn() -> None:
    """Make a handler-level WARN behave the way it did before feature 037.

    Before the feature a handler could not express WARN at all, so the closest
    faithful simulation of "this outcome does not exist" is to route it the way
    an INCONCLUSIVE was routed: attach evidence and continue, or terminate
    INCONCLUSIVE on the last step.
    """
    from darnit.sieve import orchestrator
    from darnit.sieve.handler_registry import HandlerResultStatus

    original = orchestrator.resolve_step_result

    def patched(handler_status, effective_authority, is_last_step=False):
        if handler_status == HandlerResultStatus.WARN:
            return original(
                HandlerResultStatus.INCONCLUSIVE, effective_authority, is_last_step
            )
        return original(handler_status, effective_authority, is_last_step)

    orchestrator.resolve_step_result = patched
    orchestrator.SieveOrchestrator.__module__  # touch, keeps linters honest


def _capture_one(framework: str, repo_path: str, neutralize: bool = False) -> dict[str, str]:
    """Audit one (framework, repo) pair in THIS process."""
    if neutralize:
        _neutralize_warn()
    from darnit.tools.audit import run_checks

    results, _skipped = run_checks(
        owner="org",
        repo="repo",
        local_path=repo_path,
        default_branch="main",
        level=3,
        stop_on_llm=True,
        apply_user_config=False,
        framework_name=framework,
    )
    return {_control_id(r): _status(r) for r in results}


def capture(neutralize: bool = False) -> dict[str, dict[str, str]]:
    """Per-control status for every (framework, repo) pair.

    Each pair runs in a FRESH SUBPROCESS. This is not defensive style, it is
    required for the capture to mean anything: control registration is
    process-global and leaks across frameworks. Auditing `openssf-baseline`
    and then `reproducibility` in one process yields 71 controls for
    reproducibility instead of 5, 65 of them OSPS baseline controls. In-process
    capture therefore produced a 46% "nondeterministic" exclusion rate that was
    entirely this leak rather than any real nondeterminism.

    The leak is a pre-existing product defect, out of scope for feature 037 and
    tracked separately. Subprocess isolation is how this baseline avoids
    measuring it instead of measuring SC-008.
    """
    out: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory() as scratch:
        # Copy once, not once per framework: repo_inputs() is not idempotent
        # against the same scratch directory.
        inputs = repo_inputs(Path(scratch))
        for framework in framework_names():
            for repo_name, repo_path in inputs.items():
                key = f"{framework}::{repo_name}"
                argv = [sys.executable, __file__, "--worker", framework, str(repo_path)]
                if neutralize:
                    argv.append("--neutralize-warn")
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    cwd=str(REPO_ROOT),
                    env=_neutral_env(Path(scratch)),
                )
                if proc.returncode != 0:
                    out[key] = {"__capture_error__": proc.stderr.strip()[-400:]}
                    continue
                out[key] = json.loads(proc.stdout)
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--worker":
        print(
            json.dumps(
                _capture_one(
                    sys.argv[2], sys.argv[3], neutralize="--neutralize-warn" in sys.argv
                )
            )
        )
    else:
        import pprint

        pprint.pprint({k: len(v) for k, v in capture().items()})
