# darnit-reproducibility (transitional)

`darnit-reproducibility` was renamed `darnit-amber` in darnit 0.1.2 (#532).
This package exists for one release so that upgrading `darnit-mcp` replaces
the old plugin instead of leaving it installed next to the new one: it has no
entry points and only depends on `darnit-amber`.

Migrate:

    pip uninstall darnit-reproducibility
    # then rename `reproducibility` to `amber` in:
    #   darnit audit -f amber
    #   MCP client configs (server and framework name)
    #   operator configuration: [plugins].allowed, [[compose]] source

`import darnit_reproducibility` re-exports `darnit_amber` with a
`DeprecationWarning`.
