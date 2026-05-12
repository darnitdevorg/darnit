#!/bin/sh
#
# darnit container entrypoint.
#
# Dispatches the first positional argument:
#   audit, remediate, list-controls, plan, profiles, validate, --version, --help
#     → forwarded to `darnit` CLI
#   mcp
#     → forwarded to `darnit-mcp` (stdio MCP server)
#   anything else (including a path or shell command)
#     → executed directly (escape hatch for advanced users)
#
# Contract: packaging/container/Dockerfile sets WORKDIR=/repo so users
# typically invoke with `-v "$PWD:/repo"`.

set -eu

if [ "$#" -eq 0 ]; then
    exec darnit --help
fi

case "$1" in
    audit|remediate|list-controls|plan|profiles|validate|--version|--help|-h|-V)
        exec darnit "$@"
        ;;
    mcp)
        shift
        exec darnit-mcp "$@"
        ;;
    *)
        # Escape hatch — exec the user's command directly. Lets advanced
        # users run arbitrary CLIs in the image (sh, gh, git, etc.)
        # without us maintaining a whitelist.
        exec "$@"
        ;;
esac
