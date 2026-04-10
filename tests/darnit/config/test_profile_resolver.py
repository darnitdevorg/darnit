"""Tests for profile_resolver module.

Tests for darnit.config.profile_resolver - resolving profile names
and filtering controls by profile definitions.
"""

import pytest

from darnit.config.framework_schema import AuditProfileConfig
from darnit.config.profile_resolver import (
    ProfileAmbiguousError,
    ProfileNotFoundError,
    _matches_tags,
    resolve_profile,
    resolve_profile_control_ids,
)
from darnit.core.plugin import ControlSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(controls=None, tags=None, description="Test profile"):
    """Create an AuditProfileConfig with at least one of controls or tags."""
    return AuditProfileConfig(
        description=description,
        controls=controls or [],
        tags=tags or ({"level": 1} if not controls else {}),
    )


def _make_control(control_id, level=1, domain="AC", tags=None):
    extra_tags = tags or {}
    return ControlSpec(
        control_id=control_id,
        name=control_id,
        description=f"Description for {control_id}",
        level=level,
        domain=domain,
        metadata={},
        tags={**extra_tags},
    )


# ---------------------------------------------------------------------------
# resolve_profile
# ---------------------------------------------------------------------------


class TestResolveProfile:
    def test_resolves_short_name(self):
        profile = _make_profile(controls=["CTRL-01"])
        implementations = {"my-impl": {"onboard": profile}}

        impl_name, resolved = resolve_profile("onboard", implementations)

        assert impl_name == "my-impl"
        assert resolved is profile

    def test_resolves_qualified_name(self):
        profile = _make_profile(controls=["CTRL-01"])
        implementations = {
            "impl-a": {"onboard": profile},
            "impl-b": {"onboard": _make_profile(controls=["CTRL-02"])},
        }

        impl_name, resolved = resolve_profile("impl-a:onboard", implementations)

        assert impl_name == "impl-a"
        assert resolved is profile

    def test_raises_not_found_for_unknown_short_name(self):
        implementations = {"my-impl": {"onboard": _make_profile(controls=["CTRL-01"])}}

        with pytest.raises(ProfileNotFoundError) as exc_info:
            resolve_profile("unknown", implementations)

        assert "unknown" in str(exc_info.value)

    def test_raises_not_found_for_unknown_qualified_name(self):
        implementations = {"my-impl": {"onboard": _make_profile(controls=["CTRL-01"])}}

        with pytest.raises(ProfileNotFoundError):
            resolve_profile("my-impl:nonexistent", implementations)

    def test_raises_not_found_for_unknown_impl_in_qualified_name(self):
        implementations = {"my-impl": {"onboard": _make_profile(controls=["CTRL-01"])}}

        with pytest.raises(ProfileNotFoundError):
            resolve_profile("other-impl:onboard", implementations)

    def test_raises_ambiguous_when_multiple_impls_define_same_profile(self):
        profile_a = _make_profile(controls=["CTRL-01"])
        profile_b = _make_profile(controls=["CTRL-02"])
        implementations = {
            "impl-a": {"onboard": profile_a},
            "impl-b": {"onboard": profile_b},
        }

        with pytest.raises(ProfileAmbiguousError) as exc_info:
            resolve_profile("onboard", implementations)

        assert "impl-a" in str(exc_info.value) or "impl-b" in str(exc_info.value)

    def test_error_message_lists_available_profiles(self):
        implementations = {"my-impl": {"onboard": _make_profile(controls=["CTRL-01"])}}

        with pytest.raises(ProfileNotFoundError) as exc_info:
            resolve_profile("missing", implementations)

        assert "onboard" in str(exc_info.value)

    def test_handles_empty_implementations(self):
        with pytest.raises(ProfileNotFoundError):
            resolve_profile("anything", {})


# ---------------------------------------------------------------------------
# resolve_profile_control_ids
# ---------------------------------------------------------------------------


class TestResolveProfileControlIds:
    def test_explicit_controls_included(self):
        controls = [_make_control("CTRL-01"), _make_control("CTRL-02")]
        profile = _make_profile(controls=["CTRL-01"])

        result = resolve_profile_control_ids(profile, controls)

        assert "CTRL-01" in result
        assert "CTRL-02" not in result

    def test_unknown_explicit_control_skipped(self):
        controls = [_make_control("CTRL-01")]
        profile = _make_profile(controls=["CTRL-99"])

        result = resolve_profile_control_ids(profile, controls)

        assert result == []

    def test_tag_filter_level(self):
        controls = [
            _make_control("L1-01", level=1),
            _make_control("L2-01", level=2),
        ]
        profile = _make_profile(tags={"level": 1})

        result = resolve_profile_control_ids(profile, controls)

        assert "L1-01" in result
        assert "L2-01" not in result

    def test_tag_filter_domain(self):
        controls = [
            _make_control("AC-01", domain="AC"),
            _make_control("VM-01", domain="VM"),
        ]
        profile = _make_profile(tags={"domain": "AC"})

        result = resolve_profile_control_ids(profile, controls)

        assert "AC-01" in result
        assert "VM-01" not in result

    def test_tag_gte_filter(self):
        controls = [
            ControlSpec("HIGH-01", "High", "desc", 3, "AC", {}, tags={"severity": 8}),
            ControlSpec("LOW-01", "Low", "desc", 1, "AC", {}, tags={"severity": 3}),
        ]
        profile = AuditProfileConfig(
            description="High severity",
            tags={"severity_gte": 7},
        )

        result = resolve_profile_control_ids(profile, controls)

        assert "HIGH-01" in result
        assert "LOW-01" not in result

    def test_tag_lte_filter(self):
        controls = [
            ControlSpec("HIGH-01", "High", "desc", 3, "AC", {}, tags={"severity": 8}),
            ControlSpec("LOW-01", "Low", "desc", 1, "AC", {}, tags={"severity": 3}),
        ]
        profile = AuditProfileConfig(
            description="Low severity",
            tags={"severity_lte": 5},
        )

        result = resolve_profile_control_ids(profile, controls)

        assert "LOW-01" in result
        assert "HIGH-01" not in result

    def test_union_of_controls_and_tags(self):
        controls = [
            _make_control("CTRL-01", level=1),
            _make_control("CTRL-02", level=2),
            _make_control("CTRL-03", level=1),
        ]
        # Explicit: CTRL-02; tags level=1: CTRL-01 and CTRL-03
        profile = AuditProfileConfig(
            description="Union test",
            controls=["CTRL-02"],
            tags={"level": 1},
        )

        result = resolve_profile_control_ids(profile, controls)

        assert "CTRL-01" in result
        assert "CTRL-02" in result
        assert "CTRL-03" in result

    def test_result_is_sorted(self):
        controls = [
            _make_control("CTRL-B", level=1),
            _make_control("CTRL-A", level=1),
        ]
        profile = _make_profile(tags={"level": 1})

        result = resolve_profile_control_ids(profile, controls)

        assert result == sorted(result)

    def test_empty_controls_list_returns_empty(self):
        profile = _make_profile(controls=["CTRL-01"])

        result = resolve_profile_control_ids(profile, [])

        assert result == []


# ---------------------------------------------------------------------------
# _matches_tags
# ---------------------------------------------------------------------------


class TestMatchesTags:
    def test_exact_match_passes(self):
        control = _make_control("C-01", level=1, domain="AC")

        assert _matches_tags(control, {"level": 1}) is True

    def test_exact_match_fails_wrong_value(self):
        control = _make_control("C-01", level=1)

        assert _matches_tags(control, {"level": 2}) is False

    def test_missing_tag_fails(self):
        control = _make_control("C-01")

        assert _matches_tags(control, {"nonexistent": "value"}) is False

    def test_gte_passes_when_equal(self):
        control = ControlSpec("C-01", "C", "d", 1, "AC", {}, tags={"score": 7})

        assert _matches_tags(control, {"score_gte": 7}) is True

    def test_gte_passes_when_greater(self):
        control = ControlSpec("C-01", "C", "d", 1, "AC", {}, tags={"score": 9})

        assert _matches_tags(control, {"score_gte": 7}) is True

    def test_gte_fails_when_less(self):
        control = ControlSpec("C-01", "C", "d", 1, "AC", {}, tags={"score": 5})

        assert _matches_tags(control, {"score_gte": 7}) is False

    def test_gte_fails_when_tag_missing(self):
        control = _make_control("C-01")

        assert _matches_tags(control, {"score_gte": 7}) is False

    def test_lte_passes_when_equal(self):
        control = ControlSpec("C-01", "C", "d", 1, "AC", {}, tags={"score": 5})

        assert _matches_tags(control, {"score_lte": 5}) is True

    def test_lte_passes_when_less(self):
        control = ControlSpec("C-01", "C", "d", 1, "AC", {}, tags={"score": 3})

        assert _matches_tags(control, {"score_lte": 5}) is True

    def test_lte_fails_when_greater(self):
        control = ControlSpec("C-01", "C", "d", 1, "AC", {}, tags={"score": 8})

        assert _matches_tags(control, {"score_lte": 5}) is False

    def test_multiple_tags_all_must_match(self):
        control = _make_control("C-01", level=1, domain="AC")

        assert _matches_tags(control, {"level": 1, "domain": "AC"}) is True
        assert _matches_tags(control, {"level": 1, "domain": "VM"}) is False

    def test_empty_tags_always_matches(self):
        control = _make_control("C-01")

        assert _matches_tags(control, {}) is True
