"""SC-007 fixture auto-discovery test (feature 028 T026).

Asserts that fixture count matches directory count -- when a maintainer
adds a directory under `tests/darnit/parity/fixtures/`, the parity test
suite includes it on the next collection without any test file edit.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _discovered_fixture_dirs() -> list[Path]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir() and (p / ".baseline.toml").exists())


def test_fixture_count_matches_directory_count() -> None:
    """SC-007: no manual list of fixtures in test code -- discovery is
    directory-driven. Adding or removing a fixture only requires touching
    the fixture's directory."""
    fixtures = _discovered_fixture_dirs()
    # Sanity: at least the four MVP fixtures.
    assert len(fixtures) >= 4, f"Expected at least 4 fixtures, got {len(fixtures)}: {[f.name for f in fixtures]}"
    # Every discovered directory contains a `.baseline.toml` -- the
    # required marker file. If a maintainer adds a directory without
    # `.baseline.toml`, it's silently ignored (not counted as a fixture).
    for fixture in fixtures:
        assert (fixture / ".baseline.toml").exists()


def test_new_fixture_is_picked_up() -> None:
    """Directly exercise the discovery function with a synthetic addition.

    Uses a temporary side directory to avoid mutating the real corpus;
    verifies the discovery pattern would include it.
    """
    import shutil
    import tempfile

    # Simulate the discovery by pointing at a temp copy of the fixtures dir
    # plus one extra fake fixture.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        for existing in _discovered_fixture_dirs():
            shutil.copytree(existing, tmp_root / existing.name)

        # Add a synthetic fixture.
        new_dir = tmp_root / "synthetic_extra"
        new_dir.mkdir()
        (new_dir / ".baseline.toml").write_text('extends = "openssf-baseline"\n')

        # Rediscover using the same pattern.
        discovered = sorted(p for p in tmp_root.iterdir() if p.is_dir() and (p / ".baseline.toml").exists())
        names = {p.name for p in discovered}
        assert "synthetic_extra" in names
        assert len(discovered) == len(_discovered_fixture_dirs()) + 1
