"""Tests for darnit.core.authority (feature 025 T006).

Covers the Literal domain and the is_terminal_authority helper.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from darnit.core.authority import Authority, is_terminal_authority


class TestIsTerminalAuthority:
    def test_dispositive_is_terminal(self) -> None:
        assert is_terminal_authority("dispositive") is True

    def test_asserted_is_terminal(self) -> None:
        assert is_terminal_authority("asserted") is True

    def test_suggestive_is_not_terminal(self) -> None:
        assert is_terminal_authority("suggestive") is False

    def test_none_is_not_terminal(self) -> None:
        # FR-001 safety: authority-less results never conclude.
        assert is_terminal_authority(None) is False

    def test_unknown_string_is_not_terminal(self) -> None:
        # Defensive: an unexpected string (e.g. a schema evolution) does NOT
        # count as terminal. Guards against silent conclusions from junk data.
        assert is_terminal_authority("junk") is False  # type: ignore[arg-type]


class TestAuthorityDomain:
    """Confirms Authority is a strict Literal enforced by Pydantic."""

    def _make_model(self):
        class M(BaseModel):
            a: Authority

        return M

    def test_dispositive_accepted(self) -> None:
        M = self._make_model()
        assert M(a="dispositive").a == "dispositive"

    def test_suggestive_accepted(self) -> None:
        M = self._make_model()
        assert M(a="suggestive").a == "suggestive"

    def test_asserted_accepted(self) -> None:
        M = self._make_model()
        assert M(a="asserted").a == "asserted"

    def test_unknown_value_rejected(self) -> None:
        M = self._make_model()
        with pytest.raises(ValidationError):
            M(a="junk")

    def test_wrong_type_rejected(self) -> None:
        M = self._make_model()
        with pytest.raises(ValidationError):
            M(a=1)  # type: ignore[arg-type]
