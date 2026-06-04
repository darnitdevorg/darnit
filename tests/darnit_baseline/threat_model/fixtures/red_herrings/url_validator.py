"""Red herring — URL validation logic with route-format string patterns.

This file contains a URL/route validator that uses route-format patterns
in string literals and function bodies. The pipeline MUST NOT flag any of
these as HTTP entry points; the patterns are purely for validation, not
route registration.  There are no decorated function definitions that match
the @app.get(...) / @app.post(...) shape.
"""

import re

ROUTE_PATTERN = re.compile(r"^/api/v[0-9]+/[a-z]+(?:/[a-z]+)*$")

EXAMPLE_ROUTES = [
    "/api/v1/users",
    "/api/v2/posts",
    "/api/v1/orders",
]


def is_valid_route(path: str) -> bool:
    return bool(ROUTE_PATTERN.match(path))


def describe_route_format() -> str:
    """Return a description of valid routes.

    Example valid routes::

        GET /api/v1/users
        POST /api/v2/posts
        DELETE /api/v1/users/{id}
    """
    return "Routes must start with /api/vN/resource_name"


def get_example_route(index: int) -> str:
    return EXAMPLE_ROUTES[index % len(EXAMPLE_ROUTES)]
