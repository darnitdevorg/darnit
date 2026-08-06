"""Tests for darnit.core.errors (feature 025 T007).

Confirms structured fields survive raise/except round-trips and str() is
informative.
"""

from __future__ import annotations

import pytest

from darnit.core.errors import (
    AuthorityViolation,
    OutOfOrderSubmission,
    ResultSchemaMismatch,
)


class TestOutOfOrderSubmission:
    def test_carries_step_ids(self) -> None:
        with pytest.raises(OutOfOrderSubmission) as excinfo:
            raise OutOfOrderSubmission("expected_step", "submitted_step")
        assert excinfo.value.expected_step_id == "expected_step"
        assert excinfo.value.submitted_step_id == "submitted_step"

    def test_str_names_both_step_ids(self) -> None:
        err = OutOfOrderSubmission("A", "B")
        s = str(err)
        assert "A" in s
        assert "B" in s


class TestResultSchemaMismatch:
    def test_carries_step_id_and_fields(self) -> None:
        with pytest.raises(ResultSchemaMismatch) as excinfo:
            raise ResultSchemaMismatch("step_x", ["missing_field"], "field missing")
        assert excinfo.value.step_id == "step_x"
        assert excinfo.value.offending_fields == ["missing_field"]

    def test_str_names_step_id_and_message(self) -> None:
        err = ResultSchemaMismatch("step_x", ["a", "b"], "bad")
        s = str(err)
        assert "step_x" in s
        assert "bad" in s


class TestAuthorityViolation:
    def test_carries_control_and_step_ids(self) -> None:
        with pytest.raises(AuthorityViolation) as excinfo:
            raise AuthorityViolation("CTRL-01", "step_1", "cannot claim asserted")
        assert excinfo.value.control_id == "CTRL-01"
        assert excinfo.value.step_id == "step_1"

    def test_str_names_control_step_and_message(self) -> None:
        err = AuthorityViolation("CTRL-01", "step_1", "cannot claim asserted")
        s = str(err)
        assert "CTRL-01" in s
        assert "step_1" in s
        assert "cannot claim" in s
