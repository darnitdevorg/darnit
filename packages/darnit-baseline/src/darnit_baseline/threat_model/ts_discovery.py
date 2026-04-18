"""Tree-sitter based discovery pipeline.

Orchestrates tree-sitter queries across supported languages to produce the
asset/finding lists the rest of the threat-model pipeline consumes.

Every discovery function is pure — it takes parsed input and returns
dataclasses. File I/O happens once in ``discover_all``; individual
functions operate on already-loaded source bytes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import dependencies as deps_module
from .discovery_models import (
    CallGraphNode,
    CandidateFinding,
    CodeSnippet,
    DataFlowStep,
    DataFlowTrace,
    DataStoreKind,
    DiscoveredDataStore,
    DiscoveredEntryPoint,
    DiscoveryResult,
    EntryPointKind,
    FileScanStats,
    FindingSource,
    Location,
)
from .file_discovery import ScannedFile, walk_repo
from .models import StrideCategory
from .opengrep_runner import OpengrepResult, run_opengrep
from .parsing import node_text, parse_source, run_query
from .queries import go as go_queries
from .queries import javascript as js_queries
from .queries import python as py_queries
from .ranking import confidence_for, severity_for

logger = logging.getLogger("darnit_baseline.threat_model.ts_discovery")


# ---------------------------------------------------------------------------
# Sets used by extractors for filtering broad query matches
# ---------------------------------------------------------------------------

_HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options"}
)

#: Python ``obj.method`` pairs we treat as dangerous dynamic-execution sinks.
_PY_DANGEROUS_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("subprocess", "run"),
        ("subprocess", "call"),
        ("subprocess", "check_call"),
        ("subprocess", "check_output"),
        ("subprocess", "Popen"),
        ("os", "system"),
        ("os", "popen"),
    }
)

#: Python ``obj.method`` pairs that construct a real data store client
#: (the ``module.Constructor(...)`` idiom). Keys are the matched
#: ``(obj, method)``, values are ``(DataStoreKind, technology, import_hint)``
#: triples where ``import_hint`` is the module that must appear in the
#: file's imports or in its dependency manifest for the finding to be
#: emitted.
_PY_DATASTORE_CONSTRUCTORS: dict[tuple[str, str], tuple[DataStoreKind, str, str]] = {
    ("sqlite3", "connect"): (DataStoreKind.RELATIONAL_DB, "sqlite", "sqlite3"),
    ("psycopg", "connect"): (DataStoreKind.RELATIONAL_DB, "postgresql", "psycopg"),
    ("psycopg2", "connect"): (DataStoreKind.RELATIONAL_DB, "postgresql", "psycopg2"),
    ("asyncpg", "connect"): (DataStoreKind.RELATIONAL_DB, "postgresql", "asyncpg"),
    ("redis", "Redis"): (DataStoreKind.KEY_VALUE, "redis", "redis"),
    ("redis", "StrictRedis"): (DataStoreKind.KEY_VALUE, "redis", "redis"),
    ("aioredis", "from_url"): (DataStoreKind.KEY_VALUE, "redis", "aioredis"),
    ("pymongo", "MongoClient"): (DataStoreKind.DOCUMENT_DB, "mongodb", "pymongo"),
    ("boto3", "client"): (DataStoreKind.OBJECT_STORE, "aws", "boto3"),
    ("boto3", "resource"): (DataStoreKind.OBJECT_STORE, "aws", "boto3"),
}

#: Datastore constructors that are commonly imported via ``from X import Y``
#: and then called as a bare ``Y(...)``. Keys are the bare function name,
#: values are ``(DataStoreKind, technology, required_source_module)`` — the
#: extractor only emits a finding if the bare call's name was brought into
#: scope by an import from ``required_source_module``. This rules out
#: unrelated same-named calls in other modules.
_PY_DATASTORE_BARE_CONSTRUCTORS: dict[str, tuple[DataStoreKind, str, str]] = {
    "Redis": (DataStoreKind.KEY_VALUE, "redis", "redis"),
    "StrictRedis": (DataStoreKind.KEY_VALUE, "redis", "redis"),
    "MongoClient": (DataStoreKind.DOCUMENT_DB, "mongodb", "pymongo"),
    "create_engine": (DataStoreKind.RELATIONAL_DB, "sqlalchemy", "sqlalchemy"),
}

#: Python framework identifiers that mark a module's HTTP app as a
#: particular framework. Keys are module names that must appear in the
#: file's imports; values are the canonical framework identifier set on
#: ``DiscoveredEntryPoint.framework``.
_PY_HTTP_FRAMEWORK_MODULES: dict[str, str] = {
    "fastapi": "fastapi",
    "flask": "flask",
    "starlette": "starlette",
    "aiohttp": "aiohttp",
    "sanic": "sanic",
}

#: Go ``(pkg, method)`` pairs treated as HTTP handler registration.
_GO_HTTP_HANDLER_METHODS: frozenset[str] = frozenset(
    {
        "HandleFunc",
        "Handle",
        "Get",
        "Post",
        "Put",
        "Delete",
        "Patch",
        "Options",
        "Head",
    }
)

#: Go ``(pkg, method)`` pairs that open a SQL connection. The first string
#: argument is the driver, which doubles as the technology identifier.
_GO_DB_OPEN_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {("sql", "Open"), ("sqlx", "Open"), ("gorm", "Open")}
)

_GO_DRIVER_TO_TECH: dict[str, tuple[DataStoreKind, str]] = {
    "postgres": (DataStoreKind.RELATIONAL_DB, "postgresql"),
    "postgresql": (DataStoreKind.RELATIONAL_DB, "postgresql"),
    "mysql": (DataStoreKind.RELATIONAL_DB, "mysql"),
    "sqlite3": (DataStoreKind.RELATIONAL_DB, "sqlite"),
    "sqlite": (DataStoreKind.RELATIONAL_DB, "sqlite"),
}


# ---------------------------------------------------------------------------
# Snippet / location helpers
# ---------------------------------------------------------------------------


def _build_location(node: Any, relpath: str) -> Location:
    return Location(
        file=relpath,
        line=node.start_point[0] + 1,
        column=node.start_point[1] + 1,
        end_line=node.end_point[0] + 1,
        end_column=node.end_point[1] + 1,
    )


def _build_snippet(source: bytes, marker_line: int, context_lines: int = 10) -> CodeSnippet:
    """Extract a ±context_lines window around ``marker_line``.

    ``marker_line`` is 1-indexed. The returned ``CodeSnippet`` invariants
    require ``start_line <= marker_line < start_line + len(lines)``.
    """
    all_lines = source.decode("utf-8", errors="replace").splitlines()
    if not all_lines:
        # File is empty; synthesize a single empty line so the snippet is valid
        return CodeSnippet(lines=("",), start_line=1, marker_line=1)

    marker_0 = marker_line - 1
    start_0 = max(0, marker_0 - context_lines)
    end_0 = min(len(all_lines), marker_0 + context_lines + 1)
    lines = tuple(all_lines[start_0:end_0])
    start_line = start_0 + 1
    # Guard against an out-of-range marker (e.g., a query that pointed past
    # the file's last line because the file lacks a trailing newline).
    if marker_line >= start_line + len(lines):
        marker_line = start_line + len(lines) - 1
    return CodeSnippet(lines=lines, start_line=start_line, marker_line=marker_line)


def _text(node: Any, source: bytes) -> str:
    return node_text(node, source)


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"', "`"):
        return text[1:-1]
    return text


def _extract_kwarg(call_node: Any, kwarg_name: str, source: bytes) -> str | None:
    """Extract the string value of a keyword argument from a call node.

    Given ``f(a, name="foo")``, ``_extract_kwarg(node, "name", src)``
    returns ``"foo"``. Returns ``None`` if the keyword is absent or its
    value is not a string literal.
    """
    for child in call_node.children:
        if child.type == "argument_list":
            for arg in child.children:
                if arg.type == "keyword_argument":
                    key_node = arg.child_by_field_name("name")
                    val_node = arg.child_by_field_name("value")
                    if key_node and val_node and _text(key_node, source) == kwarg_name:
                        val_text = _text(val_node, source)
                        stripped = _strip_quotes(val_text)
                        if stripped != val_text:
                            return stripped
                        # Value is an identifier (variable reference) — return it
                        if val_node.type == "identifier":
                            return val_text
    return None


def _is_kwarg_string_literal(call_node: Any, kwarg_name: str, source: bytes) -> bool:
    """Return True if the named kwarg exists and its value is a string literal."""
    for child in call_node.children:
        if child.type == "argument_list":
            for arg in child.children:
                if arg.type == "keyword_argument":
                    key_node = arg.child_by_field_name("name")
                    val_node = arg.child_by_field_name("value")
                    if key_node and val_node and _text(key_node, source) == kwarg_name:
                        val_text = _text(val_node, source)
                        return _strip_quotes(val_text) != val_text
    return False


def _find_enclosing_for_loop(node: Any) -> Any | None:
    """Walk parent chain to find an enclosing ``for_statement``, if any."""
    cursor = node.parent
    while cursor is not None:
        if cursor.type == "for_statement":
            return cursor
        cursor = cursor.parent
    return None


def _describe_for_loop_iterable(for_node: Any, source: bytes) -> str | None:
    """Extract a human-readable label from a for-loop's iterable.

    For ``for name, spec in registry.tools.items():``, returns
    ``"registry.tools"``.  Returns ``None`` on unrecognised shapes.
    """
    # The iterable is the right-hand side of ``in``
    # In tree-sitter python grammar: for_statement has fields "left" and "right"
    right = for_node.child_by_field_name("right")
    if right is None:
        return None
    text = _text(right, source)
    # Strip common iterator suffixes
    for suffix in (".items()", ".keys()", ".values()", ".entries()"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _extract_first_positional_arg(call_node: Any, source: bytes) -> str | None:
    """Return the text of the first positional (non-keyword) argument.

    For ``f(handler, name="x")``, returns ``"handler"``.
    """
    for child in call_node.children:
        if child.type == "argument_list":
            for arg in child.children:
                if arg.type not in ("keyword_argument", ",", "(", ")"):
                    return _text(arg, source)
    return None


def _extract_nth_positional_arg(
    call_node: Any, n: int, source: bytes
) -> str | None:
    """Return the text of the *n*-th positional (non-keyword) argument (0-indexed)."""
    idx = 0
    for child in call_node.children:
        if child.type == "argument_list":
            for arg in child.children:
                if arg.type not in ("keyword_argument", ",", "(", ")"):
                    if idx == n:
                        return _text(arg, source)
                    idx += 1
    return None


def _extract_first_positional_string(
    call_node: Any, source: bytes
) -> str | None:
    """Return the unquoted value of the first positional string literal argument."""
    for child in call_node.children:
        if child.type == "argument_list":
            for arg in child.children:
                if arg.type == "string":
                    return _strip_quotes(_text(arg, source))
    return None


# ---------------------------------------------------------------------------
# Python extractors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PythonImports:
    """AST-derived import information for a single Python file.

    ``modules`` is the set of top-level module names imported via plain
    ``import X`` or ``from X import ...`` statements.

    ``bare_to_module`` maps the name that was brought into scope via
    ``from X import Y`` (or its ``as Z`` alias) to its source module.
    Example: ``from redis import Redis`` → ``{"Redis": "redis"}``.
    """

    modules: frozenset[str]
    bare_to_module: dict[str, str]


def _collect_python_imports(source: bytes, tree: Any) -> _PythonImports:
    """Return AST-derived import information for a Python file.

    Replaces the previous ``set[str]``-returning helper; now also populates
    the ``bare_to_module`` mapping that the data-store extractor needs to
    resolve ``from X import Y; Y(...)`` style usage.
    """
    modules: set[str] = set()
    bare_to_module: dict[str, str] = {}

    for caps in run_query(
        py_queries.QUERY_REGISTRY["python.imports.plain"].query, tree.root_node
    ):
        for node in caps.get("name", []):
            text = _text(node, source)
            modules.add(text.split(".", 1)[0])

    for caps in run_query(
        py_queries.QUERY_REGISTRY["python.imports.from"].query, tree.root_node
    ):
        for node in caps.get("module", []):
            text = _text(node, source)
            modules.add(text.split(".", 1)[0])
        module_nodes = caps.get("module", [])
        imported_nodes = caps.get("imported", [])
        if not module_nodes or not imported_nodes:
            continue
        module_name = _text(module_nodes[0], source).split(".", 1)[0]
        for imp_node in imported_nodes:
            imp_name = _text(imp_node, source).split(".", 1)[0]
            bare_to_module[imp_name] = module_name

    return _PythonImports(
        modules=frozenset(modules),
        bare_to_module=bare_to_module,
    )


def _extract_python_entry_points(
    file: ScannedFile,
    source: bytes,
    tree: Any,
    imports: _PythonImports,
) -> list[DiscoveredEntryPoint]:
    entries: list[DiscoveredEntryPoint] = []

    # FastAPI / Flask style: @app.get("/path") / @app.route("/path")
    query = py_queries.QUERY_REGISTRY["python.entry.decorated_route"].query
    for caps in run_query(query, tree.root_node):
        method = _text(caps["method"][0], source)
        whole = caps["whole"][0]
        func_name = _text(caps["func_name"][0], source)
        path_raw = _text(caps["path"][0], source)
        path = _strip_quotes(path_raw)

        if method in _HTTP_METHODS:
            framework = _infer_python_http_framework(imports)
            entries.append(
                DiscoveredEntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    name=func_name,
                    location=_build_location(whole, file.relpath),
                    language="python",
                    framework=framework,
                    route_path=path,
                    http_method=method.upper(),
                    has_auth_decorator=False,
                    source_query="python.entry.decorated_route",
                )
            )
        elif method == "route":
            # Flask-style; the route is always the first string argument.
            entries.append(
                DiscoveredEntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    name=func_name,
                    location=_build_location(whole, file.relpath),
                    language="python",
                    framework="flask",
                    route_path=path,
                    http_method=None,
                    has_auth_decorator=False,
                    source_query="python.entry.decorated_route",
                )
            )

    # MCP tool decorator: @server.tool(...)
    query = py_queries.QUERY_REGISTRY["python.entry.mcp_tool"].query
    for caps in run_query(query, tree.root_node):
        tool_attr = _text(caps["tool"][0], source)
        if tool_attr != "tool":
            continue
        whole = caps["whole"][0]
        func_name = _text(caps["func_name"][0], source)
        entries.append(
            DiscoveredEntryPoint(
                kind=EntryPointKind.MCP_TOOL,
                name=func_name,
                location=_build_location(whole, file.relpath),
                language="python",
                framework="mcp",
                route_path=None,
                http_method=None,
                has_auth_decorator=False,
                source_query="python.entry.mcp_tool",
            )
        )

    # Imperative MCP tool registration: server.add_tool(handler, name=...)
    query = py_queries.QUERY_REGISTRY["python.entry.mcp_tool_imperative"].query
    # Track for-loop–based registrations to emit one entry per loop, not per
    # match (the loop body matches N times but represents one registration site
    # that produces M tools at runtime).
    _seen_loop_sites: set[int] = set()
    for caps in run_query(query, tree.root_node):
        method = _text(caps["method"][0], source)
        if method != "add_tool":
            continue
        call_node = caps["call"][0]

        # Check whether the name kwarg is a string literal vs. a variable.
        is_literal = _is_kwarg_string_literal(call_node, "name", source)
        tool_name = _extract_kwarg(call_node, "name", source)
        if tool_name is None:
            tool_name = _extract_first_positional_arg(call_node, source)
        if tool_name is None:
            continue

        if is_literal:
            # Static name — one entry point per call site.
            entries.append(
                DiscoveredEntryPoint(
                    kind=EntryPointKind.MCP_TOOL,
                    name=tool_name,
                    location=_build_location(call_node, file.relpath),
                    language="python",
                    framework="mcp",
                    route_path=None,
                    http_method=None,
                    has_auth_decorator=False,
                    source_query="python.entry.mcp_tool_imperative",
                )
            )
        else:
            # Dynamic name (variable) — likely inside a for-loop registering
            # multiple tools from a registry/dict.  Emit one entry per loop
            # site rather than duplicating for each tree-sitter match.
            for_loop = _find_enclosing_for_loop(call_node)
            if for_loop is not None:
                loop_id = for_loop.start_point[0]  # line number
                if loop_id in _seen_loop_sites:
                    continue  # already emitted for this loop
                _seen_loop_sites.add(loop_id)
                iterable = _describe_for_loop_iterable(for_loop, source)
                label = (
                    f"(dynamic — registered from {iterable})"
                    if iterable
                    else "(dynamic — loop registration)"
                )
            else:
                label = f"(dynamic: {tool_name})"

            entries.append(
                DiscoveredEntryPoint(
                    kind=EntryPointKind.MCP_TOOL,
                    name=label,
                    location=_build_location(call_node, file.relpath),
                    language="python",
                    framework="mcp",
                    route_path=None,
                    http_method=None,
                    has_auth_decorator=False,
                    source_query="python.entry.mcp_tool_imperative",
                )
            )

    # Imperative HTTP route registration: app.add_url_rule / app.add_route
    query = py_queries.QUERY_REGISTRY["python.entry.http_route_imperative"].query
    for caps in run_query(query, tree.root_node):
        method = _text(caps["method"][0], source)
        if method not in ("add_url_rule", "add_route"):
            continue
        call_node = caps["call"][0]
        route_path = _extract_first_positional_string(call_node, source)
        if route_path is None:
            continue
        framework = _infer_python_http_framework(imports)
        # Try to extract the endpoint name from kwargs or positional args
        endpoint_name = _extract_kwarg(call_node, "endpoint", source)
        if endpoint_name is None:
            endpoint_name = _extract_kwarg(call_node, "view_func", source)
        if endpoint_name is None:
            # Second positional arg is often the endpoint name
            endpoint_name = _extract_nth_positional_arg(call_node, 1, source)
        if endpoint_name is None:
            endpoint_name = route_path
        entries.append(
            DiscoveredEntryPoint(
                kind=EntryPointKind.HTTP_ROUTE,
                name=endpoint_name,
                location=_build_location(call_node, file.relpath),
                language="python",
                framework=framework,
                route_path=route_path,
                http_method=None,
                has_auth_decorator=False,
                source_query="python.entry.http_route_imperative",
            )
        )

    return entries


def _infer_python_http_framework(imports: _PythonImports) -> str:
    """Return the canonical framework name based on AST-resolved imports.

    Replaces the old substring-based search which could match the
    framework's name inside a docstring or comment — exactly the class of
    false positive this rewrite exists to eliminate.
    """
    for module, canonical in _PY_HTTP_FRAMEWORK_MODULES.items():
        if module in imports.modules:
            return canonical
    return "http"


def _extract_python_data_stores(
    file: ScannedFile,
    source: bytes,
    tree: Any,
    imports: _PythonImports,
    dependency_names: set[str],
) -> list[DiscoveredDataStore]:
    stores: list[DiscoveredDataStore] = []
    seen_locations: set[tuple[int, int]] = set()

    def _maybe_append(store: DiscoveredDataStore) -> None:
        # Dedupe in case the same call is matched by both the attribute and
        # bare-call queries (shouldn't happen structurally, but belt-and-
        # suspenders against future query changes).
        key = (store.location.line, store.location.column)
        if key in seen_locations:
            return
        seen_locations.add(key)
        stores.append(store)

    # Attribute form: redis.Redis(...), sqlite3.connect(...), etc.
    attr_query = py_queries.QUERY_REGISTRY["python.datastore.attr"].query
    for caps in run_query(attr_query, tree.root_node):
        obj = _text(caps["obj"][0], source)
        method = _text(caps["method"][0], source)
        call_node = caps["call"][0]
        key = (obj, method)
        if key not in _PY_DATASTORE_CONSTRUCTORS:
            continue
        kind, tech, import_hint = _PY_DATASTORE_CONSTRUCTORS[key]
        import_evidence: str | None = (
            import_hint if import_hint in imports.modules else None
        )
        manifest_evidence: str | None = (
            import_hint if import_hint in dependency_names else None
        )
        if import_evidence is None and manifest_evidence is None:
            continue
        _maybe_append(
            DiscoveredDataStore(
                kind=kind,
                technology=tech,
                location=_build_location(call_node, file.relpath),
                language="python",
                import_evidence=import_evidence,
                dependency_manifest_evidence=manifest_evidence,
                source_query="python.datastore.attr",
            )
        )

    # Bare form: Redis(...), MongoClient(...), create_engine(...) after
    # ``from redis import Redis`` / ``from pymongo import MongoClient`` /
    # ``from sqlalchemy import create_engine``.
    bare_query = py_queries.QUERY_REGISTRY["python.datastore.bare_call"].query
    for caps in run_query(bare_query, tree.root_node):
        func_name = _text(caps["func"][0], source)
        if func_name not in _PY_DATASTORE_BARE_CONSTRUCTORS:
            continue
        kind, tech, source_module = _PY_DATASTORE_BARE_CONSTRUCTORS[func_name]
        # The symbol must have been imported from the expected module.
        imported_from = imports.bare_to_module.get(func_name)
        if imported_from != source_module:
            continue
        call_node = caps["call"][0]
        import_evidence: str | None = source_module
        manifest_evidence: str | None = (
            source_module if source_module in dependency_names else None
        )
        _maybe_append(
            DiscoveredDataStore(
                kind=kind,
                technology=tech,
                location=_build_location(call_node, file.relpath),
                language="python",
                import_evidence=import_evidence,
                dependency_manifest_evidence=manifest_evidence,
                source_query="python.datastore.bare_call",
            )
        )

    return stores


def _classify_subprocess_arg_shape(call_node: Any, source: bytes) -> str:
    """Classify a subprocess call into a risk tier based on argument shape.

    Returns one of:
    - ``"shell"``  — ``shell=True`` is present (always highest risk)
    - ``"dynamic"`` — first arg is a bare variable, function call, or any
      non-list expression
    - ``"parameterized"`` — first arg is a list literal containing at least
      one non-literal element (variable, f-string, call expression)
    - ``"static"`` — first arg is a list literal with ALL string literal
      elements (no variables, no f-strings)
    """
    args = call_node.child_by_field_name("arguments")
    if args is None:
        return "dynamic"

    first_positional: Any | None = None
    has_shell_true = False

    for child in args.named_children:
        if child.type == "comment":
            continue  # skip inline noqa / type: ignore comments
        if child.type == "keyword_argument":
            key_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")
            if key_node is None or value_node is None:
                continue
            key_text = _text(key_node, source)
            value_text = _text(value_node, source)
            if key_text == "shell" and value_text == "True":
                has_shell_true = True
            continue
        if first_positional is None:
            first_positional = child

    if has_shell_true:
        return "shell"
    if first_positional is None:
        return "dynamic"
    if first_positional.type != "list":
        return "dynamic"
    # List literal — check whether all elements are string literals.
    for item in first_positional.named_children:
        if item.type != "string":
            return "parameterized"
    return "static"


def _is_config_driven_subprocess(
    call_node: Any, source: bytes, tree: Any
) -> bool:
    """Check if a subprocess call's command argument was populated from config/dict.

    Heuristic: the first argument to the subprocess call is a variable, and
    within the same function scope, that variable is assigned from:
    - A dict subscript: ``config["key"]`` or ``config.get("key")``
    - A loop over a dict: ``for x in config.items()``
    - An extend/append from config values

    This catches patterns like::

        cmd = config["command"]
        subprocess.run(cmd, ...)

    and::

        for arg in command:
            resolved_cmd.append(arg.replace(var, val))
        subprocess.run(resolved_cmd, ...)
    """
    # 1. Get first positional argument of the subprocess call.
    args = call_node.child_by_field_name("arguments")
    if args is None:
        return False

    first_positional: Any | None = None
    for child in args.named_children:
        if child.type == "keyword_argument":
            continue
        first_positional = child
        break

    if first_positional is None or first_positional.type != "identifier":
        return False

    var_name = _text(first_positional, source)

    # 2. Find the enclosing function_definition node.
    enclosing_func: Any | None = call_node.parent
    while enclosing_func is not None and enclosing_func.type != "function_definition":
        enclosing_func = enclosing_func.parent
    if enclosing_func is None:
        return False

    body = enclosing_func.child_by_field_name("body")
    if body is None:
        return False

    # 3. Walk the function body looking for dict-related assignments to var_name.
    return _body_has_config_assignment(body, var_name, source)


def _body_has_config_assignment(body: Any, var_name: str, source: bytes) -> bool:
    """Walk *body* for assignments to *var_name* that originate from a dict.

    Also handles one level of transitivity: if ``full_cmd = [cmd] + args``
    and ``cmd = config["command"]``, the function recognises that
    ``full_cmd`` is indirectly config-derived.
    """
    _DICT_METHODS = frozenset({"get", "items", "values", "keys", "pop"})
    _LIST_MUTATORS = frozenset({"extend", "append"})

    # Pass 1: collect all local variable names that are directly assigned
    # from a dict access expression (e.g. ``cmd = config["command"]``).
    config_vars: set[str] = set()
    for node in _walk_descendants(body):
        if node.type in ("assignment", "augmented_assignment"):
            lhs = node.child_by_field_name("left")
            rhs = node.child_by_field_name("right")
            if lhs is None or rhs is None:
                continue
            if lhs.type != "identifier":
                continue
            if _is_dict_access_expr(rhs, source, _DICT_METHODS):
                config_vars.add(_text(lhs, source))

    # Direct match: the subprocess argument variable itself is config-derived.
    if var_name in config_vars:
        return True

    # Pass 2: walk the body again looking for patterns that link var_name
    # to config_vars (transitive) or to dict-like iteration/mutation.
    for node in _walk_descendants(body):
        # --- assignment: var_name = <rhs> ---
        if node.type in ("assignment", "augmented_assignment"):
            lhs = node.child_by_field_name("left")
            rhs = node.child_by_field_name("right")
            if lhs is None or rhs is None:
                continue
            if _text(lhs, source) != var_name:
                continue
            # Direct dict access on RHS.
            if _is_dict_access_expr(rhs, source, _DICT_METHODS):
                return True
            # Transitive: RHS references a variable known to be config-derived.
            if config_vars and _rhs_references_config_vars(
                rhs, source, config_vars
            ):
                return True

        # --- for ... in <expr>.items() / for ... in config ---
        if node.type == "for_statement":
            right = node.child_by_field_name("right")
            if right is not None and _is_dict_access_expr(
                right, source, _DICT_METHODS
            ):
                return True

        # --- var.append(config[...]) / var.extend(config.values()) ---
        if node.type == "expression_statement":
            expr = node.named_children[0] if node.named_children else None
            if expr is not None and expr.type == "call":
                func_node = expr.child_by_field_name("function")
                if func_node is not None and func_node.type == "attribute":
                    obj_node = func_node.child_by_field_name("object")
                    attr_node = func_node.child_by_field_name("attribute")
                    if (
                        obj_node is not None
                        and attr_node is not None
                        and _text(obj_node, source) == var_name
                        and _text(attr_node, source) in _LIST_MUTATORS
                    ):
                        call_args = expr.child_by_field_name("arguments")
                        if call_args is not None:
                            for arg in call_args.named_children:
                                if _is_dict_access_expr(
                                    arg, source, _DICT_METHODS
                                ):
                                    return True

    return False


def _rhs_references_config_vars(
    node: Any, source: bytes, config_vars: set[str]
) -> bool:
    """Return True if *node* (an RHS expression) contains any identifier
    that appears in *config_vars*."""
    if node.type == "identifier" and _text(node, source) in config_vars:
        return True
    for child in node.children:
        if _rhs_references_config_vars(child, source, config_vars):
            return True
    return False


def _is_dict_access_expr(
    node: Any, source: bytes, dict_methods: frozenset[str]
) -> bool:
    """Return True if *node* looks like a dict access expression.

    Matches:
    - subscript: ``config["key"]``
    - attribute call: ``config.get("key")`` / ``.items()`` / ``.values()``
    """
    if node.type == "subscript":
        return True
    if node.type == "call":
        func = node.child_by_field_name("function")
        if func is not None and func.type == "attribute":
            attr = func.child_by_field_name("attribute")
            if attr is not None and _text(attr, source) in dict_methods:
                return True
    return False


def _walk_descendants(node: Any):
    """Yield all descendant nodes of *node* in pre-order."""
    for child in node.children:
        yield child
        yield from _walk_descendants(child)


def _extract_python_subprocess_findings(
    file: ScannedFile, source: bytes, tree: Any
) -> list[CandidateFinding]:
    findings: list[CandidateFinding] = []

    # subprocess.run / os.system etc.
    attr_query = py_queries.QUERY_REGISTRY["python.sink.dangerous_attr"].query
    for caps in run_query(attr_query, tree.root_node):
        obj = _text(caps["obj"][0], source)
        method = _text(caps["method"][0], source)
        if (obj, method) not in _PY_DANGEROUS_PAIRS:
            continue
        call_node = caps["call"][0]
        tier = _classify_subprocess_arg_shape(call_node, source)
        location = _build_location(call_node, file.relpath)

        # Elevate confidence when the command argument originates from a
        # config/dict lookup — this is a well-known attack surface for
        # TOML-driven command construction.
        config_driven = tier == "dynamic" and _is_config_driven_subprocess(
            call_node, source, tree
        )

        findings.append(
            _build_subprocess_finding(
                source,
                location,
                title=f"Potential command injection via {obj}.{method}",
                query_id="python.sink.dangerous_attr",
                tier=tier,
                config_driven=config_driven,
            )
        )

    # Bare eval/exec/compile — these are Elevation of Privilege (arbitrary
    # code execution), not Tampering (data modification). Still emitted at
    # low confidence until Opengrep taint can confirm external input flow.
    bare_query = py_queries.QUERY_REGISTRY["python.sink.dangerous_bare"].query
    for caps in run_query(bare_query, tree.root_node):
        func = _text(caps["func"][0], source)
        call_node = caps["call"][0]
        location = _build_location(call_node, file.relpath)
        snippet = _build_snippet(source, location.line)
        severity = severity_for(
            StrideCategory.ELEVATION_OF_PRIVILEGE, has_taint_trace=False
        )
        confidence = confidence_for(
            FindingSource.TREE_SITTER_STRUCTURAL,
            query_intent="dangerous_sink_no_taint",
        )
        findings.append(
            CandidateFinding(
                category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                title=f"Dynamic code execution via {func}()",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=location,
                related_assets=(),
                code_snippet=snippet,
                severity=severity,
                confidence=confidence,
                rationale=(
                    f"Call to {func}() detected. This enables arbitrary code "
                    "execution if the argument is influenced by external input. "
                    "Opengrep taint analysis can confirm or dismiss this finding."
                ),
                query_id="python.sink.dangerous_bare",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Additional STRIDE category extractors
# ---------------------------------------------------------------------------

#: Broad exception handler types that may leak sensitive state.
_BROAD_EXCEPT_TYPES = frozenset({"Exception", "BaseException"})

#: Known subprocess/network calls that should have timeouts.
_TIMEOUT_EXPECTED_CALLS = frozenset({
    ("subprocess", "run"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("subprocess", "Popen"),
    ("requests", "get"),
    ("requests", "post"),
    ("requests", "put"),
    ("requests", "delete"),
    ("requests", "patch"),
    ("requests", "request"),
    ("urllib", "urlopen"),
    ("httpx", "get"),
    ("httpx", "post"),
})


def _has_timeout_kwarg(call_node: Any, source: bytes) -> bool:
    """Check if a call node has a ``timeout=`` keyword argument."""
    for child in call_node.children:
        if child.type == "argument_list":
            for arg in child.children:
                if arg.type == "keyword_argument":
                    key_node = arg.child_by_field_name("name")
                    if key_node and _text(key_node, source) == "timeout":
                        return True
    return False


def _extract_python_info_disclosure_findings(
    file: ScannedFile, source: bytes, tree: Any
) -> list[CandidateFinding]:
    """Detect patterns that may leak sensitive information."""
    findings: list[CandidateFinding] = []

    # Broad exception handlers (except Exception / bare except)
    query = py_queries.QUERY_REGISTRY["python.info_disc.broad_except"].query
    for caps in run_query(query, tree.root_node):
        handler_type = _text(caps["handler"][0], source)
        if handler_type not in _BROAD_EXCEPT_TYPES:
            continue
        body_node = caps["body"][0]
        body_text = _text(body_node, source)
        # Only flag if the handler re-raises or returns the exception
        # (potential traceback leak). Skip handlers that just log.
        if "traceback" in body_text or "str(e)" in body_text or "repr(e)" in body_text:
            location = _build_location(caps["handler"][0], file.relpath)
            snippet = _build_snippet(source, location.line)
            findings.append(
                CandidateFinding(
                    category=StrideCategory.INFORMATION_DISCLOSURE,
                    title=f"Broad except {handler_type} may leak error details",
                    source=FindingSource.TREE_SITTER_STRUCTURAL,
                    primary_location=location,
                    related_assets=(),
                    code_snippet=snippet,
                    severity=severity_for(
                        StrideCategory.INFORMATION_DISCLOSURE,
                        has_taint_trace=False,
                    ),
                    confidence=0.5,
                    rationale=(
                        f"A broad ``except {handler_type}`` handler exposes "
                        "exception details (traceback, str(e), or repr(e)). "
                        "In production, this may leak internal file paths, "
                        "stack frames, or sensitive state to callers."
                    ),
                    query_id="python.info_disc.broad_except",
                )
            )

    # open() with variable path — potential path traversal
    query = py_queries.QUERY_REGISTRY["python.info_disc.open_call"].query
    for caps in run_query(query, tree.root_node):
        call_node = caps["call"][0]
        first_arg = _extract_first_positional_arg(call_node, source)
        if first_arg is None:
            continue
        # Only flag when the argument is a variable (not a string literal)
        stripped = _strip_quotes(first_arg)
        if stripped != first_arg:
            continue  # string literal — not interesting
        location = _build_location(call_node, file.relpath)
        snippet = _build_snippet(source, location.line)
        findings.append(
            CandidateFinding(
                category=StrideCategory.INFORMATION_DISCLOSURE,
                title=f"File open with variable path: {first_arg}",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=location,
                related_assets=(),
                code_snippet=snippet,
                severity=severity_for(
                    StrideCategory.INFORMATION_DISCLOSURE,
                    has_taint_trace=False,
                ),
                confidence=0.4,
                rationale=(
                    f"``open({first_arg})`` uses a variable path. If the path "
                    "originates from user input without validation, this "
                    "enables path traversal attacks (reading arbitrary files)."
                ),
                query_id="python.info_disc.open_call",
            )
        )

    return findings


def _extract_python_dos_findings(
    file: ScannedFile, source: bytes, tree: Any
) -> list[CandidateFinding]:
    """Detect patterns that may cause denial of service."""
    findings: list[CandidateFinding] = []

    # subprocess / network calls without timeout
    attr_query = py_queries.QUERY_REGISTRY["python.sink.dangerous_attr"].query
    for caps in run_query(attr_query, tree.root_node):
        obj = _text(caps["obj"][0], source)
        method = _text(caps["method"][0], source)
        if (obj, method) not in _TIMEOUT_EXPECTED_CALLS:
            continue
        call_node = caps["call"][0]
        if _has_timeout_kwarg(call_node, source):
            continue  # timeout present — not a DoS concern
        location = _build_location(call_node, file.relpath)
        snippet = _build_snippet(source, location.line)
        findings.append(
            CandidateFinding(
                category=StrideCategory.DENIAL_OF_SERVICE,
                title=f"No timeout on {obj}.{method}()",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=location,
                related_assets=(),
                code_snippet=snippet,
                severity=severity_for(
                    StrideCategory.DENIAL_OF_SERVICE, has_taint_trace=False
                ),
                confidence=0.6,
                rationale=(
                    f"``{obj}.{method}()`` is called without a ``timeout`` "
                    "parameter. A hung subprocess or unresponsive network "
                    "endpoint will block the caller indefinitely, which can "
                    "be exploited for denial of service."
                ),
                query_id="python.sink.dangerous_attr",
            )
        )

    return findings


def _extract_python_eop_findings(
    file: ScannedFile, source: bytes, tree: Any
) -> list[CandidateFinding]:
    """Detect elevation of privilege patterns beyond eval/exec."""
    findings: list[CandidateFinding] = []

    # Dynamic import: importlib.import_module(...)
    query = py_queries.QUERY_REGISTRY["python.eop.dynamic_import_attr"].query
    for caps in run_query(query, tree.root_node):
        call_node = caps["call"][0]
        first_arg = _extract_first_positional_arg(call_node, source)
        arg_label = first_arg or "..."
        # Only interesting if argument is a variable, not a literal
        if first_arg and _strip_quotes(first_arg) != first_arg:
            continue
        location = _build_location(call_node, file.relpath)
        snippet = _build_snippet(source, location.line)
        findings.append(
            CandidateFinding(
                category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                title=f"Dynamic import via importlib.import_module({arg_label})",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=location,
                related_assets=(),
                code_snippet=snippet,
                severity=severity_for(
                    StrideCategory.ELEVATION_OF_PRIVILEGE,
                    has_taint_trace=False,
                ),
                confidence=0.5,
                rationale=(
                    "Dynamic imports allow loading arbitrary modules at "
                    "runtime. If the module name originates from untrusted "
                    "input, an attacker can achieve arbitrary code execution."
                ),
                query_id="python.eop.dynamic_import_attr",
            )
        )

    # __import__(...)
    query = py_queries.QUERY_REGISTRY["python.eop.dynamic_import_bare"].query
    for caps in run_query(query, tree.root_node):
        call_node = caps["call"][0]
        location = _build_location(call_node, file.relpath)
        snippet = _build_snippet(source, location.line)
        findings.append(
            CandidateFinding(
                category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                title="Dynamic import via __import__()",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=location,
                related_assets=(),
                code_snippet=snippet,
                severity=severity_for(
                    StrideCategory.ELEVATION_OF_PRIVILEGE,
                    has_taint_trace=False,
                ),
                confidence=0.4,
                rationale=(
                    "__import__() enables dynamic module loading. If the "
                    "argument is derived from user input, this is an "
                    "arbitrary code execution vector."
                ),
                query_id="python.eop.dynamic_import_bare",
            )
        )

    # os.chmod / os.chown / os.setuid
    query = py_queries.QUERY_REGISTRY["python.eop.permission_change"].query
    for caps in run_query(query, tree.root_node):
        method = _text(caps["method"][0], source)
        call_node = caps["call"][0]
        location = _build_location(call_node, file.relpath)
        snippet = _build_snippet(source, location.line)
        findings.append(
            CandidateFinding(
                category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                title=f"Permission modification via os.{method}()",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=location,
                related_assets=(),
                code_snippet=snippet,
                severity=severity_for(
                    StrideCategory.ELEVATION_OF_PRIVILEGE,
                    has_taint_trace=False,
                ),
                confidence=0.6,
                rationale=(
                    f"``os.{method}()`` modifies filesystem permissions or "
                    "process identity. If arguments are influenced by "
                    "untrusted input, this can be used for privilege "
                    "escalation."
                ),
                query_id="python.eop.permission_change",
            )
        )

    return findings


def _build_subprocess_finding(
    source: bytes,
    location: Location,
    title: str,
    query_id: str,
    tier: str = "dynamic",
    config_driven: bool = False,
) -> CandidateFinding:
    snippet = _build_snippet(source, location.line)

    # Tier-specific severity and confidence overrides.
    # These bypass ranking.py's severity_for/confidence_for because the
    # four subprocess tiers require finer-grained differentiation than the
    # generic (STRIDE-category, taint-boolean) matrix provides.
    _TIER_SCORES: dict[str, tuple[int, float, str]] = {
        "static": (
            1,
            0.2,
            "Static literal command — no injection risk without shell=True.",
        ),
        "parameterized": (
            4,
            0.6,
            "Command list contains variable arguments that may originate "
            "from external input.",
        ),
        "dynamic": (
            6,
            0.8,
            "Entire command built dynamically — highest injection risk "
            "without taint confirmation.",
        ),
        "shell": (
            8,
            0.9,
            "shell=True enables shell interpretation of the command string, "
            "greatly increasing injection risk.",
        ),
    }

    severity, confidence, tier_rationale = _TIER_SCORES[tier]

    # Config-driven subprocess calls get elevated confidence because the
    # command argument originates from a configuration/dict lookup, which
    # is a well-known attack surface (e.g. TOML-driven command templates).
    if config_driven:
        confidence = 0.9
        tier_rationale = (
            f"{tier_rationale} Command argument is populated from "
            "configuration/dict lookup within the same function scope."
        )

    return CandidateFinding(
        category=StrideCategory.TAMPERING,
        title=title,
        source=FindingSource.TREE_SITTER_STRUCTURAL,
        primary_location=location,
        related_assets=(),
        code_snippet=snippet,
        severity=severity,
        confidence=confidence,
        rationale=(
            f"[subprocess/{tier}] {tier_rationale} "
            "Opengrep taint analysis will lift confirmed cases "
            "to high confidence."
        ),
        query_id=query_id,
    )


def _extract_python_call_graph(
    file: ScannedFile, source: bytes, tree: Any
) -> list[CallGraphNode]:
    func_query = py_queries.QUERY_REGISTRY["python.structure.function_def"].query
    call_query = py_queries.QUERY_REGISTRY["python.structure.call_site"].query

    nodes: list[CallGraphNode] = []
    for caps in run_query(func_query, tree.root_node):
        name_node = caps["func_name"][0]
        body_node = caps["body"][0]
        whole_node = caps["whole"][0]
        func_name = _text(name_node, source)
        calls: set[str] = set()
        for call_caps in run_query(call_query, body_node):
            for called in call_caps.get("called_name", []):
                calls.add(_text(called, source))
        nodes.append(
            CallGraphNode(
                function_name=func_name,
                location=_build_location(whole_node, file.relpath),
                language="python",
                calls=frozenset(calls),
                is_exported=not func_name.startswith("_"),
            )
        )
    return nodes


# ---------------------------------------------------------------------------
# Go extractors
# ---------------------------------------------------------------------------


def _extract_go_entry_points(
    file: ScannedFile, source: bytes, tree: Any
) -> list[DiscoveredEntryPoint]:
    entries: list[DiscoveredEntryPoint] = []
    query = go_queries.QUERY_REGISTRY["go.entry.selector_string_arg"].query
    for caps in run_query(query, tree.root_node):
        method = _text(caps["method"][0], source)
        if method not in _GO_HTTP_HANDLER_METHODS:
            continue
        obj = _text(caps["obj"][0], source)
        path = _strip_quotes(_text(caps["path"][0], source))
        whole = caps["whole"][0]
        # Map method name → HTTP verb where possible.
        http_method = None
        if method in ("Get", "Post", "Put", "Delete", "Patch", "Options", "Head"):
            http_method = method.upper()
        framework = "net/http" if obj == "http" else "http"
        entries.append(
            DiscoveredEntryPoint(
                kind=EntryPointKind.HTTP_ROUTE,
                name=path,
                location=_build_location(whole, file.relpath),
                language="go",
                framework=framework,
                route_path=path,
                http_method=http_method,
                has_auth_decorator=False,
                source_query="go.entry.selector_string_arg",
            )
        )
    return entries


def _extract_go_data_stores(
    file: ScannedFile,
    source: bytes,
    tree: Any,
    dependency_names: set[str],
) -> list[DiscoveredDataStore]:
    stores: list[DiscoveredDataStore] = []
    query = go_queries.QUERY_REGISTRY["go.datastore.sql_open"].query
    go_imports = _collect_go_imports(source, tree)

    for caps in run_query(query, tree.root_node):
        pkg = _text(caps["pkg"][0], source)
        method = _text(caps["method"][0], source)
        if (pkg, method) not in _GO_DB_OPEN_PAIRS:
            continue
        driver_text = _strip_quotes(_text(caps["driver"][0], source))
        # The driver may be the full URL; grab the scheme/prefix.
        driver_key = driver_text.split(":", 1)[0].lower()
        if driver_key not in _GO_DRIVER_TO_TECH:
            continue
        kind, tech = _GO_DRIVER_TO_TECH[driver_key]
        whole = caps["whole"][0]
        # Corroborate with imports: a real postgres driver import is a
        # strong signal; if missing, fall back to the call itself as
        # evidence (the call node is structurally real).
        import_evidence: str | None = None
        for imp in go_imports:
            if driver_key in imp.lower():
                import_evidence = imp
                break
        manifest_evidence: str | None = None
        if tech in dependency_names or driver_key in dependency_names:
            manifest_evidence = tech
        if import_evidence is None and manifest_evidence is None:
            # Use the call itself as evidence — in Go, unlike Python, the
            # driver name appears directly in the code.
            import_evidence = f"sql.Open({driver_text!r})"
        stores.append(
            DiscoveredDataStore(
                kind=kind,
                technology=tech,
                location=_build_location(whole, file.relpath),
                language="go",
                import_evidence=import_evidence,
                dependency_manifest_evidence=manifest_evidence,
                source_query="go.datastore.sql_open",
            )
        )
    return stores


def _collect_go_imports(source: bytes, tree: Any) -> set[str]:
    imports: set[str] = set()
    for caps in run_query(
        go_queries.QUERY_REGISTRY["go.imports"].query, tree.root_node
    ):
        for node in caps.get("path", []):
            imports.add(_strip_quotes(_text(node, source)))
    return imports


# ---------------------------------------------------------------------------
# JavaScript / TypeScript extractors (minimal v1)
# ---------------------------------------------------------------------------


def _extract_js_entry_points(
    file: ScannedFile, source: bytes, tree: Any
) -> list[DiscoveredEntryPoint]:
    language = file.language
    registry_key = f"{language}.entry.route_call"
    if registry_key not in js_queries.QUERY_REGISTRY:
        return []
    query = js_queries.QUERY_REGISTRY[registry_key].query
    entries: list[DiscoveredEntryPoint] = []
    for caps in run_query(query, tree.root_node):
        method = _text(caps["method"][0], source)
        if method not in _HTTP_METHODS and method != "use":
            continue
        path = _strip_quotes(_text(caps["path"][0], source))
        whole = caps["whole"][0]
        entries.append(
            DiscoveredEntryPoint(
                kind=EntryPointKind.HTTP_ROUTE,
                name=path,
                location=_build_location(whole, file.relpath),
                language=language,
                framework="express",
                route_path=path,
                http_method=method.upper() if method in _HTTP_METHODS else None,
                has_auth_decorator=False,
                source_query=f"{language}.entry.route_call",
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Opengrep normalization and deduplication
# ---------------------------------------------------------------------------

#: STRIDE category mapping from Opengrep rule metadata. Rules can set
#: ``metadata.stride`` to one of these values; if missing, default to
#: TAMPERING (the most common case for taint rules).
_STRIDE_FROM_METADATA: dict[str, StrideCategory] = {
    "spoofing": StrideCategory.SPOOFING,
    "tampering": StrideCategory.TAMPERING,
    "repudiation": StrideCategory.REPUDIATION,
    "information_disclosure": StrideCategory.INFORMATION_DISCLOSURE,
    "denial_of_service": StrideCategory.DENIAL_OF_SERVICE,
    "elevation_of_privilege": StrideCategory.ELEVATION_OF_PRIVILEGE,
}


def _normalize_opengrep_findings(
    raw_findings: list[dict],
    scanned_files: list[ScannedFile],
) -> list[CandidateFinding]:
    """Convert Opengrep JSON result entries into ``CandidateFinding`` objects."""
    file_cache: dict[str, bytes] = {}
    candidates: list[CandidateFinding] = []

    for entry in raw_findings:
        try:
            candidate = _normalize_one_opengrep_finding(entry, scanned_files, file_cache)
        except Exception as exc:  # noqa: BLE001
            path = entry.get("path", "unknown")
            logger.warning(
                "skipping malformed opengrep finding in file %s (error type: %s): %s",
                path,
                type(exc).__name__,
                exc,
            )
            continue
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _normalize_one_opengrep_finding(
    entry: dict,
    scanned_files: list[ScannedFile],
    file_cache: dict[str, bytes],
) -> CandidateFinding | None:
    """Convert a single Opengrep JSON result to a CandidateFinding."""
    check_id = entry.get("check_id", "unknown")
    path = entry.get("path", "")
    start = entry.get("start", {})
    end = entry.get("end", {})
    extra = entry.get("extra", {})
    message = extra.get("message", check_id)
    og_severity = extra.get("severity", "WARNING").upper()
    metadata = extra.get("metadata", {})

    # Location
    line = start.get("line", 1)
    col = start.get("col", 1)
    end_line = end.get("line", line)
    end_col = end.get("col", col)

    # Resolve relative path — Opengrep returns absolute paths
    relpath = path
    for sf in scanned_files:
        if str(sf.path) == path or sf.relpath == path:
            relpath = sf.relpath
            break

    location = Location(
        file=relpath,
        line=line,
        column=col,
        end_line=end_line,
        end_column=end_col,
    )

    # STRIDE category from rule metadata or severity
    stride_key = metadata.get("stride", metadata.get("category", ""))
    category = _STRIDE_FROM_METADATA.get(
        stride_key.lower() if stride_key else "",
        StrideCategory.TAMPERING,
    )

    # Data flow trace (taint rules only)
    dataflow_raw = extra.get("dataflow_trace")
    data_flow: DataFlowTrace | None = None
    source_enum = FindingSource.OPENGREP_PATTERN

    if dataflow_raw is not None:
        source_enum = FindingSource.OPENGREP_TAINT
        try:
            data_flow = _parse_dataflow_trace(dataflow_raw, relpath)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "malformed opengrep dataflow trace in file %s (error type: %s): %s",
                relpath,
                type(exc).__name__,
                exc,
            )
            # Malformed trace — downgrade to pattern match
            source_enum = FindingSource.OPENGREP_PATTERN
            data_flow = None

    # Severity mapping from Opengrep severity string
    severity_map = {"ERROR": 9, "WARNING": 6, "INFO": 3}
    severity = severity_map.get(og_severity, 6)

    confidence = confidence_for(source_enum)

    # Code snippet
    source_bytes = _get_source_for(relpath, scanned_files, file_cache)
    if source_bytes is not None:
        snippet = _build_snippet(source_bytes, line)
    else:
        snippet = CodeSnippet(
            lines=(extra.get("lines", ""),),
            start_line=line,
            marker_line=line,
        )

    return CandidateFinding(
        category=category,
        title=message,
        source=source_enum,
        primary_location=location,
        related_assets=(),
        code_snippet=snippet,
        severity=severity,
        confidence=confidence,
        rationale=(
            f"Finding from Opengrep rule `{check_id}`. "
            + ("Taint analysis confirmed data flow from source to sink."
               if data_flow is not None
               else "Structural pattern match (no taint trace).")
        ),
        query_id=check_id,
        data_flow=data_flow,
    )


def _parse_dataflow_trace(raw: dict | list, default_file: str) -> DataFlowTrace:
    """Parse Opengrep's dataflow_trace JSON into a DataFlowTrace.

    Opengrep emits traces as a dict with ``taint_source``,
    ``intermediate_vars``, and ``taint_sink`` keys. Each step can be
    either a dict (standard format) or a list (``["CliLoc", ...]`` format
    seen in some Opengrep versions). We normalize both to our
    :class:`DataFlowTrace` shape.

    Raises ``ValueError`` if the input is malformed or missing required
    fields — callers should catch and downgrade to a pattern-match finding.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"Unexpected dataflow_trace shape: {type(raw)}")

    src_raw = raw.get("taint_source")
    sink_raw = raw.get("taint_sink")
    inter_raw = raw.get("intermediate_vars", [])

    if src_raw is None:
        raise ValueError("dataflow_trace missing taint_source")
    if sink_raw is None:
        raise ValueError("dataflow_trace missing taint_sink")

    def _step(step_raw: Any) -> DataFlowStep:
        if step_raw is None:
            raise ValueError("dataflow step is None")
        if isinstance(step_raw, list) and len(step_raw) >= 2:
            # ["CliLoc", [{location_dict}, "content"]]
            loc_and_content = step_raw[1]
            if isinstance(loc_and_content, list) and len(loc_and_content) >= 2:
                loc_dict = loc_and_content[0] if isinstance(loc_and_content[0], dict) else {}
                content = str(loc_and_content[1])
                return DataFlowStep(
                    location=Location(
                        file=default_file,
                        line=loc_dict.get("start", {}).get("line", 1),
                        column=loc_dict.get("start", {}).get("col", 1),
                        end_line=loc_dict.get("end", {}).get("line", 1),
                        end_column=loc_dict.get("end", {}).get("col", 1),
                    ),
                    content=content,
                )
        if isinstance(step_raw, dict):
            loc = step_raw.get("location", {})
            return DataFlowStep(
                location=Location(
                    file=default_file,
                    line=loc.get("start", {}).get("line", 1),
                    column=loc.get("start", {}).get("col", 1),
                    end_line=loc.get("end", {}).get("line", 1),
                    end_column=loc.get("end", {}).get("col", 1),
                ),
                content=step_raw.get("content", ""),
            )
        raise ValueError(f"Unexpected step shape: {type(step_raw)}")

    source = _step(src_raw)
    sink = _step(sink_raw)
    intermediates = tuple(_step(i) for i in (inter_raw or []))

    return DataFlowTrace(source=source, intermediate=intermediates, sink=sink)


def _merge_opengrep_into_findings(
    ts_findings: list[CandidateFinding],
    og_findings: list[CandidateFinding],
) -> list[CandidateFinding]:
    """Merge Opengrep findings into the tree-sitter findings list.

    Dedup strategy: if an Opengrep finding lands on the same (file, line)
    as an existing tree-sitter finding, the Opengrep finding wins (it has
    higher confidence and may include a taint trace). ALL tree-sitter
    findings at that location are replaced (the first is overwritten, the
    rest are dropped). Tree-sitter findings at unique locations are kept.
    Opengrep findings at unique locations are added.
    """
    # Index ALL tree-sitter findings by (file, line) — there may be
    # multiple findings at the same line (e.g. Tampering + DoS for a
    # subprocess call).
    ts_by_location: dict[tuple[str, int], list[int]] = {}
    for i, f in enumerate(ts_findings):
        key = (f.primary_location.file, f.primary_location.line)
        ts_by_location.setdefault(key, []).append(i)

    merged = list(ts_findings)
    drop_indices: set[int] = set()

    for og in og_findings:
        key = (og.primary_location.file, og.primary_location.line)
        if key in ts_by_location:
            indices = ts_by_location[key]
            # Replace the first ts finding with the Opengrep one;
            # drop all others at this location.
            replaced_first = False
            for idx in indices:
                if not replaced_first:
                    merged[idx] = og
                    replaced_first = True
                else:
                    drop_indices.add(idx)
        else:
            # New location — add alongside tree-sitter findings
            merged.append(og)

    if drop_indices:
        merged = [f for i, f in enumerate(merged) if i not in drop_indices]
    return merged


# ---------------------------------------------------------------------------
# Asset-to-finding generators (populate non-Tampering STRIDE categories)
# ---------------------------------------------------------------------------


def _spoofing_findings_from_entry_points(
    entry_points: list[DiscoveredEntryPoint],
    scanned_files: list[ScannedFile],
) -> list[CandidateFinding]:
    """Emit a Spoofing candidate for each entry point that lacks an auth decorator.

    This populates the Spoofing category with actionable observations:
    "this endpoint is publicly reachable and no decorator-level auth was
    detected." The calling agent can verify whether authentication exists
    at a different layer (middleware, reverse proxy, etc.) and strip
    findings that don't apply.
    """
    file_content_cache: dict[str, bytes] = {}
    findings: list[CandidateFinding] = []

    for ep in entry_points:
        if ep.has_auth_decorator:
            continue  # decorated with auth — no spoofing concern
        source = _get_source_for(ep.location.file, scanned_files, file_content_cache)
        if source is None:
            continue
        severity = severity_for(StrideCategory.SPOOFING, has_taint_trace=False)
        confidence = confidence_for(
            FindingSource.TREE_SITTER_STRUCTURAL, query_intent="decorator"
        )
        snippet = _build_snippet(source, ep.location.line)
        kind_label = ep.kind.value.replace("_", " ")
        framework_label = f" ({ep.framework})" if ep.framework else ""
        findings.append(
            CandidateFinding(
                category=StrideCategory.SPOOFING,
                title=f"Unauthenticated {kind_label}{framework_label}: {ep.route_path or ep.name}",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=ep.location,
                related_assets=(ep.id,),
                code_snippet=snippet,
                severity=severity,
                confidence=confidence,
                rationale=(
                    "No authentication decorator was found on this endpoint. "
                    "If the endpoint handles sensitive actions, it may be "
                    "accessible to unauthenticated callers. Verify whether "
                    "authentication is enforced at a different layer "
                    "(middleware, reverse proxy, MCP client credential check)."
                ),
                query_id=ep.source_query,
            )
        )
    return findings


def _info_disclosure_findings_from_data_stores(
    data_stores: list[DiscoveredDataStore],
    scanned_files: list[ScannedFile],
) -> list[CandidateFinding]:
    """Emit an Information Disclosure candidate for each data store.

    Every data store is a potential target for data exfiltration. The
    calling agent should verify whether the store is protected by
    access controls and whether the data it holds is sensitive.
    """
    file_content_cache: dict[str, bytes] = {}
    findings: list[CandidateFinding] = []

    for ds in data_stores:
        source = _get_source_for(ds.location.file, scanned_files, file_content_cache)
        if source is None:
            continue
        severity = severity_for(
            StrideCategory.INFORMATION_DISCLOSURE, has_taint_trace=False
        )
        confidence = confidence_for(
            FindingSource.TREE_SITTER_STRUCTURAL, query_intent="constructor_call"
        )
        snippet = _build_snippet(source, ds.location.line)
        findings.append(
            CandidateFinding(
                category=StrideCategory.INFORMATION_DISCLOSURE,
                title=f"Data store: {ds.technology} ({ds.kind.value})",
                source=FindingSource.TREE_SITTER_STRUCTURAL,
                primary_location=ds.location,
                related_assets=(ds.id,),
                code_snippet=snippet,
                severity=severity,
                confidence=confidence,
                rationale=(
                    f"A {ds.technology} data store was detected. Review "
                    "whether access controls, encryption at rest, and "
                    "connection-string management meet the project's "
                    "security requirements. If the store holds PII or "
                    "secrets, additional controls may be needed."
                ),
                query_id=ds.source_query,
            )
        )
    return findings


def _get_source_for(
    relpath: str,
    scanned_files: list[ScannedFile],
    cache: dict[str, bytes],
) -> bytes | None:
    """Lazily read and cache a file's bytes for snippet generation."""
    if relpath in cache:
        return cache[relpath]
    for sf in scanned_files:
        if sf.relpath == relpath:
            try:
                content = sf.read_bytes()
                cache[relpath] = content
                return content
            except OSError:
                return None
    return None


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryConfig:
    snippet_context_lines: int = 10
    shallow_threshold: int = 500
    extra_excludes: tuple[str, ...] = ()


def discover_all(
    repo_root: Path,
    config: DiscoveryConfig | None = None,
) -> DiscoveryResult:
    """Walk ``repo_root`` and produce a complete :class:`DiscoveryResult`.

    This is the single entry point the handler calls. It runs tree-sitter
    structural queries, optional Opengrep enrichment, asset-to-finding
    generation, and returns the combined results.
    """
    config = config or DiscoveryConfig()
    repo_root = Path(repo_root).resolve()

    scanned_files, scan_stats = walk_repo(
        repo_root,
        extra_excludes=config.extra_excludes,
        shallow_threshold=config.shallow_threshold,
    )
    shallow = scan_stats.shallow_mode
    if shallow:
        logger.info(
            "shallow mode activated (%d in-scope files > threshold %d): "
            "skipping subprocess/call-graph/injection queries",
            scan_stats.in_scope_files,
            scan_stats.shallow_threshold,
        )
    dependency_names = _read_dependency_names(repo_root)

    entry_points: list[DiscoveredEntryPoint] = []
    data_stores: list[DiscoveredDataStore] = []
    call_graph: list[CallGraphNode] = []
    findings: list[CandidateFinding] = []

    for file in scanned_files:
        try:
            source = file.read_bytes()
        except OSError as e:
            logger.debug("skipping unreadable file %s: %s", file.relpath, e)
            continue

        try:
            tree = parse_source(file.language, source)
        except ValueError:
            logger.debug("skipping %s: unsupported for parser", file.relpath)
            continue

        lang = file.language
        if lang == "python":
            py_imports = _collect_python_imports(source, tree)
            entry_points.extend(
                _extract_python_entry_points(file, source, tree, py_imports)
            )
            data_stores.extend(
                _extract_python_data_stores(
                    file, source, tree, py_imports, dependency_names
                )
            )
            if not shallow:
                findings.extend(
                    _extract_python_subprocess_findings(file, source, tree)
                )
                findings.extend(
                    _extract_python_info_disclosure_findings(file, source, tree)
                )
                findings.extend(
                    _extract_python_dos_findings(file, source, tree)
                )
                findings.extend(
                    _extract_python_eop_findings(file, source, tree)
                )
                call_graph.extend(_extract_python_call_graph(file, source, tree))
        elif lang == "go":
            entry_points.extend(_extract_go_entry_points(file, source, tree))
            data_stores.extend(
                _extract_go_data_stores(file, source, tree, dependency_names)
            )
        elif lang in ("javascript", "typescript", "tsx"):
            entry_points.extend(_extract_js_entry_points(file, source, tree))
        elif lang == "yaml":
            pass

    # Asset-to-finding generation: produce candidate findings from the
    # discovered assets themselves (entry points → Spoofing, data stores
    # → Information Disclosure). These populate the STRIDE categories that
    # would otherwise be empty when only subprocess/eval findings exist.
    findings.extend(_spoofing_findings_from_entry_points(entry_points, scanned_files))
    findings.extend(_info_disclosure_findings_from_data_stores(data_stores, scanned_files))

    # Opengrep enrichment: run bundled rules for taint analysis + structural
    # pattern matching when the binary is available. On absence or failure,
    # degrade cleanly with a logged warning.
    og_result = _run_opengrep_enrichment(repo_root)
    opengrep_available = og_result.available
    opengrep_degraded_reason = og_result.degraded_reason

    if og_result.findings:
        og_findings = _normalize_opengrep_findings(og_result.findings, scanned_files)
        findings = _merge_opengrep_into_findings(findings, og_findings)
        logger.debug(
            "opengrep enriched: %d raw findings → %d normalized, merged into %d total",
            len(og_result.findings),
            len(og_findings),
            len(findings),
        )

    if not entry_points and scan_stats.in_scope_files > 50:
        logger.warning(
            "discover_all: zero entry points found in a repository with %d "
            "in-scope files. This likely indicates missing query coverage for "
            "the project's framework or registration pattern.",
            scan_stats.in_scope_files,
        )

    logger.debug(
        "discover_all: %d entry points, %d data stores, %d findings, %d call graph nodes",
        len(entry_points),
        len(data_stores),
        len(findings),
        len(call_graph),
    )
    return DiscoveryResult(
        entry_points=entry_points,
        data_stores=data_stores,
        call_graph=call_graph,
        findings=findings,
        file_scan_stats=scan_stats,
        opengrep_available=opengrep_available,
        opengrep_degraded_reason=opengrep_degraded_reason,
    )


def _run_opengrep_enrichment(repo_root: Path) -> OpengrepResult:
    """Invoke Opengrep with bundled rules against the repo.

    Uses ``importlib.resources`` to locate the rules directory, which
    handles both editable installs and zipped wheels. On any failure
    returns a no-op ``OpengrepResult`` so the caller can degrade cleanly.
    """
    try:
        from importlib.resources import as_file, files

        rules_ref = files("darnit_baseline.threat_model").joinpath("opengrep_rules")
        with as_file(rules_ref) as rules_path:
            return run_opengrep(target=repo_root, rules_dir=rules_path)
    except Exception as exc:  # noqa: BLE001 — never break discovery
        logger.warning(
            "opengrep enrichment failed on %s (error type: %s): %s",
            repo_root,
            type(exc).__name__,
            exc,
        )
        return OpengrepResult(
            available=False,
            degraded_reason=f"opengrep rules resolution failed: {exc}",
        )


def _read_dependency_names(repo_root: Path) -> set[str]:
    """Parse the repo's dependency manifests into a flat name set.

    Reuses :mod:`darnit_baseline.threat_model.dependencies` which already
    handles pyproject.toml, package.json, go.mod, etc.
    """
    try:
        names = deps_module.parse_dependency_manifests(str(repo_root))
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.warning(
            "dependency manifest parse failed for %s (error type: %s): %s",
            repo_root,
            type(e).__name__,
            e,
        )
        return set()
    if isinstance(names, dict):
        return set(names.keys())
    return set(names) if names else set()


def build_empty_result() -> DiscoveryResult:
    """A zeroed DiscoveryResult used when discovery cannot run at all."""
    return DiscoveryResult(
        entry_points=[],
        data_stores=[],
        call_graph=[],
        findings=[],
        file_scan_stats=FileScanStats(
            total_files_seen=0,
            excluded_dir_count=0,
            unsupported_file_count=0,
            in_scope_files=0,
            by_language={},
            shallow_mode=False,
            shallow_threshold=500,
        ),
        opengrep_available=False,
        opengrep_degraded_reason=None,
    )


__all__ = [
    "DiscoveryConfig",
    "discover_all",
    "build_empty_result",
]
