"""Corpus inventory tests (feature 028 T015).

Covers SC-008: the fixture corpus produces at least one control in each
of the four categories: all_pass, all_fail, mixed, pending_llm.

Also guards against accidental fixture deletion (asserts at least four
fixtures are discovered).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from tests.darnit.parity.tier1.fixture_meta import (
    VALID_CATEGORIES,
    load_parity_metadata,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _discover_fixtures() -> list[Path]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir() and (p / ".baseline.toml").exists())


class TestCorpusInventory:
    def test_at_least_four_fixtures_present(self) -> None:
        fixtures = _discover_fixtures()
        assert len(fixtures) >= 4, (
            f"Expected at least 4 fixtures under {FIXTURES_DIR}, got {len(fixtures)}: {[f.name for f in fixtures]}"
        )

    def test_every_category_represented(self) -> None:
        """SC-008: at least one fixture per category, verified via parity.toml."""
        fixtures = _discover_fixtures()

        categories: Counter[str] = Counter()
        for fixture in fixtures:
            meta = load_parity_metadata(fixture)
            if meta is not None:
                categories[meta.category] += 1

        missing = [c for c in VALID_CATEGORIES if categories[c] < 1]
        assert not missing, f"Categories missing from corpus: {missing}. Present: {dict(categories)}"
