"""FR-014 mechanical enforcement (feature 028 T031a).

Runs `git diff --name-only <base>...HEAD` and asserts no file under
`packages/darnit/src/` or `packages/darnit-baseline/src/` is modified in
the current PR. Guards against a future maintainer accidentally adding
a "small helper" to product code from a parity-tests PR.

Skips on local dev when no base ref is reachable.
"""

from __future__ import annotations

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


def test_no_product_source_changes() -> None:
    """FR-014: parity-tests PR MUST NOT modify product source. Test/config
    files are exempt so a build-config touch or a test refactor stays in
    scope."""
    base = _base_ref()
    if base is None:
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
