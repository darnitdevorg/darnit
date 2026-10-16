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
import re
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


# Issue #528 dropped the ignored ``auto_init_config`` parameter. The parity
# callers had to stop passing it. Those mechanical edits are not a parity
# feature. A harness file qualifies only when every changed line is one of
# the lines below, and the same change removes the parameter from the
# product signature. Any other added or removed line keeps the file in scope.
_AUTO_INIT_CONFIG_REMOVED_LINES = frozenset(
    {
        "auto_init_config=False,",
        'args["auto_init_config"] = False',
        "# Force safe defaults.",
    }
)
_AUTO_INIT_CONFIG_ADDED_LINES = frozenset(
    {
        'args.pop("auto_init_config", None)',
        "# Force safe defaults. Drop the removed no-op if a model still sends it.",
    }
)
_AUTO_INIT_CONFIG_SIGNATURE = re.compile(r"^auto_init_config\s*:\s*bool\b")
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


def _diff_line_bodies(diff_text: str) -> tuple[list[str], list[str]]:
    """Added and removed line bodies from a unified diff, headers excluded."""
    removed: list[str] = []
    added: list[str] = []
    for raw in diff_text.splitlines():
        if raw.startswith(("diff ", "index ", "---", "+++", "@@", "\\")):
            continue
        if raw.startswith("-"):
            removed.append(raw[1:].strip())
        elif raw.startswith("+"):
            added.append(raw[1:].strip())
    return removed, added


def _is_auto_init_config_callsite_diff(diff_text: str) -> bool:
    """True when the diff only drops or pops the obsolete ``auto_init_config`` argument."""
    removed, added = _diff_line_bodies(diff_text)
    if any(line not in _AUTO_INIT_CONFIG_REMOVED_LINES for line in removed):
        return False
    if any(line not in _AUTO_INIT_CONFIG_ADDED_LINES for line in added):
        return False
    removed_code = [line for line in removed if not line.startswith("#")]
    added_code = [line for line in added if not line.startswith("#")]
    if not removed_code:
        return False
    assignments = [line for line in removed_code if line == 'args["auto_init_config"] = False']
    kwargs = [line for line in removed_code if line == "auto_init_config=False,"]
    pops = [line for line in added_code if line == 'args.pop("auto_init_config", None)']
    return len(assignments) + len(kwargs) == len(removed_code) and pops == added_code and len(pops) == len(assignments)


def _product_diff_removes_auto_init_config_parameter(product_diff: str) -> bool:
    """True when a removed line is the ``auto_init_config`` signature parameter."""
    for raw in product_diff.splitlines():
        if raw.startswith("-") and not raw.startswith("---") and _AUTO_INIT_CONFIG_SIGNATURE.match(raw[1:].strip()):
            return True
    return False


def _harness_candidates(changed: list[str]) -> list[str]:
    return [
        path
        for path in changed
        if path.startswith("tests/darnit/parity/") and not path.startswith(_FIXTURES) and path != _SELF
    ]


def parity_harness_feature_paths(
    changed: list[str],
    harness_diffs: dict[str, str],
    product_diff: str,
) -> list[str]:
    """Parity paths that make this a feature-028 PR.

    Call-site updates for ``auto_init_config`` drop out only when the product
    diff removes that parameter. A missing harness diff is not compatibility.
    """
    candidates = _harness_candidates(changed)
    if not candidates or not _product_diff_removes_auto_init_config_parameter(product_diff):
        return candidates
    return [path for path in candidates if not _is_auto_init_config_callsite_diff(harness_diffs.get(path, ""))]


def _git_diff(base: str, *paths: str) -> str:
    rc = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}...HEAD", "--", *paths],
        capture_output=True,
        text=True,
        check=True,
    )
    return rc.stdout


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

    # FR-014's scope is "parity-tests PR MUST NOT modify product source",
    # so this check only applies to PRs that change the parity harness --
    # the tier1/tier2 test code. A PR that changes product behavior
    # legitimately updates parity fixtures and their expected outcomes under
    # `tests/darnit/parity/fixtures/`, and that alone does not make it a
    # parity-tests PR. A PR that doesn't touch the harness is not a
    # parity-tests PR and may edit product code under `packages/*/src/`.
    #
    # Exclude this file itself from the heuristic: a PR that only touches
    # the guard (to tune scope, adjust base-ref detection, etc.) is a
    # meta-change to the guard, not a parity-tests-feature PR.
    #
    # Issue #528 also updates existing audit call sites so they no longer
    # pass ``auto_init_config``. That is a compatibility edit, not a parity
    # feature, when the product signature removes the parameter in this
    # same change. The whole file stays in scope if any other line changes.
    candidates = _harness_candidates(changed)
    product_paths = [path for path in changed if path.startswith(_PRODUCT_PREFIXES)]
    product_diff = _git_diff(base, *product_paths) if product_paths else ""
    harness_diffs = {path: _git_diff(base, path) for path in candidates}
    feature_paths = parity_harness_feature_paths(changed, harness_diffs, product_diff)
    if not feature_paths:
        if candidates:
            pytest.skip(
                "FR-014 check skipped: parity-tree edits only drop the removed "
                "auto_init_config call sites, and the product signature drops "
                "that parameter in this change.",
            )
        pytest.skip(
            "FR-014 check skipped: PR does not modify the parity harness "
            "(tests/darnit/parity/ outside fixtures/, other than this guard), "
            "so it is not a parity-tests PR and FR-014's product-code "
            "guardrail does not apply.",
        )

    forbidden = [path for path in changed if path.startswith(_PRODUCT_PREFIXES)]
    assert not forbidden, (
        "Feature 028 (parity tests) MUST NOT modify product source code "
        "(FR-014). Offending files:\n"
        + "\n".join(f"  - {f}" for f in forbidden)
        + "\n\nIf a change under packages/*/src/ is genuinely necessary, "
        "split it into a separate PR that is not scoped to feature 028."
    )


_PRODUCT = "packages/darnit-baseline/src/darnit_baseline/tools.py"
_SKILL = "packages/darnit/src/darnit/skills/darnit-data/SKILL.md"
_FIXTURE = "tests/darnit/parity/fixtures/all_pass_repo/parity.toml"
_CONFTEST = "tests/darnit/parity/tier1/conftest.py"
_RUN = "tests/darnit/parity/tier2/run.py"
_OPENAI = "tests/darnit/parity/tier2/backends/openai_backend.py"

_SIGNATURE_DIFF = """\
--- a/packages/darnit-baseline/src/darnit_baseline/tools.py
+++ b/packages/darnit-baseline/src/darnit_baseline/tools.py
@@ -96,1 +95,0 @@ def audit_openssf_baseline(
-    auto_init_config: bool = True,
"""

_KWARG_DIFF = """\
--- a/tests/darnit/parity/tier1/conftest.py
+++ b/tests/darnit/parity/tier1/conftest.py
@@ -141,1 +140,0 @@ def mcp_tool_result(
-        auto_init_config=False,
"""

_POP_DIFF = """\
--- a/tests/darnit/parity/tier2/backends/openai_backend.py
+++ b/tests/darnit/parity/tier2/backends/openai_backend.py
@@ -83,2 +83,2 @@ def _dispatch_tool_call(
-        # Force safe defaults.
-        args["auto_init_config"] = False
+        # Force safe defaults. Drop the removed no-op if a model still sends it.
+        args.pop("auto_init_config", None)
"""


def test_528_compatibility_edits_are_not_a_parity_feature() -> None:
    """The three #528 call-site updates do not make this a parity-tests PR."""
    changed = [_PRODUCT, _SKILL, _CONFTEST, _RUN, _OPENAI]
    diffs = {_CONFTEST: _KWARG_DIFF, _RUN: _KWARG_DIFF, _OPENAI: _POP_DIFF}

    assert parity_harness_feature_paths(changed, diffs, _SIGNATURE_DIFF) == []


def test_harness_logic_change_with_product_edits_stays_in_scope() -> None:
    """An extra assertion beside the call-site edit is still a parity-feature change."""
    tainted = _KWARG_DIFF + "+        assert report.is_green\n"
    changed = [_PRODUCT, _CONFTEST]

    assert parity_harness_feature_paths(changed, {_CONFTEST: tainted}, _SIGNATURE_DIFF) == [_CONFTEST]


def test_product_only_change_is_not_a_parity_feature() -> None:
    assert parity_harness_feature_paths([_PRODUCT, _SKILL], {}, _SIGNATURE_DIFF) == []


def test_fixture_only_change_is_not_a_parity_feature() -> None:
    changed = [_PRODUCT, _FIXTURE]

    assert parity_harness_feature_paths(changed, {}, _SIGNATURE_DIFF) == []


def test_compatibility_without_signature_removal_stays_in_scope() -> None:
    """A docstring mention is not removal of the signature parameter."""
    docstring_only = "-        auto_init_config: Create .project.yaml if missing. Default: True\n"
    changed = [_PRODUCT, _CONFTEST]

    assert parity_harness_feature_paths(changed, {_CONFTEST: _KWARG_DIFF}, docstring_only) == [_CONFTEST]


def test_unrelated_harness_lines_are_not_compatibility() -> None:
    imported = _KWARG_DIFF + "+import os\n"
    branched = _POP_DIFF + "+        if True:\n"
    changed = [_PRODUCT, _CONFTEST, _OPENAI]
    diffs = {_CONFTEST: imported, _OPENAI: branched}

    assert parity_harness_feature_paths(changed, diffs, _SIGNATURE_DIFF) == [_CONFTEST, _OPENAI]
