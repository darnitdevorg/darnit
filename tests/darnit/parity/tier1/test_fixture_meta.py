"""Tests for parity.toml parser (feature 028 T007).

Covers contract parity-toml-schema.md rules PT-2..PT-14.
"""

from __future__ import annotations

import pytest

from tests.darnit.parity.tier1.fixture_meta import (
    ExpectedControl,
    load_parity_metadata,
)


class TestBasicShape:
    def test_absent_parity_toml_returns_none(self, tmp_path):
        """PT-2: absent file -> None (not an error)."""
        assert load_parity_metadata(tmp_path) is None

    def test_valid_minimal_parity_toml(self, tmp_path):
        (tmp_path / "parity.toml").write_text(
            '[expected]\ncategory = "all_pass"\n',
        )
        meta = load_parity_metadata(tmp_path)
        assert meta is not None
        assert meta.category == "all_pass"
        assert meta.has_pending_llm is False  # derived from empty counts
        assert meta.strict is False
        assert meta.counts == {}

    def test_valid_full_parity_toml(self, tmp_path):
        (tmp_path / "parity.toml").write_text(
            "[expected]\n"
            'category = "mixed"\n'
            "has_pending_llm = true\n"
            "strict = true\n"
            "\n"
            "[expected.counts]\n"
            "pass = 4\n"
            "fail = 2\n"
            "warn = 1\n"
            "error = 0\n"
            "n_a = 3\n"
            "pending_llm = 1\n"
            "\n"
            "[[expected.controls]]\n"
            'id = "OSPS-GV-01.01"\n'
            'status = "PASS"\n',
        )
        meta = load_parity_metadata(tmp_path)
        assert meta is not None
        assert meta.category == "mixed"
        assert meta.has_pending_llm is True
        assert meta.strict is True
        assert meta.counts == {
            "pass": 4,
            "fail": 2,
            "warn": 1,
            "error": 0,
            "n_a": 3,
            "pending_llm": 1,
        }
        assert meta.controls == (ExpectedControl(id="OSPS-GV-01.01", status="PASS"),)


class TestValidationFailures:
    def test_malformed_toml_raises(self, tmp_path):
        """PT-4: malformed TOML -> ValueError."""
        (tmp_path / "parity.toml").write_text("this is not valid toml [")
        with pytest.raises(ValueError, match="malformed parity.toml"):
            load_parity_metadata(tmp_path)

    def test_unknown_category_rejected(self, tmp_path):
        """PT-5: category must be one of the four literals."""
        (tmp_path / "parity.toml").write_text(
            '[expected]\ncategory = "unknown"\n',
        )
        with pytest.raises(ValueError, match="category.*must be one of"):
            load_parity_metadata(tmp_path)

    def test_has_pending_llm_disagreement_rejected(self, tmp_path):
        """PT-6: has_pending_llm=true with counts.pending_llm=0 fails."""
        (tmp_path / "parity.toml").write_text(
            '[expected]\ncategory = "mixed"\nhas_pending_llm = true\n\n[expected.counts]\npending_llm = 0\n',
        )
        with pytest.raises(ValueError, match="disagrees with counts"):
            load_parity_metadata(tmp_path)

    def test_negative_count_rejected(self, tmp_path):
        """PT-8: counts must be non-negative."""
        (tmp_path / "parity.toml").write_text(
            '[expected]\ncategory = "mixed"\n[expected.counts]\npass = -1\n',
        )
        with pytest.raises(ValueError, match="non-negative integer"):
            load_parity_metadata(tmp_path)

    def test_missing_expected_section_rejected(self, tmp_path):
        """A parity.toml without [expected] is a schema error."""
        (tmp_path / "parity.toml").write_text("# no expected block\n")
        with pytest.raises(ValueError, match="missing.*expected"):
            load_parity_metadata(tmp_path)


class TestForwardCompatibility:
    def test_unknown_key_warns_but_does_not_fail(self, tmp_path):
        """PT-9: unknown [expected] keys warn but don't fail."""
        (tmp_path / "parity.toml").write_text(
            '[expected]\ncategory = "all_pass"\nfuture_field = "someday"\n',
        )
        with pytest.warns(UserWarning, match="unknown.*future_field"):
            meta = load_parity_metadata(tmp_path)
        assert meta is not None
        assert meta.category == "all_pass"

    def test_unknown_counts_key_warns_but_does_not_fail(self, tmp_path):
        (tmp_path / "parity.toml").write_text(
            '[expected]\ncategory = "mixed"\n[expected.counts]\npass = 1\nfuture_status = 5\n',
        )
        with pytest.warns(UserWarning, match="unknown counts key.*future_status"):
            meta = load_parity_metadata(tmp_path)
        assert meta is not None
        assert meta.counts == {"pass": 1}  # unknown key skipped


class TestDerivedFields:
    def test_has_pending_llm_derived_when_absent(self, tmp_path):
        """When has_pending_llm is not set, derive from counts.pending_llm > 0."""
        (tmp_path / "parity.toml").write_text(
            '[expected]\ncategory = "pending_llm"\n[expected.counts]\npending_llm = 2\n',
        )
        meta = load_parity_metadata(tmp_path)
        assert meta is not None
        assert meta.has_pending_llm is True
