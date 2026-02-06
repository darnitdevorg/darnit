## Context

The darnit framework has a well-defined `ComplianceImplementation` protocol and a mature reference implementation (`darnit-baseline` with 62 controls). However, `darnit-baseline` is large and tightly coupled to the OpenSSF specification, making it hard to use as a learning reference. The `IMPLEMENTATION_GUIDE.md` teaches the pattern with pseudocode but has no runnable companion. Plugin authors need a small, self-contained example they can copy, install, and modify.

## Goals / Non-Goals

**Goals:**
- Provide a working, installable package that satisfies the `ComplianceImplementation` protocol
- Demonstrate all major plugin features: TOML controls, Python controls, remediation, handler registration, testing
- Keep the control set small enough (8 controls, 2 levels) that the entire package is readable in one sitting
- Run fully offline (no API calls) so anyone can clone and test immediately
- Validate that `docs/IMPLEMENTATION_GUIDE.md` is accurate and followable

**Non-Goals:**
- Replace or compete with `darnit-baseline` as a production implementation
- Cover every framework feature (CEL expressions, locator configs, LLM pass, context-conditional controls)
- Provide a real compliance standard — the "Project Hygiene Standard" is illustrative only
- Modify framework internals beyond the minimum needed (`ALLOWED_MODULE_PREFIXES`)

## Decisions

### 1. Package location: `packages/darnit-example/` (workspace member)

Place the package in the existing `packages/` directory alongside `darnit` and `darnit-baseline`. This makes it a workspace member automatically (via `packages/*` glob in `[tool.uv.workspace]`) and matches the established layout.

**Alternative considered**: `docs/examples/darnit-example/` — rejected because workspace member status is needed for `uv sync` to install it as a real entry-point package, and `docs/examples/` packages are not workspace members.

### 2. Control mix: 6 TOML + 2 Python

Six TOML-only controls demonstrate that most checks need no Python code at all. Two Python controls show the factory function pattern (`_create_*_check() -> Callable`) and custom analyzers, which are the patterns new plugin authors are most likely to need. This ratio matches the real-world expectation: most controls are file-existence checks.

**Alternative considered**: All 8 in TOML, or all 8 in Python — rejected because showing only one approach defeats the educational purpose.

### 3. Control domain: "Project Hygiene" (file existence checks)

All controls check for local files (README, LICENSE, .gitignore, CI config, etc.). This keeps the example runnable offline without GitHub API access, Docker, or other external dependencies.

**Alternative considered**: API-based controls (like checking GitHub branch protection) — rejected because they require authentication and network access, adding friction for first-time users.

### 4. Remediation: two simple file-create actions

Only `create_readme` and `create_gitignore` are implemented as remediation actions. This covers the common pattern (create a missing file from a template) without bloating the example.

### 5. Handler: single stub function

One async handler (`example_hygiene_check`) demonstrates the registration pattern without implementing real MCP tool logic. The focus is on showing `register_handlers()` and `ALLOWED_MODULE_PREFIXES` integration.

### 6. Rules catalog: inline dict in `implementation.py`

The rules catalog is a simple `_RULES` dict in the implementation module rather than a separate `rules/catalog.py`. This is intentional — it keeps the example compact and avoids introducing the deprecated catalog pattern that `darnit-baseline` still carries.

## Risks / Trade-offs

- **Divergence from guide**: If `IMPLEMENTATION_GUIDE.md` evolves, the example could become stale → Mitigation: the guide now references the example, creating a natural reminder to keep both in sync.
- **Workspace bloat**: Adding a third package increases `uv sync` time slightly → Acceptable for a small package with no extra dependencies.
- **ALLOWED_MODULE_PREFIXES grows**: Each new plugin needs a prefix entry → This is a known limitation of the security allowlist approach; the example documents the pattern.
- **Test isolation**: Python control registration uses a global registry; tests importing `level1.py` register controls permanently for the test session → Mitigated by using fresh `CheckContext` instances per test; registry pollution is harmless since control IDs are unique.
