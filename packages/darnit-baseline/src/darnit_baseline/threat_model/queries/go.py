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

# ---------------------------------------------------------------------------
# Cobra CLI command queries (feature 014-cobra-threat-model)
# ---------------------------------------------------------------------------

#: Match ``cobra.Command{Use: "...", RunE: ..., ...}`` composite literals.
#:
#: Captures the whole literal plus the ``cobra``/``Command`` type identifiers
#: so the extractor can confirm we're looking at cobra (and not a struct
#: in another package that happens to be named ``Command``). The Python
#: extractor walks the literal's ``literal_value`` children to extract
#: ``Use:``, ``Short:``, ``Long:``, ``RunE:``/``Run:`` field values.
#: Captures: @pkg @typename @body @whole
GO_COBRA_COMMAND_LITERAL = make_query(
    "go",
    """
(composite_literal
  type: (qualified_type
    package: (package_identifier) @pkg
    name: (type_identifier) @typename)
  body: (literal_value) @body) @whole
""",
)

#: Match ``func New() *cobra.Command { ... }``-style command constructors.
#:
#: Used as a coarse fallback for projects that wrap a command literal
#: inside a New-style factory and want the function itself surfaced as
#: an entry point (matched on by name). Deduplicated against
#: GO_COBRA_COMMAND_LITERAL captures by (file, line) — the literal wins
#: because it carries the Use: text.
#: Captures: @func_name @pkg @typename @whole
GO_COBRA_NEW_FUNC = make_query(
    "go",
    """
(function_declaration
  name: (identifier) @func_name
  result: (pointer_type
    (qualified_type
      package: (package_identifier) @pkg
      name: (type_identifier) @typename))) @whole
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
    "go.entry.cobra_command_literal": GoQuery(
        id="go.entry.cobra_command_literal",
        query=GO_COBRA_COMMAND_LITERAL,
        intent="decorator",
        mitigation_hint=(
            "Treat each cobra subcommand as an externally-reachable surface; "
            "validate inputs, scope side effects, and document permissions."
        ),
    ),
    "go.entry.cobra_new_func": GoQuery(
        id="go.entry.cobra_new_func",
        query=GO_COBRA_NEW_FUNC,
        intent="decorator",
        mitigation_hint=(
            "Cobra command constructor — verify the returned Command's "
            "RunE/Run dispatches to safely-validated logic."
        ),
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
    "GO_COBRA_COMMAND_LITERAL",
    "GO_COBRA_NEW_FUNC",
    "GoQuery",
    "QUERY_REGISTRY",
]
