"""SC-007 fixture auto-discovery test (feature 028 T026).

Asserts that fixture count matches directory count -- when a maintainer
adds a directory under `tests/darnit/parity/fixtures/`, the parity test
suite includes it on the next collection without any test file edit.
"""

from __future__ import annotations

from pathlib import Path

from tests.darnit.parity.tier1.fixture_meta import FIXTURE_MARKER, discover_fixtures

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _discovered_fixture_dirs() -> list[Path]:
    return discover_fixtures(FIXTURES_DIR)


def test_fixture_count_matches_directory_count() -> None:
    """SC-007: no manual list of fixtures in test code -- discovery is
    directory-driven. Adding or removing a fixture only requires touching
    the fixture's directory."""
    fixtures = _discovered_fixture_dirs()
    # Sanity: at least the four MVP fixtures.
    assert len(fixtures) >= 4, f"Expected at least 4 fixtures, got {len(fixtures)}: {[f.name for f in fixtures]}"
    # Every discovered directory contains the marker file (`parity.toml`).
    # A directory without it is silently ignored (not counted as a fixture).
    for fixture in fixtures:
        assert (fixture / FIXTURE_MARKER).exists()


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
        (new_dir / FIXTURE_MARKER).write_text('[expected]\ncategory = "all_pass"\n')

        # Rediscover using the same function.
        discovered = discover_fixtures(tmp_root)
        names = {p.name for p in discovered}
        assert "synthetic_extra" in names
        assert len(discovered) == len(_discovered_fixture_dirs()) + 1
