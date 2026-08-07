"""Tests for the AnswerSource Protocol + MVP file adapters (feature 026 T008).

Covers contract items AS-1..AS-8 from
``specs/026-darnit-harness/contracts/answer-source-protocol.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.harness.answer_sources import (
    AnswerResolver,
    AnswerSource,
    AnswerSourceLoadError,
    FileAnswerSource,
    ProjectYamlAnswerSource,
)

# ---------------------------------------------------------------------------
# MockAnswerSource: proves the Protocol admits a non-file source (FR-005a).
# ---------------------------------------------------------------------------


class MockAnswerSource:
    """Test-only source that reads from an in-memory dict.

    Its existence closes contract-file gap "future non-file adapter": a
    class outside the shipped file-adapters implements the Protocol and
    resolves correctly.
    """

    def __init__(self, name: str, answers: dict[str, str]) -> None:
        self.name = name
        self._answers = dict(answers)

    def get_answer(self, context_key: str) -> str | None:
        return self._answers.get(context_key)

    def known_keys(self) -> set[str]:
        return set(self._answers.keys())


# ---------------------------------------------------------------------------
# Protocol conformance (AS-4)
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_project_yaml_source_satisfies_protocol(self, tmp_path: Path) -> None:
        src = ProjectYamlAnswerSource(str(tmp_path))
        assert isinstance(src, AnswerSource)

    def test_file_source_satisfies_protocol(self, tmp_path: Path) -> None:
        p = tmp_path / "answers.yaml"
        p.write_text("k: v\n")
        src = FileAnswerSource(p)
        assert isinstance(src, AnswerSource)

    def test_mock_source_satisfies_protocol(self) -> None:
        """Contract 'future non-file adapter' gap-closer."""
        src = MockAnswerSource("mock", {"k": "v"})
        assert isinstance(src, AnswerSource)


# ---------------------------------------------------------------------------
# AnswerResolver precedence (AS-6, AS-7, AS-8)
# ---------------------------------------------------------------------------


class TestAnswerResolverPrecedence:
    def test_last_source_wins(self) -> None:
        """AS-6: LAST-added source with a match wins for a given key."""
        first = MockAnswerSource("first", {"security_contact": "a@example.com"})
        second = MockAnswerSource("second", {"security_contact": "b@example.com"})
        r = AnswerResolver()
        r.add(first)
        r.add(second)
        answer, source = r.resolve("security_contact")
        assert answer == "b@example.com"
        assert source == "second"

    def test_returns_none_for_missing_key(self) -> None:
        r = AnswerResolver()
        r.add(MockAnswerSource("x", {"a": "1"}))
        answer, source = r.resolve("nonexistent")
        assert answer is None
        assert source is None

    def test_earlier_source_used_when_later_lacks_key(self) -> None:
        first = MockAnswerSource("first", {"a": "1", "b": "2"})
        second = MockAnswerSource("second", {"a": "override"})
        r = AnswerResolver()
        r.add(first)
        r.add(second)
        # "b" only exists on first
        assert r.resolve("b") == ("2", "first")
        # "a" exists on both; second wins
        assert r.resolve("a") == ("override", "second")

    def test_duplicate_name_rejected(self) -> None:
        """AS-7: name collision on add raises ValueError with both names."""
        r = AnswerResolver()
        r.add(MockAnswerSource("dupe", {}))
        with pytest.raises(ValueError) as excinfo:
            r.add(MockAnswerSource("dupe", {}))
        assert "dupe" in str(excinfo.value)

    def test_summary_lists_sources_with_counts(self) -> None:
        """AS-8: summary produces a readable one-liner for logging."""
        r = AnswerResolver()
        r.add(MockAnswerSource("s1", {"a": "1", "b": "2"}))
        r.add(MockAnswerSource("s2", {"c": "3"}))
        s = r.summary()
        assert "s1" in s
        assert "s2" in s
        assert "2 keys" in s
        assert "1 keys" in s

    def test_sources_used_returns_ordered_names(self) -> None:
        r = AnswerResolver()
        r.add(MockAnswerSource("alpha", {}))
        r.add(MockAnswerSource("beta", {}))
        assert r.sources_used() == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# FileAnswerSource: YAML and JSON round-trip + error paths
# ---------------------------------------------------------------------------


class TestFileAnswerSource:
    def test_reads_yaml_file(self, tmp_path: Path) -> None:
        p = tmp_path / "answers.yaml"
        p.write_text("security_contact: sec@example.com\nother: value\n")
        src = FileAnswerSource(p)
        assert src.get_answer("security_contact") == "sec@example.com"
        assert src.get_answer("other") == "value"
        assert src.known_keys() == {"security_contact", "other"}

    def test_reads_json_file(self, tmp_path: Path) -> None:
        p = tmp_path / "answers.json"
        p.write_text('{"security_contact": "sec@example.com"}')
        src = FileAnswerSource(p)
        assert src.get_answer("security_contact") == "sec@example.com"

    def test_missing_file_raises_load_error(self, tmp_path: Path) -> None:
        with pytest.raises(AnswerSourceLoadError) as excinfo:
            FileAnswerSource(tmp_path / "does-not-exist.yaml")
        assert "not found" in str(excinfo.value).lower()

    def test_parse_error_raises_load_error(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("this: is: broken\n  - unclosed\n")
        with pytest.raises(AnswerSourceLoadError):
            FileAnswerSource(p)

    def test_non_mapping_top_level_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "list.yaml"
        p.write_text("- just_a_list\n- of_items\n")
        with pytest.raises(AnswerSourceLoadError) as excinfo:
            FileAnswerSource(p)
        assert "mapping" in str(excinfo.value).lower()

    def test_name_includes_path(self, tmp_path: Path) -> None:
        p = tmp_path / "answers.yaml"
        p.write_text("k: v\n")
        src = FileAnswerSource(p)
        assert str(p) in src.name


# ---------------------------------------------------------------------------
# ProjectYamlAnswerSource: silent on missing file, reads security_contact
# ---------------------------------------------------------------------------


class TestProjectYamlAnswerSource:
    def test_missing_project_dir_yields_empty_source(self, tmp_path: Path) -> None:
        """No .project/ dir at all -> known_keys empty, get_answer None. No raise."""
        src = ProjectYamlAnswerSource(str(tmp_path))
        assert src.known_keys() == set()
        assert src.get_answer("security_contact") is None

    def test_reads_security_contact_from_project_yaml(self, tmp_path: Path) -> None:
        (tmp_path / ".project").mkdir()
        (tmp_path / ".project" / "project.yaml").write_text(
            "name: test-repo\nsecurity:\n  contact: sec@example.com\n",
        )
        src = ProjectYamlAnswerSource(str(tmp_path))
        assert src.get_answer("security_contact") == "sec@example.com"
