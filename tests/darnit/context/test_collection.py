"""Tests for context collection module.

Tests the file parsers and context resolution priority.
"""

from pathlib import Path

from darnit.context.collection import (
    coerce_context_value,
    parse_codeowners,
    parse_json_path,
    parse_markdown_list,
    parse_yaml_path,
    resolve_context_value,
    validate_context_value,
)


class TestParseMarkdownList:
    """Tests for parse_markdown_list function."""

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test parsing empty file returns empty list."""
        md_file = tmp_path / "test.md"
        md_file.write_text("")
        assert parse_markdown_list(md_file) == []

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Test parsing nonexistent file returns empty list."""
        assert parse_markdown_list(tmp_path / "missing.md") == []

    def test_bullet_list(self, tmp_path: Path) -> None:
        """Test parsing bullet list items."""
        md_file = tmp_path / "test.md"
        md_file.write_text("""
# Contributors

- Alice
- Bob
- Charlie
""")
        result = parse_markdown_list(md_file)
        assert "Alice" in result
        assert "Bob" in result
        assert "Charlie" in result

    def test_numbered_list(self, tmp_path: Path) -> None:
        """Test parsing numbered list items."""
        md_file = tmp_path / "test.md"
        md_file.write_text("""
# Contributors

1. Alice
2. Bob
3. Charlie
""")
        result = parse_markdown_list(md_file)
        assert "Alice" in result
        assert "Bob" in result
        assert "Charlie" in result

    def test_at_mentions(self, tmp_path: Path) -> None:
        """Test extracting @mentions from markdown."""
        md_file = tmp_path / "test.md"
        md_file.write_text("""
# Maintainers

Contact @alice or @bob for help.
""")
        result = parse_markdown_list(md_file)
        assert "@alice" in result
        assert "@bob" in result

    def test_deduplicate(self, tmp_path: Path) -> None:
        """Test that duplicate items are deduplicated."""
        md_file = tmp_path / "test.md"
        md_file.write_text("""
- Alice
- Alice
- @alice
""")
        result = parse_markdown_list(md_file)
        # Should have Alice (bullet) and @alice (mention), not duplicates
        assert len([x for x in result if "alice" in x.lower()]) <= 2

    def test_with_pattern_filter(self, tmp_path: Path) -> None:
        """Test filtering items with a pattern."""
        md_file = tmp_path / "test.md"
        md_file.write_text("""
- alice@example.com
- bob@example.com
- not-an-email
""")
        # Filter to only email-like items
        result = parse_markdown_list(md_file, pattern=r"@.*\.com")
        assert "alice@example.com" in result
        assert "bob@example.com" in result
        assert "not-an-email" not in result


class TestParseYamlPath:
    """Tests for parse_yaml_path function."""

    def test_simple_path(self, tmp_path: Path) -> None:
        """Test extracting simple path."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("""
name: my-project
version: "1.0.0"
""")
        assert parse_yaml_path(yaml_file, "name") == "my-project"
        assert parse_yaml_path(yaml_file, "version") == "1.0.0"

    def test_nested_path(self, tmp_path: Path) -> None:
        """Test extracting nested path."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("""
security:
  policy:
    path: SECURITY.md
""")
        assert parse_yaml_path(yaml_file, "security.policy.path") == "SECURITY.md"

    def test_missing_path(self, tmp_path: Path) -> None:
        """Test extracting missing path returns None."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("name: test")
        assert parse_yaml_path(yaml_file, "missing.path") is None

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Test parsing nonexistent file returns None."""
        assert parse_yaml_path(tmp_path / "missing.yaml", "any.path") is None


class TestParseJsonPath:
    """Tests for parse_json_path function."""

    def test_simple_path(self, tmp_path: Path) -> None:
        """Test extracting simple path."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"name": "my-project", "version": "1.0.0"}')
        assert parse_json_path(json_file, "name") == "my-project"
        assert parse_json_path(json_file, "version") == "1.0.0"

    def test_nested_path(self, tmp_path: Path) -> None:
        """Test extracting nested path."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"security": {"policy": {"path": "SECURITY.md"}}}')
        assert parse_json_path(json_file, "security.policy.path") == "SECURITY.md"

    def test_jsonpath_style(self, tmp_path: Path) -> None:
        """Test JSONPath-style paths with $. prefix."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"data": {"value": 42}}')
        assert parse_json_path(json_file, "$.data.value") == 42

    def test_array_index(self, tmp_path: Path) -> None:
        """Test extracting array elements."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"items": ["first", "second", "third"]}')
        assert parse_json_path(json_file, "items[0]") == "first"
        assert parse_json_path(json_file, "items[1]") == "second"

    def test_missing_path(self, tmp_path: Path) -> None:
        """Test extracting missing path returns None."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"name": "test"}')
        assert parse_json_path(json_file, "missing.path") is None


class TestParseCodeowners:
    """Tests for parse_codeowners function."""

    def test_simple_codeowners(self, tmp_path: Path) -> None:
        """Test parsing simple CODEOWNERS file."""
        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text("""
# CODEOWNERS file
* @alice @bob
/src/ @charlie
""")
        result = parse_codeowners(codeowners)
        assert "@alice" in result
        assert "@bob" in result
        assert "@charlie" in result

    def test_team_mentions(self, tmp_path: Path) -> None:
        """Test parsing team mentions in CODEOWNERS."""
        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text("* @myorg/myteam @alice")
        result = parse_codeowners(codeowners)
        assert "@myorg/myteam" in result
        assert "@alice" in result

    def test_skip_comments(self, tmp_path: Path) -> None:
        """Test that comments are skipped."""
        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text("""
# This is a comment about @notincluded
* @included
""")
        result = parse_codeowners(codeowners)
        assert "@included" in result
        assert "@notincluded" not in result


class TestResolveContextValue:
    """Tests for resolve_context_value function."""

    def test_resolve_from_project_context(self, tmp_path: Path) -> None:
        """Test resolution from .project/ context."""
        definition = {
            "store_as": "governance.maintainers",
        }
        project_context = {
            "governance": {
                "maintainers": ["@alice", "@bob"],
            }
        }
        value, method = resolve_context_value(
            "maintainers", definition, tmp_path, project_context
        )
        assert value == ["@alice", "@bob"]
        assert method == "project"

    def test_resolve_from_file_source(self, tmp_path: Path) -> None:
        """Test resolution from file source."""
        # Create a CODEOWNERS file
        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text("* @alice @bob")

        definition = {
            "source": "CODEOWNERS",
            "parser": "codeowners",
        }
        value, method = resolve_context_value(
            "maintainers", definition, tmp_path, None
        )
        assert value is not None
        assert "@alice" in value
        assert method == "file"

    def test_resolve_from_hint_sources(self, tmp_path: Path) -> None:
        """Test resolution from hint_sources."""
        # Create a CODEOWNERS file
        codeowners = tmp_path / "CODEOWNERS"
        codeowners.write_text("* @charlie")

        definition = {
            "hint_sources": ["CODEOWNERS", ".github/CODEOWNERS"],
        }
        value, method = resolve_context_value(
            "maintainers", definition, tmp_path, None
        )
        assert value is not None
        assert "@charlie" in value
        assert "file:CODEOWNERS" in method

    def test_resolve_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Test resolution returns None when value not found."""
        definition = {
            "store_as": "governance.maintainers",
        }
        value, method = resolve_context_value(
            "maintainers", definition, tmp_path, None
        )
        assert value is None
        assert method is None


class TestValidateContextValue:
    """Tests for validate_context_value function."""

    def test_validate_boolean_true(self) -> None:
        """Test validating boolean true values."""
        definition = {"type": "boolean"}
        assert validate_context_value(True, definition) == (True, None)
        assert validate_context_value("true", definition) == (True, None)
        assert validate_context_value("yes", definition) == (True, None)
        assert validate_context_value("1", definition) == (True, None)

    def test_validate_boolean_false(self) -> None:
        """Test validating boolean false values."""
        definition = {"type": "boolean"}
        assert validate_context_value(False, definition) == (True, None)
        assert validate_context_value("false", definition) == (True, None)
        assert validate_context_value("no", definition) == (True, None)

    def test_validate_boolean_invalid(self) -> None:
        """Test validating invalid boolean values."""
        definition = {"type": "boolean"}
        is_valid, error = validate_context_value("maybe", definition)
        assert not is_valid
        assert "boolean" in error.lower()

    def test_validate_email(self) -> None:
        """Test validating email values."""
        definition = {"type": "email"}
        assert validate_context_value("test@example.com", definition) == (True, None)

        is_valid, error = validate_context_value("not-an-email", definition)
        assert not is_valid
        assert "email" in error.lower()

    def test_validate_enum(self) -> None:
        """Test validating enum values."""
        definition = {"type": "enum", "values": ["github", "gitlab", "jenkins"]}
        assert validate_context_value("github", definition) == (True, None)

        is_valid, error = validate_context_value("bitbucket", definition)
        assert not is_valid
        assert "github" in error

    def test_validate_string_with_pattern(self) -> None:
        """Test validating string with pattern."""
        definition = {"type": "string", "pattern": r"^@[\w-]+$"}
        assert validate_context_value("@alice", definition) == (True, None)

        is_valid, error = validate_context_value("alice", definition)
        assert not is_valid
        assert "pattern" in error.lower()


class TestCoerceContextValue:
    """Tests for coerce_context_value function."""

    def test_coerce_boolean(self) -> None:
        """Test coercing boolean values."""
        definition = {"type": "boolean"}
        assert coerce_context_value(True, definition) is True
        assert coerce_context_value("true", definition) is True
        assert coerce_context_value("false", definition) is False

    def test_coerce_list_from_string(self) -> None:
        """Test coercing comma-separated string to list."""
        definition = {"type": "list[string]"}
        result = coerce_context_value("alice, bob, charlie", definition)
        assert result == ["alice", "bob", "charlie"]

    def test_coerce_list_passthrough(self) -> None:
        """Test that list values pass through unchanged."""
        definition = {"type": "list[string]"}
        result = coerce_context_value(["alice", "bob"], definition)
        assert result == ["alice", "bob"]
