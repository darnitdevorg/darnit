"""FR-014 mechanical enforcement (feature 028 T031a).

Runs `git diff --name-only <base>...HEAD` and asserts no file under
`packages/darnit/src/` or `packages/darnit-baseline/src/` is modified in
the current PR. Guards against a future maintainer accidentally adding
a "small helper" to product code from a parity-tests PR.

Fails loudly (not silently) when the base ref cannot be reached under
CI, since a shallow-clone runner that silently passes gives the
maintainer a false sense of coverage. PR #370 review fix.
"""

from __future__ import annotations

import os
import subprocess

import pytest


def _base_ref() -> str | None:
    """Detect the base ref to diff against. Returns None if none reachable.

    Tries the immediate stack parent first (026-harness-with-stage1) because
    feature 028 is stacked on it during development; when 028 is on main
    (after 026 merges), origin/main is the right base. The precise order
    matters because a stacked-branch check against `main` would incorrectly
    flag every 026 change as a violation.
    """
    for candidate in [
        "origin/026-harness-with-stage1",
        "026-harness-with-stage1",
        "origin/main",
        "upstream/main",
        "main",
    ]:
        rc = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", candidate],
            capture_output=True,
            text=True,
        )
        if rc.returncode == 0 and rc.stdout.strip():
            return candidate
    return None


def _is_ci() -> bool:
    """True on GitHub Actions and most other CI runners.

    The CI env var is set by GitHub Actions, GitLab CI, CircleCI,
    Travis, and Buildkite; that's a good-enough shibboleth for
    turning the "no base ref" case from skip -> fail.
    """
    return bool(os.environ.get("CI"))


def test_no_product_source_changes() -> None:
    """FR-014: parity-tests PR MUST NOT modify product source. Test/config
    files are exempt so a build-config touch or a test refactor stays in
    scope."""
    base = _base_ref()
    if base is None:
        # PR #370 review fix: silently skipping under shallow CI clones
        # gave a false sense of coverage. Skip only when running locally;
        # under CI, fail with a clear pointer at the fix (fetch depth).
        if _is_ci():
            pytest.fail(
                "FR-014 check cannot run: no base ref reachable and CI=1. "
                "Configure the workflow to fetch enough history (e.g., "
                "actions/checkout with fetch-depth: 0) so this check can "
                "compare against `origin/main`.",
            )
        pytest.skip("no base ref reachable (local dev); CI enforces this check")

    rc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    changed = [ln.strip() for ln in rc.stdout.splitlines() if ln.strip()]

    forbidden = [
        f for f in changed if (f.startswith("packages/darnit/src/") or f.startswith("packages/darnit-baseline/src/"))
    ]
    assert not forbidden, (
        "Feature 028 (parity tests) MUST NOT modify product source code "
        "(FR-014). Offending files:\n"
        + "\n".join(f"  - {f}" for f in forbidden)
        + "\n\nIf a change under packages/*/src/ is genuinely necessary, "
        "split it into a separate PR that is not scoped to feature 028."
    )
