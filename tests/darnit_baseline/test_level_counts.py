"""Per-level control-count regression test.

Compares darnit's `openssf-baseline.toml` level tags against the applicability
lists in the vendored upstream OSPS Baseline YAML for the pinned spec_version.
Blocks CI on drift.

Convention: each upstream control is assigned to its *lowest* applicable
maturity level. Darnit's single-integer `level` field mirrors that lowest
level. Controls tagged `deprecated = true` or `darnit_specific = true` are
excluded from the comparison (they are darnit-only annotations, not upstream
controls).

Bumping the pinned spec_version: update `spec_version` in
`packages/darnit-baseline/src/darnit_baseline/implementation.py`, re-vendor
the fixtures under `tests/darnit_baseline/fixtures/osps-baseline/`, and
update the tag reference in that directory's README.
"""

from __future__ import annotations

import glob
import re
import tomllib
from collections import Counter
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "osps-baseline"
BASELINE_TOML = REPO_ROOT / "packages" / "darnit-baseline" / "openssf-baseline.toml"

# Bump alongside the vendored fixture files and the spec_version in
# packages/darnit-baseline/src/darnit_baseline/implementation.py.
EXPECTED_UPSTREAM_TAG = "v2026.02.19"

# Runtime counts a user sees when running `darnit audit --level N`. Includes
# darnit-retained controls that are deprecated upstream (e.g., BR-01.02).
# Documented in docs/USAGE_GUIDE.md; update alongside a spec_version bump.
EXPECTED_RUNTIME_COUNTS = {1: 25, 2: 19, 3: 21}

# Upstream OSPS Baseline per-level counts under the lowest-applicable-level
# convention. Excludes controls that darnit retains but upstream has retired.
EXPECTED_UPSTREAM_COUNTS = {1: 24, 2: 19, 3: 21}

# Matches "maturity-N" (slug) and "Maturity Level N" (human string).
_LEVEL_RE = re.compile(r"maturity[-_ ]?(\d)|Maturity Level (\d)", re.IGNORECASE)


def _parse_level(app: str) -> int | None:
    match = _LEVEL_RE.search(app)
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def _load_upstream_lowest_levels() -> dict[str, int]:
    """Walk vendored YAML; return {control_id: lowest_maturity_level}.

    Controls with only 'retired' applicability (no maturity levels) are omitted.
    """
    result: dict[str, int] = {}
    for path in sorted(glob.glob(str(FIXTURE_DIR / "*.yaml"))):
        with open(path) as fh:
            doc = yaml.safe_load(fh)

        def walk(node: object) -> None:
            if isinstance(node, dict):
                cid = node.get("id")
                app = node.get("applicability")
                if isinstance(cid, str) and cid.startswith("OSPS-") and isinstance(app, list):
                    levels = sorted({lvl for a in app if isinstance(a, str) and (lvl := _parse_level(a)) is not None})
                    if levels:
                        result[cid] = levels[0]
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(doc)
    return result


def _load_darnit_levels(exclude_deprecated: bool = False, exclude_darnit_specific: bool = False) -> dict[str, int]:
    """Return {control_id: level} for every OSPS control in darnit's TOML.

    Args:
        exclude_deprecated: skip controls tagged `deprecated = true` (use when
            comparing against upstream, which does not carry retired controls).
        exclude_darnit_specific: skip controls tagged `darnit_specific = true`.
    """
    with open(BASELINE_TOML, "rb") as fh:
        config = tomllib.load(fh)

    result: dict[str, int] = {}
    for cid, ctrl in config.get("controls", {}).items():
        if not cid.startswith("OSPS-"):
            continue
        tags = ctrl.get("tags") or {}
        if exclude_deprecated and tags.get("deprecated"):
            continue
        if exclude_darnit_specific and tags.get("darnit_specific"):
            continue
        level = ctrl.get("level") if ctrl.get("level") is not None else tags.get("level")
        if level is None:
            pytest.fail(f"Control {cid} has no level tag in openssf-baseline.toml")
        result[cid] = level
    return result


@pytest.mark.unit
def test_fixture_tag_matches_pinned_spec_version() -> None:
    """The vendored fixture's README must reference the same upstream tag
    the implementation pins via spec_version. A mismatch means someone
    updated one without the other."""
    readme = (FIXTURE_DIR / "README.md").read_text()
    assert f"`{EXPECTED_UPSTREAM_TAG}`" in readme, (
        f"Fixture README does not reference expected upstream tag {EXPECTED_UPSTREAM_TAG!r}. "
        f"Update {FIXTURE_DIR / 'README.md'} to match the pinned spec_version."
    )

    from darnit_baseline.implementation import OSPSBaselineImplementation

    impl = OSPSBaselineImplementation()
    assert impl.spec_version.endswith(EXPECTED_UPSTREAM_TAG), (
        f"Implementation spec_version {impl.spec_version!r} does not end with "
        f"expected upstream tag {EXPECTED_UPSTREAM_TAG!r}. Bump one or the other."
    )


@pytest.mark.unit
def test_darnit_level_tags_match_upstream_applicability() -> None:
    """For each control that exists in BOTH darnit and upstream, darnit's
    `level` tag must equal upstream's lowest maturity level. Darnit-retained
    upstream-retired controls (deprecated=true) are excluded from this
    comparison because upstream no longer has them."""
    upstream = _load_upstream_lowest_levels()
    darnit = _load_darnit_levels(exclude_deprecated=True)

    common = set(upstream) & set(darnit)
    mismatches = [
        (cid, darnit[cid], upstream[cid])
        for cid in sorted(common)
        if darnit[cid] != upstream[cid]
    ]

    only_upstream = sorted(set(upstream) - set(darnit))
    only_darnit = sorted(set(darnit) - set(upstream))

    if mismatches or only_upstream or only_darnit:
        lines = ["Darnit level tags drift from upstream OSPS Baseline:"]
        if mismatches:
            lines.append("  Level mismatches (control: darnit -> upstream_lowest):")
            for cid, dl, ul in mismatches:
                lines.append(f"    {cid}: L{dl} -> L{ul}")
        if only_upstream:
            lines.append("  Controls in upstream but missing in darnit:")
            for cid in only_upstream:
                lines.append(f"    {cid} (upstream lowest = L{upstream[cid]})")
        if only_darnit:
            lines.append("  Controls in darnit but not in upstream (mark as darnit_specific or deprecated):")
            for cid in only_darnit:
                lines.append(f"    {cid} (darnit level = L{darnit[cid]})")
        pytest.fail("\n".join(lines))


@pytest.mark.unit
def test_runtime_per_level_counts_match_documented_values() -> None:
    """User-facing counts: what `darnit audit --level N` will evaluate.
    Includes all controls a user's audit will run against, including any
    darnit-retained upstream-retired ones."""
    darnit = _load_darnit_levels()
    counts = Counter(darnit.values())
    actual = {1: counts[1], 2: counts[2], 3: counts[3]}
    assert actual == EXPECTED_RUNTIME_COUNTS, (
        f"Runtime per-level counts drift from documented values.\n"
        f"  Actual:     {actual}\n"
        f"  Documented: {EXPECTED_RUNTIME_COUNTS}\n"
        f"  Update docs/USAGE_GUIDE.md if the new counts are intentional, "
        f"or reconcile openssf-baseline.toml."
    )


@pytest.mark.unit
def test_upstream_parity_counts_match() -> None:
    """Upstream-parity: darnit's per-level counts (excluding deprecated and
    darnit_specific) equal the vendored upstream's lowest-level counts."""
    upstream = _load_upstream_lowest_levels()
    darnit = _load_darnit_levels(exclude_deprecated=True, exclude_darnit_specific=True)

    up_counts = Counter(upstream.values())
    d_counts = Counter(darnit.values())
    up_actual = {1: up_counts[1], 2: up_counts[2], 3: up_counts[3]}
    d_actual = {1: d_counts[1], 2: d_counts[2], 3: d_counts[3]}

    assert up_actual == EXPECTED_UPSTREAM_COUNTS, (
        f"Vendored upstream v2026.02.19 counts drift from EXPECTED_UPSTREAM_COUNTS.\n"
        f"  From fixture: {up_actual}\n"
        f"  Expected:     {EXPECTED_UPSTREAM_COUNTS}\n"
        f"  Update EXPECTED_UPSTREAM_COUNTS in this test file."
    )
    assert d_actual == EXPECTED_UPSTREAM_COUNTS, (
        f"Darnit's upstream-parity counts drift from expected.\n"
        f"  Darnit (excluding deprecated/darnit_specific): {d_actual}\n"
        f"  Expected (from upstream):                       {EXPECTED_UPSTREAM_COUNTS}\n"
        f"  Reconcile openssf-baseline.toml level tags."
    )
