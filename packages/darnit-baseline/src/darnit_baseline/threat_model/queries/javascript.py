"""Tree-sitter queries for JavaScript / TypeScript / TSX discovery.

The same S-expression queries are executed against three distinct grammars
exposed by ``tree-sitter-language-pack``: ``javascript``, ``typescript``,
and ``tsx``. ``ts_discovery.py`` picks the right grammar based on the
file's extension.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..parsing import make_query

# ---------------------------------------------------------------------------
# Entry point queries — Express / Fastify / Hapi / Next.js shape
# ---------------------------------------------------------------------------

#: Generic ``obj.method("path", handler)`` call shape matching Express,
#: Fastify, Hapi, and similar routers. We accept a broad shape and filter
#: by method name in the extractor.
JS_ROUTE_CALL = make_query(
    "javascript",
    """
(call_expression
  function: (member_expression
    object: (identifier) @obj
    property: (property_identifier) @method)
  arguments: (arguments
    .
    (string) @path)) @whole
""",
)

TS_ROUTE_CALL = make_query(
    "typescript",
    """
(call_expression
  function: (member_expression
    object: (identifier) @obj
    property: (property_identifier) @method)
  arguments: (arguments
    .
    (string) @path)) @whole
""",
)

TSX_ROUTE_CALL = make_query(
    "tsx",
    """
(call_expression
  function: (member_expression
    object: (identifier) @obj
    property: (property_identifier) @method)
  arguments: (arguments
    .
    (string) @path)) @whole
""",
)

# ---------------------------------------------------------------------------
# Dangerous calls (child_process.* / eval)
# ---------------------------------------------------------------------------

JS_DANGEROUS_ATTR_CALL = make_query(
    "javascript",
    """
(call_expression
  function: (member_expression
    object: (identifier) @obj
    property: (property_identifier) @method)) @call
""",
)

JS_DANGEROUS_BARE_CALL = make_query(
    "javascript",
    """
(call_expression
  function: (identifier) @func
  (#eq? @func "eval")) @call
""",
)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

JS_IMPORTS = make_query(
    "javascript",
    """
(import_statement
  source: (string) @source)
""",
)

TS_IMPORTS = make_query(
    "typescript",
    """
(import_statement
  source: (string) @source)
""",
)


@dataclass(frozen=True)
class JsQuery:
    id: str
    query: Any
    intent: str
    grammar: str  # "javascript" | "typescript" | "tsx"
    mitigation_hint: str = ""


# The registry is keyed by grammar + purpose. ts_discovery picks the
# right set of entries based on the file's detected language.
QUERY_REGISTRY: dict[str, JsQuery] = {
    "javascript.entry.route_call": JsQuery(
        id="javascript.entry.route_call",
        query=JS_ROUTE_CALL,
        intent="decorator",
        grammar="javascript",
    ),
    "typescript.entry.route_call": JsQuery(
        id="typescript.entry.route_call",
        query=TS_ROUTE_CALL,
        intent="decorator",
        grammar="typescript",
    ),
    "tsx.entry.route_call": JsQuery(
        id="tsx.entry.route_call",
        query=TSX_ROUTE_CALL,
        intent="decorator",
        grammar="tsx",
    ),
    "javascript.sink.dangerous_attr": JsQuery(
        id="javascript.sink.dangerous_attr",
        query=JS_DANGEROUS_ATTR_CALL,
        intent="bare_call",
        grammar="javascript",
    ),
    "javascript.sink.dangerous_bare": JsQuery(
        id="javascript.sink.dangerous_bare",
        query=JS_DANGEROUS_BARE_CALL,
        intent="bare_call",
        grammar="javascript",
    ),
    "javascript.imports": JsQuery(
        id="javascript.imports",
        query=JS_IMPORTS,
        intent="import",
        grammar="javascript",
    ),
    "typescript.imports": JsQuery(
        id="typescript.imports",
        query=TS_IMPORTS,
        intent="import",
        grammar="typescript",
    ),
}


__all__ = [
    "JS_ROUTE_CALL",
    "TS_ROUTE_CALL",
    "TSX_ROUTE_CALL",
    "JS_DANGEROUS_ATTR_CALL",
    "JS_DANGEROUS_BARE_CALL",
    "JS_IMPORTS",
    "TS_IMPORTS",
    "JsQuery",
    "QUERY_REGISTRY",
]
