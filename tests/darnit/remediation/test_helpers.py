"""Tests for darnit.remediation.helpers module."""

from pathlib import Path

import pytest

from darnit.remediation.github import detect_workflow_checks
from darnit.remediation.helpers import (
    check_file_exists,
    ensure_directory,
    format_error,
    format_success,
    format_warning,
    write_file_safe,
)


class TestEnsureDirectory:
    """Tests for ensure_directory function."""

    @pytest.mark.unit
    def test_creates_new_directory(self, temp_dir: Path):
        """Test creating a new directory."""
        new_dir = temp_dir / "new_subdir"
        result = ensure_directory(str(new_dir))
        assert result is None
        assert new_dir.exists()
        assert new_dir.is_dir()

    @pytest.mark.unit
    def test_creates_nested_directories(self, temp_dir: Path):
        """Test creating nested directories."""
        nested = temp_dir / "a" / "b" / "c"
        result = ensure_directory(str(nested))
        assert result is None
        assert nested.exists()

    @pytest.mark.unit
    def test_existing_directory_is_ok(self, temp_dir: Path):
        """Test that existing directory doesn't cause error."""
        result = ensure_directory(str(temp_dir))
        assert result is None

    @pytest.mark.unit
    def test_file_blocking_directory(self, temp_dir: Path):
        """Test error when file blocks directory creation."""
        # Create a file where we want a directory
        blocking_file = temp_dir / "blocking"
        blocking_file.write_text("content")

        # Try to create a subdirectory of the file
        result = ensure_directory(str(blocking_file / "subdir"))
        assert result is not None
        assert "Failed" in result


class TestWriteFileSafe:
    """Tests for write_file_safe function."""

    @pytest.mark.unit
    def test_writes_new_file(self, temp_dir: Path):
        """Test writing a new file."""
        filepath = temp_dir / "test.txt"
        success, msg = write_file_safe(str(filepath), "Hello, World!")
        assert success is True
        assert "Successfully" in msg
        assert filepath.read_text() == "Hello, World!"

    @pytest.mark.unit
    def test_overwrites_existing_file(self, temp_dir: Path):
        """Test overwriting an existing file."""
        filepath = temp_dir / "test.txt"
        filepath.write_text("Old content")

        success, msg = write_file_safe(str(filepath), "New content")
        assert success is True
        assert filepath.read_text() == "New content"

    @pytest.mark.unit
    def test_writes_unicode(self, temp_dir: Path):
        """Test writing Unicode content."""
        filepath = temp_dir / "unicode.txt"
        content = "Hello, 世界! 🌍"
        success, msg = write_file_safe(str(filepath), content)
        assert success is True
        assert filepath.read_text() == content

    @pytest.mark.unit
    def test_invalid_path(self, temp_dir: Path):
        """Test error on invalid path."""
        # Try to write to a path inside a file (impossible)
        blocking_file = temp_dir / "file.txt"
        blocking_file.write_text("content")

        success, msg = write_file_safe(str(blocking_file / "inside.txt"), "content")
        assert success is False
        assert "Failed" in msg


class TestCheckFileExists:
    """Tests for check_file_exists function."""

    @pytest.mark.unit
    def test_single_existing_file(self, temp_dir: Path):
        """Test checking a single existing file."""
        (temp_dir / "README.md").write_text("# Test")
        result = check_file_exists(str(temp_dir), "README.md")
        assert "README.md" in result

    @pytest.mark.unit
    def test_single_nonexistent_file(self, temp_dir: Path):
        """Test checking a nonexistent file."""
        result = check_file_exists(str(temp_dir), "NONEXISTENT.md")
        assert len(result) == 0

    @pytest.mark.unit
    def test_multiple_patterns_mixed(self, temp_dir: Path):
        """Test checking multiple patterns with mixed results."""
        (temp_dir / "README.md").write_text("# Test")
        (temp_dir / "LICENSE").write_text("MIT")

        result = check_file_exists(
            str(temp_dir),
            "README.md",
            "LICENSE",
            "SECURITY.md"  # Doesn't exist
        )
        assert len(result) == 2
        assert "README.md" in result
        assert "LICENSE" in result
        assert "SECURITY.md" not in result

    @pytest.mark.unit
    def test_no_patterns(self, temp_dir: Path):
        """Test with no patterns."""
        result = check_file_exists(str(temp_dir))
        assert result == []


class TestDetectWorkflowChecks:
    """Tests for detect_workflow_checks function."""

    @pytest.mark.unit
    def test_no_workflow_directory(self, temp_dir: Path):
        """Test when no .github/workflows directory exists."""
        result = detect_workflow_checks(str(temp_dir))
        assert result == []

    @pytest.mark.unit
    def test_empty_workflow_directory(self, temp_dir: Path):
        """Test with empty workflows directory."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        result = detect_workflow_checks(str(temp_dir))
        assert result == []

    @pytest.mark.unit
    def test_detects_simple_workflow(self, temp_dir: Path):
        """Test detecting jobs from a simple workflow file."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        # Create a simple workflow file
        workflow = """name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
        (workflows_dir / "ci.yml").write_text(workflow)

        result = detect_workflow_checks(str(temp_dir))
        # Should find at least the job IDs
        job_ids = [c.get("job_id") for c in result]
        assert "test" in job_ids or "lint" in job_ids

    @pytest.mark.unit
    def test_ignores_non_yaml_files(self, temp_dir: Path):
        """Test that non-YAML files are ignored."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        (workflows_dir / "readme.txt").write_text("Not a workflow")
        (workflows_dir / "script.sh").write_text("#!/bin/bash")

        result = detect_workflow_checks(str(temp_dir))
        assert result == []


class TestFormatSuccess:
    """Tests for format_success function."""

    @pytest.mark.unit
    def test_basic_success(self):
        """Test basic success message."""
        result = format_success("Operation completed", {}, [])
        assert "✅" in result
        assert "Operation completed" in result

    @pytest.mark.unit
    def test_with_details(self):
        """Test success message with details."""
        result = format_success(
            "Created file",
            {"File": "SECURITY.md", "Size": "1.2KB"},
            []
        )
        assert "**File:**" in result
        assert "SECURITY.md" in result
        assert "**Size:**" in result

    @pytest.mark.unit
    def test_with_controls(self):
        """Test success message with controls."""
        result = format_success(
            "Remediation applied",
            {},
            ["OSPS-VM-02.01", "OSPS-VM-03.01"]
        )
        assert "OSPS Controls Addressed" in result
        assert "OSPS-VM-02.01" in result
        assert "OSPS-VM-03.01" in result

    @pytest.mark.unit
    def test_with_all_parts(self):
        """Test success message with all parts."""
        result = format_success(
            "Security policy created",
            {"Path": "SECURITY.md"},
            ["OSPS-VM-02.01"]
        )
        assert "✅" in result
        assert "Security policy created" in result
        assert "**Path:**" in result
        assert "OSPS-VM-02.01" in result


class TestFormatError:
    """Tests for format_error function."""

    @pytest.mark.unit
    def test_basic_error(self):
        """Test basic error message."""
        result = format_error("Something went wrong")
        assert "❌" in result
        assert "Something went wrong" in result


class TestFormatWarning:
    """Tests for format_warning function."""

    @pytest.mark.unit
    def test_basic_warning(self):
        """Test basic warning message."""
        result = format_warning("This might be a problem")
        assert "⚠️" in result
        assert "This might be a problem" in result
