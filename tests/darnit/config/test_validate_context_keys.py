"""The recurrence guard for unwired TOML context keys (feature 039, FR-010).

Covers contracts/detect-filter.md obligation DF-11.

`ContextDefinitionConfig` sets `extra="allow"`, so an undeclared key is
retained and never reported -- a misspelled `detect_fliter` behaves exactly
like the correct spelling: it does nothing. Three instances of that defect are
known, all found after shipping and all by unrelated routes:

  - `detect_filter`      (#165, #150) -- declared, never read
  - `value_if_fail`      (PR #417)    -- declared, never read
  - `presentation_hint`  (this feature) -- declared in TOML, never mapped
                          through; harmless only because a computed fallback
                          derives the same string

This check turns the class into a CI failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _check():
    from validate_sync import validate_context_keys

    return validate_context_keys()


@pytest.mark.unit
def test_shipped_tomls_declare_every_context_key() -> None:
    """DF-11, second half: the current state of the repository passes."""
    result = _check()
    assert result.passed, result.details


@pytest.mark.unit
def test_detect_filter_is_a_declared_field() -> None:
    """The field this feature wired must be declared, not an extra."""
    from darnit.config.framework_schema import ContextDefinitionConfig

    assert "detect_filter" in ContextDefinitionConfig.model_fields


@pytest.mark.unit
def test_an_undeclared_key_would_be_caught(tmp_path: Path, monkeypatch) -> None:
    """DF-11, first half.

    Uses a misspelling of the very field this feature adds, because that is
    the failure this check exists to prevent: `detect_fliter` loads without
    complaint and silently filters nothing.
    """
    import validate_sync

    shipped = tmp_path / "packages" / "fake" / "src" / "fake"
    shipped.mkdir(parents=True)
    (shipped / "fake.toml").write_text(
        "[context.security_contact]\n"
        'type = "string"\n'
        'prompt = "?"\n'
        "detect_fliter = \"!value.contains('example.com')\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(validate_sync, "PROJECT_ROOT", tmp_path)

    result = validate_sync.validate_context_keys()
    assert not result.passed
    assert "detect_fliter" in result.details
    assert "security_contact" in result.details
