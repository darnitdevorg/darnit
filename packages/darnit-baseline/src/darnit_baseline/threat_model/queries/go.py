"""Tree-sitter queries for Go discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..parsing import make_query

# ---------------------------------------------------------------------------
# Entry point queries
# ---------------------------------------------------------------------------

#: HTTP handler registration: ``http.HandleFunc("/path", handler)`` and
#: chi/gorilla ``r.Get("/path", ...)``. We accept any
#: ``(obj.method(string, ...))`` shape and filter by ``method`` in the
#: extractor.
#: Captures: @obj @method @path @whole
GO_SELECTOR_STRING_ARG_CALL = make_query(
    "go",
    """
(call_expression
  function: (selector_expression
    operand: (identifier) @obj
    field: (field_identifier) @method)
  arguments: (argument_list
    .
    (interpreted_string_literal) @path)) @whole
""",
)

# ---------------------------------------------------------------------------
# Data store queries
# ---------------------------------------------------------------------------

#: sql.Open, sqlx.Open, gorm.Open with driver string as first argument.
#: Same shape as GO_SELECTOR_STRING_ARG_CALL but captured with a different
#: intent to distinguish data store calls from route registrations.
GO_SQL_OPEN = make_query(
    "go",
    """
(call_expression
  function: (selector_expression
    operand: (identifier) @pkg
    field: (field_identifier) @method)
  arguments: (argument_list
    .
    (interpreted_string_literal) @driver)) @whole
""",
)

# ---------------------------------------------------------------------------
# Import queries
# ---------------------------------------------------------------------------

GO_IMPORTS = make_query(
    "go",
    """
(import_spec
  path: (interpreted_string_literal) @path)
""",
)

# ---------------------------------------------------------------------------
# Call graph queries
# ---------------------------------------------------------------------------

GO_FUNCTION_DEFINITION = make_query(
    "go",
    """
(function_declaration
  name: (identifier) @func_name) @whole
""",
)


@dataclass(frozen=True)
class GoQuery:
    id: str
    query: Any
    intent: str
    mitigation_hint: str = ""


QUERY_REGISTRY: dict[str, GoQuery] = {
    "go.entry.selector_string_arg": GoQuery(
        id="go.entry.selector_string_arg",
        query=GO_SELECTOR_STRING_ARG_CALL,
        intent="decorator",
    ),
    "go.datastore.sql_open": GoQuery(
        id="go.datastore.sql_open",
        query=GO_SQL_OPEN,
        intent="constructor_call",
    ),
    "go.imports": GoQuery(
        id="go.imports",
        query=GO_IMPORTS,
        intent="import",
    ),
    "go.structure.function_def": GoQuery(
        id="go.structure.function_def",
        query=GO_FUNCTION_DEFINITION,
        intent="structural",
    ),
}


__all__ = [
    "GO_SELECTOR_STRING_ARG_CALL",
    "GO_SQL_OPEN",
    "GO_IMPORTS",
    "GO_FUNCTION_DEFINITION",
    "GoQuery",
    "QUERY_REGISTRY",
]
