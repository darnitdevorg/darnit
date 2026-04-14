"""Tree-sitter queries for Python discovery.

Every query is a module-level constant compiled once at import time. The
:data:`QUERY_REGISTRY` dict is the canonical lookup consumed by
:mod:`darnit_baseline.threat_model.ts_discovery`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..parsing import make_query

# ---------------------------------------------------------------------------
# Entry point queries
# ---------------------------------------------------------------------------

#: FastAPI / Flask style route decorator: ``@app.get("/path")`` etc.
#: Captures: @app @method @path @func_name @whole
DECORATED_ROUTE = make_query(
    "python",
    """
(decorated_definition
  (decorator
    (call
      function: (attribute
        object: (identifier) @app
        attribute: (identifier) @method)
      arguments: (argument_list . (string) @path)))
  definition: (function_definition
    name: (identifier) @func_name)) @whole
""",
)

#: Flask ``@app.route(path, methods=[...])`` variant — path is the first
#: string argument. We use the same shape as DECORATED_ROUTE and filter
#: ``method == "route"`` during extraction.
#: (Nothing new to compile; we reuse DECORATED_ROUTE and branch in
#: extraction. This constant is here for symmetry / future expansion.)
DECORATED_ROUTE_ROUTE_STYLE = DECORATED_ROUTE

#: MCP tool decorator: ``@server.tool(...)`` (FastMCP convention).
#: Captures: @server @tool @func_name @whole
MCP_TOOL_DECORATOR = make_query(
    "python",
    """
(decorated_definition
  (decorator
    (call
      function: (attribute
        object: (identifier) @server
        attribute: (identifier) @tool)))
  definition: (function_definition
    name: (identifier) @func_name)) @whole
""",
)

#: Imperative MCP tool registration: ``server.add_tool(handler, name=...)``
#: Captures: @obj @method @call
MCP_TOOL_IMPERATIVE = make_query(
    "python",
    """
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method)
  arguments: (argument_list)) @call
""",
)

#: Imperative HTTP route registration: ``app.add_url_rule(rule, endpoint, view_func)``
#: Captures: @obj @method @call
HTTP_ROUTE_IMPERATIVE = make_query(
    "python",
    """
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method)
  arguments: (argument_list)) @call
""",
)

# ---------------------------------------------------------------------------
# Subprocess / dangerous-call queries
# ---------------------------------------------------------------------------

#: subprocess.run / subprocess.call / subprocess.Popen / os.system / os.popen
#: Captures: @obj @method @call
DANGEROUS_ATTRIBUTE_CALL = make_query(
    "python",
    """
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method)) @call
""",
)

#: Bare eval/exec/compile calls.
#: Captures: @func @call
DANGEROUS_BARE_CALL = make_query(
    "python",
    """
(call
  function: (identifier) @func
  (#match? @func "^(eval|exec|compile)$")) @call
""",
)

# ---------------------------------------------------------------------------
# Data store queries
# ---------------------------------------------------------------------------

#: Matches any ``module.constructor(...)`` call; we filter by (obj, method)
#: pairs in the extractor because a single query covers sqlite3.connect,
#: psycopg.connect, redis.Redis, pymongo.MongoClient, boto3.client, and
#: SQLAlchemy create_engine.
#: Captures: @obj @method @call
DATASTORE_ATTRIBUTE_CALL = make_query(
    "python",
    """
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method)) @call
""",
)

#: Bare-call form of known datastore constructors. Matches any plain
#: ``Identifier(...)`` call; the extractor filters by function name against
#: a known constructor table AND cross-references imports to confirm the
#: symbol was brought in from a real datastore module. This is how we
#: catch the ``from redis import Redis; Redis()`` idiom.
#: Captures: @func @call
DATASTORE_BARE_CALL = make_query(
    "python",
    """
(call
  function: (identifier) @func) @call
""",
)

#: Legacy alias for backward compatibility — still available but no
#: longer registered in QUERY_REGISTRY.
DATASTORE_BARE_CREATE_ENGINE = DATASTORE_BARE_CALL

# ---------------------------------------------------------------------------
# Import queries — used for corroborating data-store findings
# ---------------------------------------------------------------------------

#: ``import X`` / ``import X.Y``. Captures: @name
IMPORT_PLAIN = make_query(
    "python",
    """
(import_statement
  name: (dotted_name) @name)
(import_statement
  name: (aliased_import
    name: (dotted_name) @name))
""",
)

#: ``from X import Y``. Captures: @module @imported
#: Each ``from X import Y, Z`` produces one match per imported name, so the
#: downstream extractor can build an ``imported_name → source_module`` map.
IMPORT_FROM = make_query(
    "python",
    """
(import_from_statement
  module_name: (dotted_name) @module
  name: (dotted_name) @imported)
(import_from_statement
  module_name: (dotted_name) @module
  name: (aliased_import
    name: (dotted_name) @imported))
(import_from_statement
  module_name: (relative_import) @module
  name: (dotted_name) @imported)
""",
)

# ---------------------------------------------------------------------------
# Information Disclosure queries
# ---------------------------------------------------------------------------

#: Broad exception handlers that might leak tracebacks or sensitive state.
#: Matches ``except Exception`` / bare ``except:`` blocks.
#: Captures: @handler @body
BROAD_EXCEPT = make_query(
    "python",
    """
(except_clause
  (identifier) @handler
  (block) @body)
""",
)

#: Open file calls — ``open(path)`` / ``open(path, mode)`` — that may read
#: arbitrary files without validation. Used for DoS (unbounded read) and
#: Information Disclosure (path traversal).
#: Captures: @func @call
OPEN_CALL = make_query(
    "python",
    """
(call
  function: (identifier) @func
  (#match? @func "^open$")) @call
""",
)

# ---------------------------------------------------------------------------
# Denial of Service queries
# ---------------------------------------------------------------------------

#: Attribute calls with no ``timeout`` keyword.  We match all attribute calls
#: and filter in the extractor for subprocess.run / requests.get / etc.
#: (Reuses DANGEROUS_ATTRIBUTE_CALL pattern — filtering is in the extractor.)

# ---------------------------------------------------------------------------
# Elevation of Privilege queries
# ---------------------------------------------------------------------------

#: Dynamic import: ``importlib.import_module(...)`` or ``__import__(...)``
#: Captures: @func @call  (bare form) or @obj @method @call  (attribute form)
DYNAMIC_IMPORT_ATTR = make_query(
    "python",
    """
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method)
  (#match? @obj "^importlib$")
  (#match? @method "^import_module$")) @call
""",
)

DYNAMIC_IMPORT_BARE = make_query(
    "python",
    """
(call
  function: (identifier) @func
  (#match? @func "^__import__$")) @call
""",
)

#: ``os.chmod`` / ``os.chown`` calls that modify file permissions.
#: Captures: @obj @method @call
PERMISSION_CHANGE = make_query(
    "python",
    """
(call
  function: (attribute
    object: (identifier) @obj
    attribute: (identifier) @method)
  (#match? @obj "^os$")
  (#match? @method "^(chmod|chown|setuid|setgid)$")) @call
""",
)

# ---------------------------------------------------------------------------
# Call graph queries
# ---------------------------------------------------------------------------

#: Top-level function definitions: ``def foo(...):``.
#: Captures: @func_name @body
FUNCTION_DEFINITION = make_query(
    "python",
    """
(function_definition
  name: (identifier) @func_name
  body: (block) @body) @whole
""",
)

#: Any call site inside a function body: ``f(...)`` or ``x.f(...)``.
#: Captures: @called_name
CALL_INSIDE_FUNCTION = make_query(
    "python",
    """
(call
  function: (identifier) @called_name)
(call
  function: (attribute
    attribute: (identifier) @called_name))
""",
)


# ---------------------------------------------------------------------------
# Query registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonQuery:
    """A named Python query with execution metadata."""

    id: str
    query: Any
    intent: str  # "decorator" | "constructor_call" | "bare_call" | "import" | "structural"
    mitigation_hint: str = ""


QUERY_REGISTRY: dict[str, PythonQuery] = {
    "python.entry.decorated_route": PythonQuery(
        id="python.entry.decorated_route",
        query=DECORATED_ROUTE,
        intent="decorator",
    ),
    "python.entry.mcp_tool": PythonQuery(
        id="python.entry.mcp_tool",
        query=MCP_TOOL_DECORATOR,
        intent="decorator",
    ),
    "python.entry.mcp_tool_imperative": PythonQuery(
        id="python.entry.mcp_tool_imperative",
        query=MCP_TOOL_IMPERATIVE,
        intent="constructor_call",
    ),
    "python.entry.http_route_imperative": PythonQuery(
        id="python.entry.http_route_imperative",
        query=HTTP_ROUTE_IMPERATIVE,
        intent="constructor_call",
    ),
    "python.sink.dangerous_attr": PythonQuery(
        id="python.sink.dangerous_attr",
        query=DANGEROUS_ATTRIBUTE_CALL,
        intent="bare_call",
    ),
    "python.sink.dangerous_bare": PythonQuery(
        id="python.sink.dangerous_bare",
        query=DANGEROUS_BARE_CALL,
        intent="bare_call",
    ),
    "python.datastore.attr": PythonQuery(
        id="python.datastore.attr",
        query=DATASTORE_ATTRIBUTE_CALL,
        intent="constructor_call",
    ),
    "python.datastore.bare_call": PythonQuery(
        id="python.datastore.bare_call",
        query=DATASTORE_BARE_CALL,
        intent="constructor_call",
    ),
    "python.imports.plain": PythonQuery(
        id="python.imports.plain",
        query=IMPORT_PLAIN,
        intent="import",
    ),
    "python.imports.from": PythonQuery(
        id="python.imports.from",
        query=IMPORT_FROM,
        intent="import",
    ),
    "python.structure.function_def": PythonQuery(
        id="python.structure.function_def",
        query=FUNCTION_DEFINITION,
        intent="structural",
    ),
    "python.structure.call_site": PythonQuery(
        id="python.structure.call_site",
        query=CALL_INSIDE_FUNCTION,
        intent="structural",
    ),
    # Information Disclosure
    "python.info_disc.broad_except": PythonQuery(
        id="python.info_disc.broad_except",
        query=BROAD_EXCEPT,
        intent="bare_call",
    ),
    "python.info_disc.open_call": PythonQuery(
        id="python.info_disc.open_call",
        query=OPEN_CALL,
        intent="bare_call",
    ),
    # Elevation of Privilege
    "python.eop.dynamic_import_attr": PythonQuery(
        id="python.eop.dynamic_import_attr",
        query=DYNAMIC_IMPORT_ATTR,
        intent="bare_call",
    ),
    "python.eop.dynamic_import_bare": PythonQuery(
        id="python.eop.dynamic_import_bare",
        query=DYNAMIC_IMPORT_BARE,
        intent="bare_call",
    ),
    "python.eop.permission_change": PythonQuery(
        id="python.eop.permission_change",
        query=PERMISSION_CHANGE,
        intent="bare_call",
    ),
}


__all__ = [
    "DECORATED_ROUTE",
    "MCP_TOOL_DECORATOR",
    "MCP_TOOL_IMPERATIVE",
    "HTTP_ROUTE_IMPERATIVE",
    "DANGEROUS_ATTRIBUTE_CALL",
    "DANGEROUS_BARE_CALL",
    "DATASTORE_ATTRIBUTE_CALL",
    "DATASTORE_BARE_CALL",
    "DATASTORE_BARE_CREATE_ENGINE",  # legacy alias
    "IMPORT_PLAIN",
    "IMPORT_FROM",
    "FUNCTION_DEFINITION",
    "CALL_INSIDE_FUNCTION",
    "BROAD_EXCEPT",
    "OPEN_CALL",
    "DYNAMIC_IMPORT_ATTR",
    "DYNAMIC_IMPORT_BARE",
    "PERMISSION_CHANGE",
    "PythonQuery",
    "QUERY_REGISTRY",
]
