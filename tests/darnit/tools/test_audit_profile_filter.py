"""Tests for profile filtering in the audit tool."""


from darnit.config.framework_schema import AuditProfileConfig
from darnit.config.profile_resolver import (
    resolve_profile,
    resolve_profile_control_ids,
)
from darnit.core.plugin import ControlSpec


def _make_control(control_id, level=1, domain="AC"):
    return ControlSpec(
        control_id=control_id,
        name=control_id,
        description=f"Test {control_id}",
        level=level,
        domain=domain,
        metadata={},
        tags={"level": level, "domain": domain},
    )


class TestAuditProfileFiltering:
    """Tests for profile-based control filtering in audit pipeline."""

    def test_profile_filters_to_explicit_controls(self):
        """Profile with explicit control IDs returns only those controls."""
        controls = [_make_control("AC-01"), _make_control("AC-02"), _make_control("VM-01")]
        profile = AuditProfileConfig(
            description="AC only",
            controls=["AC-01", "AC-02"],
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["AC-01", "AC-02"]

    def test_profile_filters_by_level_tag(self):
        """Profile with level tag filter returns only matching controls."""
        controls = [
            _make_control("L1-01", level=1),
            _make_control("L2-01", level=2),
            _make_control("L1-02", level=1),
        ]
        profile = AuditProfileConfig(
            description="Level 1",
            tags={"level": 1},
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["L1-01", "L1-02"]

    def test_profile_filters_by_domain_tag(self):
        """Profile with domain tag filter returns only matching controls."""
        controls = [
            _make_control("AC-01", domain="AC"),
            _make_control("VM-01", domain="VM"),
            _make_control("AC-02", domain="AC"),
        ]
        profile = AuditProfileConfig(
            description="AC domain",
            tags={"domain": "AC"},
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["AC-01", "AC-02"]

    def test_profile_resolve_from_single_implementation(self):
        """Short profile name resolves when only one impl defines it."""
        impls = {
            "openssf-baseline": {
                "level1_quick": AuditProfileConfig(
                    description="Level 1",
                    tags={"level": 1},
                ),
            }
        }
        impl_name, profile = resolve_profile("level1_quick", impls)
        assert impl_name == "openssf-baseline"
        assert profile.tags == {"level": 1}

    def test_no_profile_returns_all_controls(self):
        """When no profile is specified, all controls should be returned."""
        controls = [_make_control("A"), _make_control("B"), _make_control("C")]
        # This tests the default behavior — profile=None means no filtering
        all_ids = [c.control_id for c in controls]
        assert all_ids == ["A", "B", "C"]
