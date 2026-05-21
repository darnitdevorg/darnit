"""Tree-sitter wrappers and query execution helpers.

This module isolates every interaction with the tree-sitter 0.25 API so the
rest of the discovery pipeline stays ergonomic. Queries are constructed as
module-level constants in `queries/<language>.py` and re-used across files.

Thread-safety notes:

* ``tree_sitter.Language`` is thread-safe and can be shared.
* ``tree_sitter.Parser`` is NOT thread-safe. Create one per worker.
* ``tree_sitter.QueryCursor`` is NOT thread-safe. Create one per call.

Error recovery:

Tree-sitter never raises on malformed input; ``parser.parse()`` returns a tree
with ``ERROR`` / ``MISSING`` nodes and queries still work on recoverable parts.
The wrappers below never wrap ``parse()`` in a ``try`` block.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

try:
    import tree_sitter as ts
    from tree_sitter_language_pack import get_language, get_parser

    TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover — dependency is required in pyproject.toml
    TREE_SITTER_AVAILABLE = False
    ts = None  # type: ignore[assignment]

    def get_language(name: str) -> Any:  # type: ignore[misc]
        raise ImportError("tree-sitter-language-pack is not installed")

    def get_parser(name: str) -> Any:  # type: ignore[misc]
        raise ImportError("tree-sitter-language-pack is not installed")


logger = logging.getLogger("darnit_baseline.threat_model.parsing")


# ---------------------------------------------------------------------------
# Supported languages
# ---------------------------------------------------------------------------


#: Languages the discovery pipeline understands structurally. TOML is not in
#: this list — see FR-005 in spec.md.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {"python", "javascript", "typescript", "tsx", "go", "yaml"}
)


#: Map file extensions to the tree-sitter grammar name. Every entry here must
#: resolve via ``get_language`` in ``tree-sitter-language-pack``.
_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".yml": "yaml",
    ".yaml": "yaml",
}


def detect_language_from_path(path: str | Path) -> str | None:
    """Return the tree-sitter grammar name for a file path, or None.

    Unknown extensions return None; callers should skip such files silently
    (they count toward `FileScanStats.total_files_seen` but not
    `in_scope_files`).
    """

    suffix = Path(path).suffix.lower()
    return _EXTENSION_TO_LANGUAGE.get(suffix)


# ---------------------------------------------------------------------------
# Parser / query helpers
# ---------------------------------------------------------------------------


def get_tree_sitter_parser(language_name: str) -> Any:
    """Return a ready-to-use ``tree_sitter.Parser`` for the given language.

    Wraps ``tree_sitter_language_pack.get_parser`` so future caching /
    pooling can be introduced in one place without touching call sites.
    """

    if language_name not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language: {language_name!r}. "
            f"Supported: {sorted(SUPPORTED_LANGUAGES)}"
        )
    return get_parser(language_name)


def parse_source(language_name: str, content: bytes) -> Any:
    """Parse source bytes into a tree-sitter Tree.

    Never raises on malformed input; tree-sitter recovers and returns a tree
    with ``ERROR`` nodes for the broken portions. Callers can inspect
    ``tree.root_node.has_error`` for diagnostic logging but the remaining
    captures are still valid.

    Compatibility: the ``parser.parse()`` argument type changed between
    ``tree-sitter-language-pack`` releases — 1.5.x accepts ``bytes``,
    1.8.x accepts only ``str``. We try ``bytes`` first (the historical
    contract and what the rest of darnit's pipeline carries around) and
    fall back to a UTF-8 decode on TypeError. Bytes that aren't valid
    UTF-8 are decoded with ``errors="replace"`` so a single odd file
    doesn't sink the whole audit.
    """

    if not isinstance(content, (bytes, bytearray)):
        raise TypeError(
            f"parse_source expected bytes, got {type(content).__name__}"
        )
    parser = get_tree_sitter_parser(language_name)
    try:
        tree = parser.parse(bytes(content))
    except TypeError:
        # tree-sitter-language-pack >= 1.8 binding wants str, not bytes.
        # Decode and retry.
        tree = parser.parse(bytes(content).decode("utf-8", errors="replace"))
    if tree.root_node.has_error:
        logger.debug(
            "tree-sitter reported parse errors for %s (recoverable)", language_name
        )
    return tree


def make_query(language_name: str, sexpr: str) -> Any:
    """Compile an S-expression query against the grammar for the given language.

    Queries should be constructed once at module load time and cached as
    module-level constants; query construction is significantly more expensive
    than execution.
    """

    if language_name not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language: {language_name!r}. "
            f"Supported: {sorted(SUPPORTED_LANGUAGES)}"
        )
    language = get_language(language_name)
    return ts.Query(language, sexpr)


def run_query(query: Any, root_node: Any) -> Iterator[dict[str, list[Any]]]:
    """Execute a compiled query and yield one capture dict per match.

    Each yielded dict maps capture names to lists of ``tree_sitter.Node``.
    Note that every capture name maps to a *list* even when only one node
    matched — always index ``[0]`` or iterate.
    """

    cursor = ts.QueryCursor(query)
    for _pattern_index, captures in cursor.matches(root_node):
        yield captures


def node_text(node: Any, source: bytes) -> str:
    """Return the UTF-8 decoded text of a tree-sitter node.

    Handles the common failure mode where callers pass a ``str`` source by
    decoding lazily via ``node.text`` when the source is not available.
    """

    if source is not None:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    return node.text.decode("utf-8", errors="replace")


__all__ = [
    "SUPPORTED_LANGUAGES",
    "detect_language_from_path",
    "get_tree_sitter_parser",
    "parse_source",
    "make_query",
    "run_query",
    "node_text",
    "TREE_SITTER_AVAILABLE",
]
