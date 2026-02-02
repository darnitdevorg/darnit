"""Tests for CLI filter parsing and matching."""

from dataclasses import dataclass
from typing import Any

import pytest

from darnit.filtering import (
    ControlFilter,
    compare,
    filter_controls,
    matches_filter,
    matches_filters,
    parse_filter,
    parse_tags_arg,
    parse_value,
)

# =============================================================================
# Mock Control for Testing
# =============================================================================


@dataclass
class MockControl:
    """Mock control for testing filters."""

    control_id: str
    level: int
    domain: str | None = None
    name: str = "Test Control"
    metadata: dict[str, Any] = None
    check_adapter: str = "builtin"

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        # Extract domain from control_id if not set
        if self.domain is None and self.control_id:
            parts = self.control_id.split("-")
            if len(parts) >= 2:
                self.domain = parts[1]


# =============================================================================
# Test parse_value
# =============================================================================


class TestParseValue:
    """Tests for parse_value function."""

    def test_parse_integer(self):
        """Test parsing integer values."""
        assert parse_value("1") == 1
        assert parse_value("42") == 42
        assert parse_value("0") == 0
        assert parse_value("-5") == -5

    def test_parse_float(self):
        """Test parsing float values."""
        assert parse_value("1.5") == 1.5
        assert parse_value("7.0") == 7.0
        assert parse_value("0.5") == 0.5
        assert parse_value("-2.5") == -2.5

    def test_parse_string(self):
        """Test parsing string values."""
        assert parse_value("VM") == "VM"
        assert parse_value("security") == "security"
        assert parse_value("ci-cd") == "ci-cd"

    def test_parse_with_whitespace(self):
        """Test parsing values with whitespace."""
        assert parse_value("  1  ") == 1
        assert parse_value("  VM  ") == "VM"


# =============================================================================
# Test parse_filter
# =============================================================================


class TestParseFilter:
    """Tests for parse_filter function."""

    def test_parse_equals(self):
        """Test parsing equals filters."""
        f = parse_filter("level=1")
        assert f.field == "level"
        assert f.operator == "="
        assert f.value == 1

        f = parse_filter("domain=VM")
        assert f.field == "domain"
        assert f.operator == "="
        assert f.value == "VM"

    def test_parse_less_than_or_equal(self):
        """Test parsing <= filters."""
        f = parse_filter("level<=2")
        assert f.field == "level"
        assert f.operator == "<="
        assert f.value == 2

    def test_parse_greater_than_or_equal(self):
        """Test parsing >= filters."""
        f = parse_filter("severity>=7.0")
        assert f.field == "severity"
        assert f.operator == ">="
        assert f.value == 7.0

    def test_parse_not_equal(self):
        """Test parsing != filters."""
        f = parse_filter("domain!=BR")
        assert f.field == "domain"
        assert f.operator == "!="
        assert f.value == "BR"

    def test_parse_less_than(self):
        """Test parsing < filters."""
        f = parse_filter("level<3")
        assert f.field == "level"
        assert f.operator == "<"
        assert f.value == 3

    def test_parse_greater_than(self):
        """Test parsing > filters."""
        f = parse_filter("severity>5")
        assert f.field == "severity"
        assert f.operator == ">"
        assert f.value == 5

    def test_parse_bare_tag(self):
        """Test parsing bare tag filters."""
        f = parse_filter("security")
        assert f.field == "tags"
        assert f.operator == "in"
        assert f.value == "security"

        f = parse_filter("ci-cd")
        assert f.field == "tags"
        assert f.operator == "in"
        assert f.value == "ci-cd"

    def test_parse_with_whitespace(self):
        """Test parsing filters with whitespace."""
        f = parse_filter("  level = 1  ")
        assert f.field == "level"
        assert f.operator == "="
        assert f.value == 1


# =============================================================================
# Test parse_tags_arg
# =============================================================================


class TestParseTagsArg:
    """Tests for parse_tags_arg function."""

    def test_parse_single_filter(self):
        """Test parsing a single filter."""
        filters = parse_tags_arg(["level=1"])
        assert len(filters) == 1
        assert filters[0].field == "level"
        assert filters[0].value == 1

    def test_parse_multiple_filters(self):
        """Test parsing multiple --tags arguments."""
        filters = parse_tags_arg(["level=1", "domain=VM"])
        assert len(filters) == 2
        assert filters[0].field == "level"
        assert filters[1].field == "domain"

    def test_parse_comma_separated(self):
        """Test parsing comma-separated filters in single arg."""
        filters = parse_tags_arg(["level=1,domain=VM,security"])
        assert len(filters) == 3
        assert filters[0].field == "level"
        assert filters[1].field == "domain"
        assert filters[2].field == "tags"
        assert filters[2].value == "security"

    def test_parse_mixed(self):
        """Test parsing mixed filters."""
        filters = parse_tags_arg(["level<=2", "security,ci-cd"])
        assert len(filters) == 3
        assert filters[0].operator == "<="
        assert filters[1].value == "security"
        assert filters[2].value == "ci-cd"

    def test_parse_empty(self):
        """Test parsing empty input."""
        assert parse_tags_arg(None) == []
        assert parse_tags_arg([]) == []

    def test_parse_with_empty_parts(self):
        """Test handling empty parts in comma-separated list."""
        filters = parse_tags_arg(["level=1,,domain=VM"])
        assert len(filters) == 2


# =============================================================================
# Test compare
# =============================================================================


class TestCompare:
    """Tests for compare function."""

    def test_equals(self):
        """Test equals comparison."""
        assert compare(1, "=", 1) is True
        assert compare(1, "=", 2) is False
        assert compare("VM", "=", "VM") is True
        assert compare("VM", "=", "AC") is False

    def test_not_equals(self):
        """Test not equals comparison."""
        assert compare(1, "!=", 2) is True
        assert compare(1, "!=", 1) is False

    def test_less_than_or_equal(self):
        """Test <= comparison."""
        assert compare(1, "<=", 2) is True
        assert compare(2, "<=", 2) is True
        assert compare(3, "<=", 2) is False

    def test_greater_than_or_equal(self):
        """Test >= comparison."""
        assert compare(3, ">=", 2) is True
        assert compare(2, ">=", 2) is True
        assert compare(1, ">=", 2) is False

    def test_less_than(self):
        """Test < comparison."""
        assert compare(1, "<", 2) is True
        assert compare(2, "<", 2) is False

    def test_greater_than(self):
        """Test > comparison."""
        assert compare(3, ">", 2) is True
        assert compare(2, ">", 2) is False

    def test_none_value(self):
        """Test comparison with None."""
        assert compare(None, "=", 1) is False
        assert compare(None, "<=", 1) is False


# =============================================================================
# Test matches_filter
# =============================================================================


class TestMatchesFilter:
    """Tests for matches_filter function."""

    def test_match_level_equals(self):
        """Test matching level with equals."""
        control = MockControl(control_id="OSPS-AC-01.01", level=1)
        f = ControlFilter(field="level", operator="=", value=1)
        assert matches_filter(control, f) is True

        f = ControlFilter(field="level", operator="=", value=2)
        assert matches_filter(control, f) is False

    def test_match_level_less_than_or_equal(self):
        """Test matching level with <=."""
        control = MockControl(control_id="OSPS-AC-01.01", level=2)

        f = ControlFilter(field="level", operator="<=", value=2)
        assert matches_filter(control, f) is True

        f = ControlFilter(field="level", operator="<=", value=3)
        assert matches_filter(control, f) is True

        f = ControlFilter(field="level", operator="<=", value=1)
        assert matches_filter(control, f) is False

    def test_match_domain(self):
        """Test matching domain."""
        control = MockControl(control_id="OSPS-VM-01.01", level=1)

        f = ControlFilter(field="domain", operator="=", value="VM")
        assert matches_filter(control, f) is True

        f = ControlFilter(field="domain", operator="=", value="AC")
        assert matches_filter(control, f) is False

        f = ControlFilter(field="domain", operator="!=", value="AC")
        assert matches_filter(control, f) is True

    def test_match_tags(self):
        """Test matching tags."""
        control = MockControl(
            control_id="OSPS-AC-01.01",
            level=1,
            metadata={"tags": ["security", "ci-cd"]},
        )

        f = ControlFilter(field="tags", operator="in", value="security")
        assert matches_filter(control, f) is True

        f = ControlFilter(field="tags", operator="in", value="documentation")
        assert matches_filter(control, f) is False

    def test_match_severity(self):
        """Test matching severity."""
        control = MockControl(
            control_id="OSPS-AC-01.01",
            level=1,
            metadata={"security_severity": 7.5},
        )

        f = ControlFilter(field="severity", operator=">=", value=7.0)
        assert matches_filter(control, f) is True

        f = ControlFilter(field="severity", operator=">=", value=8.0)
        assert matches_filter(control, f) is False

    def test_match_adapter(self):
        """Test matching adapter."""
        control = MockControl(
            control_id="OSPS-AC-01.01",
            level=1,
            check_adapter="scorecard",
        )

        f = ControlFilter(field="adapter", operator="=", value="scorecard")
        assert matches_filter(control, f) is True

        f = ControlFilter(field="adapter", operator="=", value="builtin")
        assert matches_filter(control, f) is False

    def test_unknown_field(self):
        """Test unknown field excludes control (tag doesn't exist)."""
        control = MockControl(control_id="OSPS-AC-01.01", level=1)
        f = ControlFilter(field="unknown", operator="=", value="test")
        # Control doesn't have 'unknown' tag, so it should be excluded
        assert matches_filter(control, f) is False


# =============================================================================
# Test matches_filters
# =============================================================================


class TestMatchesFilters:
    """Tests for matches_filters function."""

    def test_empty_filters(self):
        """Test empty filters matches everything."""
        control = MockControl(control_id="OSPS-AC-01.01", level=1)
        assert matches_filters(control, []) is True

    def test_single_filter(self):
        """Test single filter matching."""
        control = MockControl(control_id="OSPS-AC-01.01", level=1)
        filters = [ControlFilter(field="level", operator="=", value=1)]
        assert matches_filters(control, filters) is True

    def test_multiple_filters_all_match(self):
        """Test AND logic - all filters must match."""
        control = MockControl(
            control_id="OSPS-VM-01.01",
            level=1,
            metadata={"tags": ["security"]},
        )
        filters = [
            ControlFilter(field="level", operator="<=", value=2),
            ControlFilter(field="domain", operator="=", value="VM"),
            ControlFilter(field="tags", operator="in", value="security"),
        ]
        assert matches_filters(control, filters) is True

    def test_multiple_filters_one_fails(self):
        """Test AND logic - one failure means no match."""
        control = MockControl(control_id="OSPS-VM-01.01", level=3)
        filters = [
            ControlFilter(field="level", operator="<=", value=2),
            ControlFilter(field="domain", operator="=", value="VM"),
        ]
        assert matches_filters(control, filters) is False

    def test_same_field_or_logic_matches(self):
        """Test OR logic for same field - level=1 OR level=2."""
        control = MockControl(control_id="OSPS-AC-01.01", level=1)
        filters = [
            ControlFilter(field="level", operator="=", value=1),
            ControlFilter(field="level", operator="=", value=2),
        ]
        # level=1 OR level=2 should match a level=1 control
        assert matches_filters(control, filters) is True

    def test_same_field_or_logic_no_match(self):
        """Test OR logic for same field - none match."""
        control = MockControl(control_id="OSPS-AC-01.01", level=3)
        filters = [
            ControlFilter(field="level", operator="=", value=1),
            ControlFilter(field="level", operator="=", value=2),
        ]
        # level=1 OR level=2 should NOT match a level=3 control
        assert matches_filters(control, filters) is False

    def test_mixed_and_or_logic(self):
        """Test combined AND (between fields) and OR (within field) logic."""
        control = MockControl(control_id="OSPS-AC-01.01", level=1)
        filters = [
            ControlFilter(field="level", operator="=", value=1),
            ControlFilter(field="level", operator="=", value=2),
            ControlFilter(field="domain", operator="=", value="AC"),
        ]
        # (level=1 OR level=2) AND domain=AC should match
        assert matches_filters(control, filters) is True

    def test_mixed_and_or_logic_domain_fails(self):
        """Test combined logic where AND condition fails."""
        control = MockControl(control_id="OSPS-AC-01.01", level=1)
        filters = [
            ControlFilter(field="level", operator="=", value=1),
            ControlFilter(field="level", operator="=", value=2),
            ControlFilter(field="domain", operator="=", value="VM"),  # AC != VM
        ]
        # (level=1 OR level=2) AND domain=VM should NOT match (domain fails)
        assert matches_filters(control, filters) is False


# =============================================================================
# Test filter_controls
# =============================================================================


class TestFilterControls:
    """Tests for filter_controls function."""

    @pytest.fixture
    def controls(self):
        """Create test controls."""
        return [
            MockControl(
                control_id="OSPS-AC-01.01",
                level=1,
                metadata={"tags": ["security"]},
            ),
            MockControl(
                control_id="OSPS-AC-02.01",
                level=2,
                metadata={"tags": ["security", "ci-cd"]},
            ),
            MockControl(
                control_id="OSPS-VM-01.01",
                level=1,
                metadata={"tags": ["documentation"]},
            ),
            MockControl(
                control_id="OSPS-VM-02.01",
                level=3,
                metadata={"tags": ["security"]},
            ),
        ]

    def test_no_filters(self, controls):
        """Test no filters returns all controls."""
        result = filter_controls(controls)
        assert len(result) == 4

    def test_filter_by_level(self, controls):
        """Test filtering by level."""
        filters = [ControlFilter(field="level", operator="<=", value=1)]
        result = filter_controls(controls, filters=filters)
        assert len(result) == 2
        assert all(c.level == 1 for c in result)

    def test_filter_by_domain(self, controls):
        """Test filtering by domain."""
        filters = [ControlFilter(field="domain", operator="=", value="AC")]
        result = filter_controls(controls, filters=filters)
        assert len(result) == 2
        assert all("AC" in c.control_id for c in result)

    def test_filter_by_tag(self, controls):
        """Test filtering by tag."""
        filters = [ControlFilter(field="tags", operator="in", value="security")]
        result = filter_controls(controls, filters=filters)
        assert len(result) == 3

    def test_include_ids(self, controls):
        """Test include IDs."""
        result = filter_controls(
            controls,
            include_ids={"OSPS-AC-01.01", "OSPS-VM-01.01"},
        )
        assert len(result) == 2
        assert {c.control_id for c in result} == {"OSPS-AC-01.01", "OSPS-VM-01.01"}

    def test_exclude_ids(self, controls):
        """Test exclude IDs."""
        result = filter_controls(
            controls,
            exclude_ids={"OSPS-AC-01.01"},
        )
        assert len(result) == 3
        assert "OSPS-AC-01.01" not in {c.control_id for c in result}

    def test_combined_filters(self, controls):
        """Test combined filtering."""
        filters = [
            ControlFilter(field="level", operator="<=", value=2),
            ControlFilter(field="tags", operator="in", value="security"),
        ]
        result = filter_controls(
            controls,
            filters=filters,
            exclude_ids={"OSPS-AC-01.01"},
        )
        # Level <= 2, has 'security' tag, not OSPS-AC-01.01
        assert len(result) == 1
        assert result[0].control_id == "OSPS-AC-02.01"

    def test_empty_controls(self):
        """Test empty controls list."""
        result = filter_controls([])
        assert result == []


# =============================================================================
# Integration Tests
# =============================================================================


class TestFilterIntegration:
    """Integration tests for the complete filtering workflow."""

    def test_cli_style_filtering(self):
        """Test filtering as it would be used from CLI."""
        controls = [
            MockControl("OSPS-AC-01.01", level=1, metadata={"tags": ["security"]}),
            MockControl("OSPS-AC-02.01", level=2, metadata={"tags": ["ci-cd"]}),
            MockControl("OSPS-VM-01.01", level=1, metadata={"tags": ["security"]}),
            MockControl("OSPS-BR-01.01", level=3, metadata={"tags": []}),
        ]

        # Simulate: darnit audit --tags level<=2,domain=AC --exclude OSPS-AC-01.01
        tags_args = ["level<=2,domain=AC"]
        filters = parse_tags_arg(tags_args)
        exclude_ids = {"OSPS-AC-01.01"}

        result = filter_controls(controls, filters=filters, exclude_ids=exclude_ids)

        assert len(result) == 1
        assert result[0].control_id == "OSPS-AC-02.01"

    def test_tag_only_filtering(self):
        """Test filtering by tag only."""
        controls = [
            MockControl("OSPS-AC-01.01", level=1, metadata={"tags": ["security"]}),
            MockControl("OSPS-AC-02.01", level=2, metadata={"tags": ["ci-cd"]}),
            MockControl("OSPS-VM-01.01", level=1, metadata={"tags": ["security"]}),
        ]

        # Simulate: darnit audit --tags security
        filters = parse_tags_arg(["security"])
        result = filter_controls(controls, filters=filters)

        assert len(result) == 2
        assert all("security" in c.metadata.get("tags", []) for c in result)

    def test_level_shorthand(self):
        """Test --level shorthand behavior."""
        controls = [
            MockControl("OSPS-AC-01.01", level=1),
            MockControl("OSPS-AC-02.01", level=2),
            MockControl("OSPS-VM-01.01", level=3),
        ]

        # Simulate: darnit audit --level 2 (equivalent to --tags level<=2)
        filters = [ControlFilter(field="level", operator="<=", value=2)]
        result = filter_controls(controls, filters=filters)

        assert len(result) == 2
        assert all(c.level <= 2 for c in result)


# =============================================================================
# Tests for Tags Dict Filtering
# =============================================================================


@dataclass
class MockControlWithTags:
    """Mock control with tags dict for testing arbitrary tag filtering."""

    control_id: str
    level: int
    domain: str
    name: str = "Test Control"
    tags: dict[str, Any] = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = {}
        if self.metadata is None:
            self.metadata = {}
        # Copy level and domain to tags (mimics ControlSpec.__post_init__)
        if self.level is not None:
            self.tags["level"] = self.level
        if self.domain is not None:
            self.tags["domain"] = self.domain


class TestTagsDictFiltering:
    """Tests for filtering on arbitrary tags via the tags dict."""

    def test_filter_on_level_via_tags_dict(self):
        """Test that level filtering works via tags dict."""
        control = MockControlWithTags(
            control_id="TEST-01", level=2, domain="AC"
        )

        f = ControlFilter(field="level", operator="<=", value=2)
        assert matches_filter(control, f) is True

        f = ControlFilter(field="level", operator="=", value=1)
        assert matches_filter(control, f) is False

    def test_filter_on_domain_via_tags_dict(self):
        """Test that domain filtering works via tags dict."""
        control = MockControlWithTags(
            control_id="TEST-01", level=1, domain="VM"
        )

        f = ControlFilter(field="domain", operator="=", value="VM")
        assert matches_filter(control, f) is True

        f = ControlFilter(field="domain", operator="=", value="AC")
        assert matches_filter(control, f) is False

    def test_filter_on_custom_tag_key(self):
        """Test filtering on custom tag keys in tags dict."""
        control = MockControlWithTags(
            control_id="TEST-01",
            level=1,
            domain="AC",
            tags={"category": "authentication", "priority": 1},
        )

        # Filter on category
        f = ControlFilter(field="category", operator="=", value="authentication")
        assert matches_filter(control, f) is True

        f = ControlFilter(field="category", operator="=", value="authorization")
        assert matches_filter(control, f) is False

        # Filter on priority
        f = ControlFilter(field="priority", operator=">=", value=1)
        assert matches_filter(control, f) is True

        f = ControlFilter(field="priority", operator=">", value=1)
        assert matches_filter(control, f) is False

    def test_filter_on_numeric_tag_value(self):
        """Test filtering numeric values in tags dict."""
        control = MockControlWithTags(
            control_id="TEST-01",
            level=1,
            domain="AC",
            tags={"score": 7.5},
        )

        f = ControlFilter(field="score", operator=">=", value=7.0)
        assert matches_filter(control, f) is True

        f = ControlFilter(field="score", operator=">=", value=8.0)
        assert matches_filter(control, f) is False

    def test_unknown_tag_key_excludes_control(self):
        """Test that unknown tag keys exclude the control."""
        control = MockControlWithTags(
            control_id="TEST-01", level=1, domain="AC"
        )

        # Control doesn't have 'nonexistent' tag, so it should be excluded
        f = ControlFilter(field="nonexistent", operator="=", value="test")
        assert matches_filter(control, f) is False

    def test_combined_tag_and_level_filtering(self):
        """Test combining tag and level filtering."""
        controls = [
            MockControlWithTags(
                control_id="TEST-01", level=1, domain="AC",
                tags={"category": "auth"},
            ),
            MockControlWithTags(
                control_id="TEST-02", level=2, domain="AC",
                tags={"category": "auth"},
            ),
            MockControlWithTags(
                control_id="TEST-03", level=1, domain="VM",
                tags={"category": "docs"},
            ),
        ]

        # Filter: level <= 1 AND category = auth
        filters = [
            ControlFilter(field="level", operator="<=", value=1),
            ControlFilter(field="category", operator="=", value="auth"),
        ]
        result = filter_controls(controls, filters=filters)

        assert len(result) == 1
        assert result[0].control_id == "TEST-01"
