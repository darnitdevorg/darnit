"""detect_filter evaluation (feature 039, issues #165 and #150).

Covers contracts/detect-filter.md obligations DF-1 through DF-6.
"""

from __future__ import annotations

import pytest

from darnit.context.detect_filter import FilterDecision, apply_filter

KEY = "security_contact"
SHIPPED = "!value.contains('example.com') && !value.contains('example.org')"


class TestScalarCandidates:
    @pytest.mark.unit
    def test_placeholder_is_rejected(self) -> None:
        """DF-1: the case the filter was written for."""
        outcome = apply_filter(SHIPPED, "security@example.com", KEY)
        assert outcome.decision is FilterDecision.REJECT
        assert outcome.value is None
        assert outcome.discarded == ["security@example.com"]

    @pytest.mark.unit
    def test_real_address_is_kept(self) -> None:
        """DF-2."""
        outcome = apply_filter(SHIPPED, "security@real.org", KEY)
        assert outcome.decision is FilterDecision.KEEP
        assert outcome.value == "security@real.org"

    @pytest.mark.unit
    def test_example_org_is_also_rejected(self) -> None:
        assert apply_filter(SHIPPED, "x@example.org", KEY).decision is (FilterDecision.REJECT)

    @pytest.mark.unit
    def test_no_filter_returns_the_candidate_untouched(self) -> None:
        """C-8: a key declaring no filter is not evaluated at all."""
        outcome = apply_filter(None, "security@example.com", KEY)
        assert outcome.decision is FilterDecision.KEEP
        assert outcome.value == "security@example.com"


class TestListCandidates:
    """DF-3 and DF-4. Lists are filtered element-wise and never bound whole."""

    @pytest.mark.unit
    def test_passing_elements_are_kept_and_failures_dropped(self) -> None:
        """DF-3."""
        outcome = apply_filter(SHIPPED, ["a@example.com", "b@real.org"], KEY)
        assert outcome.decision is FilterDecision.KEEP
        assert outcome.value == ["b@real.org"]
        assert outcome.discarded == ["a@example.com"]

    @pytest.mark.unit
    def test_discarded_count_is_reported(self) -> None:
        """FR-013: a list arriving shorter than the evidence must be explicable."""
        outcome = apply_filter(SHIPPED, ["a@example.com", "b@real.org"], KEY)
        assert "1" in outcome.reason

    @pytest.mark.unit
    def test_a_list_of_only_rejects_is_rejected(self) -> None:
        outcome = apply_filter(SHIPPED, ["a@example.com", "b@example.org"], KEY)
        assert outcome.decision is FilterDecision.REJECT
        assert outcome.value is None

    @pytest.mark.unit
    def test_list_containing_a_rejected_element_is_not_kept_whole(self) -> None:
        """DF-4. The load-bearing test of this feature.

        CEL's `contains` on a list is membership, not substring, so
        `["a@example.com"].contains("example.com")` is False and the negated
        filter returns True. Binding a list whole therefore KEEPS a list
        containing the exact value the filter exists to reject -- the same
        failing-open shape as the original bug, reintroduced by its own fix.

        If this test fails, someone has "simplified" element-wise filtering
        into a single whole-list evaluation.
        """
        outcome = apply_filter(SHIPPED, ["a@example.com"], KEY)
        assert outcome.decision is not FilterDecision.KEEP
        assert outcome.value != ["a@example.com"]

    @pytest.mark.unit
    def test_empty_list_is_rejected_rather_than_kept(self) -> None:
        outcome = apply_filter(SHIPPED, [], KEY)
        assert outcome.decision is FilterDecision.REJECT


class TestUnevaluable:
    """DF-5 and DF-6. A filter that cannot judge never returns KEEP.

    Two distinct failure paths: a malformed expression RAISES out of the CEL
    evaluator, while a wrong-typed value RETURNS a failed result. An
    implementation handling only one of them misses the other entirely.
    """

    @pytest.mark.unit
    def test_malformed_expression_does_not_propagate(self) -> None:
        """DF-5: a framework author's typo must not abort context collection."""
        outcome = apply_filter("!value.contains(", "anything", KEY)
        assert outcome.decision is FilterDecision.UNEVALUABLE

    @pytest.mark.unit
    def test_wrong_typed_value_is_unevaluable(self) -> None:
        """DF-6: `value.contains(...)` against an int returns a failed result."""
        outcome = apply_filter(SHIPPED, 42, KEY)
        assert outcome.decision is FilterDecision.UNEVALUABLE
        assert outcome.value is None

    @pytest.mark.unit
    def test_boolean_value_is_unevaluable(self) -> None:
        assert apply_filter(SHIPPED, True, KEY).decision is FilterDecision.UNEVALUABLE

    @pytest.mark.unit
    def test_unevaluable_is_distinct_from_reject(self) -> None:
        """C-2 / FR-008: 'could not judge' and 'judged and said no' are
        different claims, and reporting them identically is the defect this
        feature fixes."""
        rejected = apply_filter(SHIPPED, "a@example.com", KEY)
        unevaluable = apply_filter(SHIPPED, 42, KEY)
        assert rejected.decision is not unevaluable.decision
        assert rejected.reason != unevaluable.reason
