"""FR-014 mechanical enforcement (feature 028 T031a).

Runs `git diff --name-only <base>...HEAD` and asserts no file under
`packages/darnit/src/` or `packages/darnit-baseline/src/` is modified in
the current PR. Guards against a future maintainer accidentally adding
a "small helper" to product code from a parity-tests PR.

The same paths also change when a product PR has to update an existing
parity-harness caller. Such a PR declares itself with the commit trailer
``Parity-Guard: not-a-parity-pr``, read by git's own trailer parser. The
trailer is a reviewer-visible claim, not proof that the harness edits are
compatibility updates: a parity-suite PR can add the same trailer and bypass
this guard, so reviewers have to confirm the claim before accepting the skip.

Fails loudly (not silently) when the base ref cannot be reached under
CI, since a shallow-clone runner that silently passes gives the
maintainer a false sense of coverage. PR #370 review fix.
"""

from __future__ import annotations

import os
import subprocess

import pytest

_BASE_CANDIDATES = (
    # `upstream/main` before `origin/main`: on a fork clone, `origin/main`
    # is often stale (last synced days ago) while `upstream/main` tracks
    # the source-of-truth remote. On the source repo itself,
    # `upstream/main` won't exist and we fall through to `origin/main`.
    "upstream/main",
    "origin/main",
    "main",
)


def _find_reachable_base() -> str | None:
    for candidate in _BASE_CANDIDATES:
        rc = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", candidate],
            capture_output=True,
            text=True,
        )
        if rc.returncode == 0 and rc.stdout.strip():
            return candidate
    return None


def _base_ref() -> str | None:
    """Detect the base ref to diff against. Returns None if none reachable
    even after unshallowing.

    Tries the immediate stack parent first (026-harness-with-stage1) because
    feature 028 is stacked on it during development; when 028 is on main
    (after 026 merges), origin/main is the right base. The precise order
    matters because a stacked-branch check against `main` would incorrectly
    flag every 026 change as a violation. Under a shallow CI clone (the
    default `actions/checkout` config) the base ref is often not initially
    reachable; try `git fetch --unshallow` + a full remote sync once before
    giving up.
    """
    hit = _find_reachable_base()
    if hit is not None:
        return hit

    # Shallow-clone recovery path. `--unshallow` deepens the current ref,
    # but stack-parent refs (`origin/026-harness-with-stage1`) live on
    # OTHER branches -- add an explicit refspec fetch so they appear.
    # Both commands quietly succeed even when there's no remote to fetch
    # from (or the repo is already unshallow); either way we re-check.
    subprocess.run(
        ["git", "fetch", "--unshallow", "--tags", "origin"],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"],
        capture_output=True,
        text=True,
    )
    return _find_reachable_base()


_SELF = "tests/darnit/parity/tier1/test_no_product_changes.py"
_FIXTURES = "tests/darnit/parity/fixtures/"
_PRODUCT_PREFIXES = ("packages/darnit/src/", "packages/darnit-baseline/src/")


def _is_ci() -> bool:
    """True on GitHub Actions and most other CI runners.

    The CI env var is set by GitHub Actions, GitLab CI, CircleCI,
    Travis, and Buildkite; that's a good-enough shibboleth for
    turning the "no base ref" case from skip -> fail.
    """
    return bool(os.environ.get("CI"))


def _touches_parity_harness(changed: list[str]) -> bool:
    """Whether tier1/tier2 parity code changed.

    Fixture and expectation updates under fixtures/ come with product behavior
    changes, and an edit to this guard alone is a meta-change; neither makes a
    PR a parity-tests PR.
    """
    return any(
        path.startswith("tests/darnit/parity/") and not path.startswith(_FIXTURES) and path != _SELF for path in changed
    )


def _product_paths(changed: list[str]) -> list[str]:
    return [path for path in changed if path.startswith(_PRODUCT_PREFIXES)]


def _declares_product_pr(base: str) -> bool:
    """Whether a commit in ``base..HEAD`` has the trailer ``Parity-Guard: not-a-parity-pr``.

    Git decides which lines are trailers, so the same words in a subject or
    body do not count. ``key=`` matches case-insensitively and ``valueonly``
    prints one value per line.
    """
    rc = subprocess.run(
        ["git", "log", "--format=%(trailers:key=Parity-Guard,valueonly)", f"{base}..HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return any(value.strip() == "not-a-parity-pr" for value in rc.stdout.splitlines())


def test_no_product_source_changes() -> None:
    """FR-014: parity-tests PR MUST NOT modify product source. Test/config
    files are exempt so a build-config touch or a test refactor stays in
    scope.

    Now that PR #365 has merged, feature 028 sits directly on `main`;
    the base ref is `origin/main` (or a local `main` variant) and the
    diff cleanly identifies the parity PR's own commits. If no main ref
    is reachable at all -- e.g., a shallow CI clone without unshallow
    -- fall back to skip (local dev) or fail (CI, with a clear pointer
    at fetch depth).
    """
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

    if not _touches_parity_harness(changed):
        pytest.skip(
            "FR-014 check skipped: PR does not modify the parity harness "
            "(tests/darnit/parity/ outside fixtures/, other than this guard), "
            "so it is not a parity-tests PR and FR-014's product-code "
            "guardrail does not apply.",
        )

    forbidden = _product_paths(changed)
    if forbidden and _declares_product_pr(base):
        pytest.skip(
            "FR-014 check skipped: a commit in this PR carries the trailer "
            "`Parity-Guard: not-a-parity-pr`, declaring that this is a product "
            "change whose parity-harness edits are compatibility updates for "
            "existing callers. Reviewers must confirm that declaration. The "
            "trailer is a claim, not proof: a parity-suite change can carry the "
            "same trailer and bypass this guard.",
        )
    assert not forbidden, (
        "Feature 028 (parity tests) MUST NOT modify product source code "
        "(FR-014). Offending files:\n"
        + "\n".join(f"  - {f}" for f in forbidden)
        + "\n\nIf a change under packages/*/src/ is genuinely necessary, "
        "split it into a separate PR that is not scoped to feature 028."
    )


_PRODUCT = "packages/darnit-baseline/src/darnit_baseline/tools.py"
_HARNESS = "tests/darnit/parity/tier1/conftest.py"
_FIXTURE = "tests/darnit/parity/fixtures/example/parity.toml"


@pytest.mark.parametrize(
    ("changed", "touches_harness", "product"),
    [
        pytest.param([_PRODUCT], False, [_PRODUCT], id="product-only"),
        pytest.param([_FIXTURE, _PRODUCT], False, [_PRODUCT], id="fixtures-plus-product"),
        pytest.param([_SELF, _PRODUCT], False, [_PRODUCT], id="guard-file-plus-product"),
        pytest.param([_HARNESS, _PRODUCT], True, [_PRODUCT], id="harness-and-product"),
        pytest.param([_HARNESS], True, [], id="harness-only"),
        pytest.param([], False, [], id="empty-change-list"),
    ],
)
def test_fr014_path_rules(changed: list[str], touches_harness: bool, product: list[str]) -> None:
    assert _touches_parity_harness(changed) is touches_harness
    assert _product_paths(changed) == product


def _commit(*paragraphs: str) -> None:
    message = [arg for paragraph in paragraphs for arg in ("-m", paragraph)]
    subprocess.run(
        ["git", "-c", "user.name=FR014", "-c", "user.email=fr014@example.com", "-c", "commit.gpgsign=false"]
        + ["commit", "--allow-empty", "-q", *message],
        check=True,
    )


@pytest.mark.parametrize(
    ("commits", "declared"),
    [
        pytest.param([("Update callers.", "Parity-Guard: not-a-parity-pr")], True, id="valid-trailer"),
        pytest.param([("Update callers.", "Parity-Guard: product-change")], False, id="invalid-value"),
        pytest.param(
            [
                (
                    "The review asked about Parity-Guard: not-a-parity-pr as an example.",
                    "Signed-off-by: Ada <a@example.com>",
                )
            ],
            False,
            id="mentioned-in-prose",
        ),
        pytest.param([("Update callers.",)], False, id="no-trailer"),
        pytest.param([("Update callers.",), ("Declare.", "Parity-Guard: not-a-parity-pr")], True, id="later-commit"),
    ],
)
def test_parity_guard_trailer(tmp_path, monkeypatch, commits: list[tuple[str, ...]], declared: bool) -> None:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q", "-b", "main"], check=True)
    _commit("base")
    subprocess.run(["git", "branch", "base"], check=True)
    for paragraphs in commits:
        _commit(*paragraphs)
    assert _declares_product_pr("base") is declared
