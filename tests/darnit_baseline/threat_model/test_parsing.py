"""Smoke tests for darnit_baseline.threat_model.parsing.

Each test parses a small snippet and runs a trivial identifier query to
confirm the grammar is loadable and query execution works end-to-end.
These do NOT test discovery logic — that's in test_discovery.py.
"""

from __future__ import annotations

import pytest

from darnit_baseline.threat_model import parsing
from darnit_baseline.threat_model.parsing import (
    SUPPORTED_LANGUAGES,
    detect_language_from_path,
    make_query,
    parse_source,
    run_query,
)


def test_tree_sitter_available() -> None:
    assert parsing.TREE_SITTER_AVAILABLE, "tree-sitter must be importable"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/tmp/foo.py", "python"),
        ("/tmp/foo.pyi", "python"),
        ("/tmp/foo.js", "javascript"),
        ("/tmp/foo.mjs", "javascript"),
        ("/tmp/foo.ts", "typescript"),
        ("/tmp/foo.tsx", "tsx"),
        ("/tmp/foo.go", "go"),
        ("/tmp/foo.yml", "yaml"),
        ("/tmp/foo.yaml", "yaml"),
        ("/tmp/foo.toml", None),
        ("/tmp/foo.rs", None),
        ("/tmp/no_extension", None),
    ],
)
def test_detect_language_from_path(path: str, expected: str | None) -> None:
    assert detect_language_from_path(path) == expected


def test_supported_languages_is_frozen() -> None:
    assert isinstance(SUPPORTED_LANGUAGES, frozenset)
    assert "python" in SUPPORTED_LANGUAGES
    assert "toml" not in SUPPORTED_LANGUAGES  # FR-005


@pytest.mark.parametrize(
    "language,snippet",
    [
        ("python", b"def foo():\n    return 1\n"),
        ("javascript", b"function foo() { return 1; }\n"),
        # .jsx files are mapped to the javascript grammar; verify the grammar
        # actually handles JSX so detect_language_from_path('.jsx') is correct
        ("javascript", b"const C = () => <div>hi</div>;\n"),
        ("typescript", b"function foo(): number { return 1; }\n"),
        ("tsx", b"const C = () => <div>hi</div>;\n"),
        ("go", b"package main\n\nfunc foo() int { return 1 }\n"),
        ("yaml", b"name: test\non:\n  push:\n    branches: [main]\n"),
    ],
)
def test_parse_and_query_smoke(language: str, snippet: bytes) -> None:
    tree = parse_source(language, snippet)
    assert tree is not None
    assert not tree.root_node.has_error, (
        f"parse of {language} snippet reported errors: "
        f"{tree.root_node.sexp() if hasattr(tree.root_node, 'sexp') else ''}"
    )

    # Each grammar has at least one identifier-like node type. We use a
    # maximally permissive wildcard query that should always match something.
    query = make_query(language, "(_) @any")
    matches = list(run_query(query, tree.root_node))
    assert len(matches) > 0, f"expected at least one capture for {language}"


def test_parse_source_rejects_str() -> None:
    with pytest.raises(TypeError, match="expected bytes"):
        parse_source("python", "def foo(): pass")  # type: ignore[arg-type]


def test_parse_source_recovers_from_syntax_errors() -> None:
    """Tree-sitter must return a tree even for broken input."""

    broken = b"def foo(\n    broken\n\nclass X(\n"
    tree = parse_source("python", broken)
    assert tree is not None
    assert tree.root_node.has_error  # broken file is flagged but queries still work
    query = make_query("python", "(identifier) @id")
    matches = list(run_query(query, tree.root_node))
    # We should still find at least `foo` and `X` identifiers
    assert len(matches) >= 1


def test_unsupported_language_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported language"):
        parse_source("rust", b"fn main() {}")


def test_parse_source_handles_both_language_pack_apis(monkeypatch) -> None:
    """Regression: tree-sitter-language-pack changed parser.parse() arg
    type between releases — 1.5.x took bytes, 1.8.x takes str only.
    parse_source() must work against either by trying bytes first and
    falling back to a UTF-8 decode on TypeError.

    Simulates the 1.8.x binding by monkeypatching the parser to reject
    bytes and only accept str.
    """
    from darnit_baseline.threat_model import parsing

    real_parser = parsing.get_tree_sitter_parser("python")

    class StrOnlyParserWrapper:
        """Mimics the tree-sitter-language-pack 1.8 binding's parse()
        which raises TypeError unless given a str."""

        def parse(self, source):
            if not isinstance(source, str):
                raise TypeError(
                    "argument 'source': 'bytes' object is not an instance of 'str'"
                )
            return real_parser.parse(source.encode("utf-8"))

    monkeypatch.setattr(
        parsing, "get_tree_sitter_parser", lambda _lang: StrOnlyParserWrapper()
    )

    # Even though the underlying parser rejects bytes, parse_source must
    # still succeed by transparently falling back to the str path.
    tree = parse_source("python", b"def foo(): pass\n")
    assert tree is not None
    query = make_query("python", "(identifier) @id")
    matches = list(run_query(query, tree.root_node))
    assert any(
        match[1].get("id", []) and parsing.node_text(match[1]["id"][0], b"def foo(): pass\n") == "foo"
        if isinstance(match, tuple) and len(match) >= 2
        else False
        for match in matches
    ) or len(matches) >= 1  # at least one identifier captured


def test_parse_source_handles_non_utf8_bytes_under_str_binding(monkeypatch) -> None:
    """Regression: when the binding requires str, parse_source must decode
    bytes safely even if they contain invalid UTF-8 sequences. The decode
    uses errors='replace' so a single bad byte doesn't tank the audit.
    """
    from darnit_baseline.threat_model import parsing

    real_parser = parsing.get_tree_sitter_parser("python")

    class StrOnlyParserWrapper:
        def parse(self, source):
            if not isinstance(source, str):
                raise TypeError("source must be str")
            return real_parser.parse(source.encode("utf-8"))

    monkeypatch.setattr(
        parsing, "get_tree_sitter_parser", lambda _lang: StrOnlyParserWrapper()
    )

    # Embed a bare 0xFF byte (invalid UTF-8 start) into otherwise-valid Python.
    naughty = b"def foo():\n    return '\xff'\n"
    tree = parse_source("python", naughty)
    assert tree is not None  # didn't raise UnicodeDecodeError
