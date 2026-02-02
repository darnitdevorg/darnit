"""Tests for the tool output normalizer."""


from darnit.config.framework_schema import OutputMapping
from darnit.locate import (
    CheckOutput,
    FoundEvidence,
    extract_jsonpath,
    normalize_scorecard_output,
    normalize_tool_output,
)


class TestExtractJsonpath:
    """Tests for extract_jsonpath()."""

    def test_simple_field_access(self):
        """Test extracting a simple field."""
        data = {"name": "test", "value": 42}
        assert extract_jsonpath(data, "$.name") == "test"
        assert extract_jsonpath(data, "$.value") == 42

    def test_nested_field_access(self):
        """Test extracting nested fields."""
        data = {
            "checks": {
                "BranchProtection": {
                    "pass": True,
                    "score": 8,
                }
            }
        }
        assert extract_jsonpath(data, "$.checks.BranchProtection.pass") is True
        assert extract_jsonpath(data, "$.checks.BranchProtection.score") == 8

    def test_array_index_access(self):
        """Test extracting from arrays."""
        data = {
            "items": [
                {"name": "first"},
                {"name": "second"},
                {"name": "third"},
            ]
        }
        assert extract_jsonpath(data, "$.items[0].name") == "first"
        assert extract_jsonpath(data, "$.items[1].name") == "second"
        assert extract_jsonpath(data, "$.items[2].name") == "third"

    def test_array_out_of_bounds(self):
        """Test array access out of bounds returns None."""
        data = {"items": [1, 2, 3]}
        assert extract_jsonpath(data, "$.items[10]") is None

    def test_missing_field_returns_none(self):
        """Test missing field returns None."""
        data = {"name": "test"}
        assert extract_jsonpath(data, "$.missing") is None
        assert extract_jsonpath(data, "$.nested.missing") is None

    def test_path_without_dollar_sign(self):
        """Test path without leading $."""
        data = {"name": "test"}
        assert extract_jsonpath(data, "name") == "test"
        assert extract_jsonpath(data, ".name") == "test"

    def test_none_data_returns_none(self):
        """Test None data returns None."""
        assert extract_jsonpath(None, "$.name") is None

    def test_none_path_returns_none(self):
        """Test None path returns None."""
        assert extract_jsonpath({"name": "test"}, None) is None

    def test_complex_nested_path(self):
        """Test complex nested path with arrays and objects."""
        data = {
            "results": [
                {
                    "checks": [
                        {"id": "check1", "status": "pass"},
                        {"id": "check2", "status": "fail"},
                    ]
                }
            ]
        }
        assert extract_jsonpath(data, "$.results[0].checks[0].status") == "pass"
        assert extract_jsonpath(data, "$.results[0].checks[1].id") == "check2"


class TestNormalizeToolOutput:
    """Tests for normalize_tool_output()."""

    def test_basic_pass_status(self):
        """Test normalizing output with pass status."""
        raw = {"result": True}
        mapping = OutputMapping(status_path="$.result")

        output = normalize_tool_output(raw, mapping)

        assert output.status == "pass"
        assert output.confidence == 1.0

    def test_basic_fail_status(self):
        """Test normalizing output with fail status."""
        raw = {"result": False}
        mapping = OutputMapping(status_path="$.result")

        output = normalize_tool_output(raw, mapping)

        assert output.status == "fail"
        assert output.confidence == 1.0

    def test_string_status_values(self):
        """Test normalizing string status values."""
        mapping = OutputMapping(status_path="$.status")

        # Pass variants
        for status in ["pass", "passed", "success", "true", "ok"]:
            raw = {"status": status}
            output = normalize_tool_output(raw, mapping)
            assert output.status == "pass", f"Failed for '{status}'"

        # Fail variants
        for status in ["fail", "failed", "failure", "false"]:
            raw = {"status": status}
            output = normalize_tool_output(raw, mapping)
            assert output.status == "fail", f"Failed for '{status}'"

    def test_score_with_threshold(self):
        """Test score-based status with threshold."""
        raw = {"score": 8}
        mapping = OutputMapping(
            status_path="$.status",  # Not present
            score_path="$.score",
            pass_threshold=7.0,
        )

        output = normalize_tool_output(raw, mapping)
        assert output.status == "pass"

        # Below threshold
        raw = {"score": 5}
        output = normalize_tool_output(raw, mapping)
        assert output.status == "fail"

    def test_message_extraction(self):
        """Test message extraction from output."""
        raw = {"status": "pass", "reason": "All checks passed"}
        mapping = OutputMapping(
            status_path="$.status",
            message_path="$.reason",
        )

        output = normalize_tool_output(raw, mapping)
        assert output.message == "All checks passed"

    def test_default_message_generation(self):
        """Test default message generation when no message_path."""
        mapping = OutputMapping(status_path="$.status")

        raw = {"status": "pass"}
        output = normalize_tool_output(raw, mapping)
        assert output.message == "Check passed"

        raw = {"status": "fail"}
        output = normalize_tool_output(raw, mapping)
        assert output.message == "Check failed"

    def test_found_evidence_extraction(self):
        """Test extracting found evidence from output."""
        raw = {
            "status": "pass",
            "file": "SECURITY.md",
        }
        mapping = OutputMapping(
            status_path="$.status",
            found_path="$.file",
            found_kind_default="file",
        )

        output = normalize_tool_output(raw, mapping)
        assert output.found is not None
        assert output.found.path == "SECURITY.md"
        assert output.found.kind == "file"

    def test_found_evidence_with_kind(self):
        """Test extracting found evidence with kind from output."""
        raw = {
            "status": "pass",
            "location": "https://docs.example.com/security",
            "type": "url",
        }
        mapping = OutputMapping(
            status_path="$.status",
            found_path="$.location",
            found_kind_path="$.type",
            found_kind_default="file",
        )

        output = normalize_tool_output(raw, mapping)
        assert output.found is not None
        assert output.found.url == "https://docs.example.com/security"
        assert output.found.kind == "url"

    def test_json_string_input(self):
        """Test normalizing JSON string input."""
        raw = '{"status": "pass", "message": "OK"}'
        mapping = OutputMapping(
            status_path="$.status",
            message_path="$.message",
        )

        output = normalize_tool_output(raw, mapping)
        assert output.status == "pass"
        assert output.message == "OK"

    def test_invalid_json_string(self):
        """Test handling invalid JSON string."""
        raw = "not valid json"
        mapping = OutputMapping(status_path="$.status")

        output = normalize_tool_output(raw, mapping)
        assert output.status == "error"
        assert "Failed to parse" in output.message

    def test_non_dict_input(self):
        """Test handling non-dict input."""
        raw = ["a", "list"]
        mapping = OutputMapping(status_path="$.status")

        output = normalize_tool_output(raw, mapping)
        assert output.status == "error"
        assert "Expected dict" in output.message

    def test_no_status_path_inconclusive(self):
        """Test that missing status_path returns inconclusive."""
        raw = {"data": "value"}
        mapping = OutputMapping()  # No status_path

        output = normalize_tool_output(raw, mapping)
        assert output.status == "inconclusive"

    def test_evidence_preserved(self):
        """Test that raw output is preserved in evidence."""
        raw = {"status": "pass", "extra": "data"}
        mapping = OutputMapping(status_path="$.status")

        output = normalize_tool_output(raw, mapping)
        assert output.evidence["raw_output"] == raw


class TestNormalizeScorecardOutput:
    """Tests for normalize_scorecard_output()."""

    def test_passing_score(self):
        """Test Scorecard output with passing score."""
        raw = {
            "checks": [
                {
                    "name": "BranchProtection",
                    "score": 9,
                    "reason": "Branch protection is enabled",
                }
            ]
        }

        output = normalize_scorecard_output(raw, "BranchProtection")

        assert output.status == "pass"
        assert output.confidence == 1.0
        assert "Branch protection is enabled" in output.message
        assert output.evidence["score"] == 9

    def test_failing_score(self):
        """Test Scorecard output with failing score."""
        raw = {
            "checks": [
                {
                    "name": "BranchProtection",
                    "score": 5,
                    "reason": "Branch protection is partially configured",
                }
            ]
        }

        output = normalize_scorecard_output(raw, "BranchProtection")

        assert output.status == "fail"
        assert output.evidence["score"] == 5

    def test_inconclusive_score(self):
        """Test Scorecard output with inconclusive score (-1)."""
        raw = {
            "checks": [
                {
                    "name": "BranchProtection",
                    "score": -1,
                    "reason": "Could not determine branch protection status",
                }
            ]
        }

        output = normalize_scorecard_output(raw, "BranchProtection")

        assert output.status == "inconclusive"
        assert output.confidence == 0.5

    def test_check_not_found(self):
        """Test when requested check is not in output."""
        raw = {
            "checks": [
                {
                    "name": "OtherCheck",
                    "score": 10,
                }
            ]
        }

        output = normalize_scorecard_output(raw, "BranchProtection")

        assert output.status == "inconclusive"
        assert "not found" in output.message

    def test_multiple_checks(self):
        """Test selecting correct check from multiple."""
        raw = {
            "checks": [
                {"name": "Check1", "score": 5, "reason": "Reason 1"},
                {"name": "BranchProtection", "score": 9, "reason": "Reason 2"},
                {"name": "Check3", "score": 3, "reason": "Reason 3"},
            ]
        }

        output = normalize_scorecard_output(raw, "BranchProtection")

        assert output.status == "pass"
        assert output.evidence["score"] == 9
        assert "Reason 2" in output.message

    def test_empty_checks_list(self):
        """Test with empty checks list."""
        raw = {"checks": []}

        output = normalize_scorecard_output(raw, "BranchProtection")

        assert output.status == "inconclusive"
        assert "not found" in output.message

    def test_missing_checks_key(self):
        """Test with missing checks key."""
        raw = {"other": "data"}

        output = normalize_scorecard_output(raw, "BranchProtection")

        assert output.status == "inconclusive"

    def test_exact_threshold_score(self):
        """Test score exactly at threshold (8)."""
        raw = {
            "checks": [
                {"name": "TestCheck", "score": 8, "reason": "Score is 8"}
            ]
        }

        output = normalize_scorecard_output(raw, "TestCheck")

        assert output.status == "pass"  # 8 >= 8

    def test_just_below_threshold(self):
        """Test score just below threshold."""
        raw = {
            "checks": [
                {"name": "TestCheck", "score": 7, "reason": "Score is 7"}
            ]
        }

        output = normalize_scorecard_output(raw, "TestCheck")

        assert output.status == "fail"  # 7 < 8


class TestCheckOutputModel:
    """Tests for CheckOutput model from models.py."""

    def test_create_with_all_fields(self):
        """Test creating CheckOutput with all fields."""
        output = CheckOutput(
            status="pass",
            message="All checks passed",
            confidence=0.95,
            found=FoundEvidence(path="file.txt"),
            evidence={"key": "value"},
            issues=["issue1"],
            suggestions=["suggestion1"],
        )

        assert output.status == "pass"
        assert output.message == "All checks passed"
        assert output.confidence == 0.95
        assert output.found.path == "file.txt"
        assert output.evidence == {"key": "value"}
        assert output.issues == ["issue1"]
        assert output.suggestions == ["suggestion1"]

    def test_create_minimal(self):
        """Test creating CheckOutput with minimal fields."""
        output = CheckOutput(
            status="fail",
            message="Check failed",
        )

        assert output.status == "fail"
        assert output.message == "Check failed"
        assert output.confidence == 1.0  # Default
        assert output.found is None
        assert output.evidence == {}
        assert output.issues == []
        assert output.suggestions == []
