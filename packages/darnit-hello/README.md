# darnit-hello

A **minimal worked example** of a third-party darnit compliance implementation. Not a real compliance framework — this package exists purely as a copy-paste starter for teams who want to build their own darnit plugins.

For the step-by-step packaging guide, see [`docs/packaging-plugins.md`](https://github.com/kusari-oss/darnit/blob/main/docs/packaging-plugins.md) in the darnit repo.

## What it contains

- One control: **`HELLO-01.01 ReadmeExists`** — verifies the repository has a top-level `README` file.
- One remediation: auto-creates a stub `README.md` if missing.
- One MCP tool: `audit_hello`, an alias for the built-in `audit`.

Everything is defined in `hello.toml`. The Python side is the absolute minimum to satisfy the `darnit.core.plugin.ComplianceImplementation` protocol:

```
src/darnit_hello/
├── __init__.py           # register() + get_framework_path() entry points
├── implementation.py     # HelloImplementation class — protocol-conforming
└── hello.toml            # Source of truth for controls (bundled at install)
```

## Install (locally)

```bash
# From a darnit checkout
pip install -e packages/darnit-hello

# Confirm darnit discovers it
darnit list-controls --implementation hello
# → HELLO-01.01 ReadmeExists

# Run the audit
darnit audit --implementation hello
```

## Using as a starting point

1. Copy `packages/darnit-hello/` to your own repo (or fork darnit and rename).
2. Rename `darnit_hello` → `<your_package>` throughout (the package directory, `__init__.py`, `implementation.py`, and `pyproject.toml`'s `name` + entry-point keys).
3. Replace `hello.toml` with your own framework + controls. The TOML schema is documented in [`docs/packaging-plugins.md`](https://github.com/kusari-oss/darnit/blob/main/docs/packaging-plugins.md).
4. Publish to PyPI (or a private index), and darnit will discover it on any host where both are installed.

## Why this exists separately from `darnit-example`

`darnit-example` is a fuller reference implementation that exercises Python control handlers, custom tools, remediation actions, and multi-level scoring. It's a learning tool but it's a lot to read.

`darnit-hello` is deliberately the smallest plugin that the framework will discover, audit, and report against. Read this one first; once you understand the entry-point + ComplianceImplementation surface, look at `darnit-example` for the richer patterns.

## License

Apache-2.0.
