# Phase 0 Research: Pluggable storage backends via per-artifact Protocols

## Purpose

Resolve every unknown surfaced by the plan's Technical Context and record the call-site inventory, ownership decisions, and pattern-reuse choices that the tasks decomposition and reader contracts depend on.

## Decisions

### R-001: Call-site inventory per artifact class

**Decision**: The four artifact classes have the following current hard-coded filesystem call sites. Rewriting each is a Phase 3 task.

| Artifact class | Module | Line(s) | Current shape | Notes |
|----------------|--------|---------|---------------|-------|
| Attestation | `packages/darnit-baseline/src/darnit_baseline/attestation/generator.py` | 138 | `open(output_path, 'w', encoding="utf-8")` | Sole call site. `output_path` is a caller-supplied path passed all the way from the audit driver. Becomes an `AttestationStore` supplied by the audit driver instead of a raw path. |
| Audit cache | `packages/darnit/src/darnit/core/audit_cache.py` | 138 (write), 170 (read) | `os.fdopen(fd, "w", encoding="utf-8")` + `open(cache_path, encoding="utf-8")` | Tempfile-then-rename write path preserves atomic-rename semantics; that logic moves into `FilesystemAuditCacheStore`'s implementation. The public `read_audit_cache` / `write_audit_cache` functions become thin wrappers that call into the store. |
| Project state (read) | `packages/darnit/src/darnit/context/dot_project.py` | 384 (project.yaml), 425 (maintainers.yaml), 958 (project.yaml re-read for update path) | `open(self.project_yaml, encoding="utf-8")` etc. | `DotProjectReader` becomes store-aware. Reader retains the same public shape; its `__init__` now accepts a `ProjectStateStore` (defaults to `FilesystemProjectStateStore(repo_path)` for backward compat with existing callers that pass a repo path). |
| Project state (write) | `packages/darnit/src/darnit/context/dot_project.py` | 971 | `open(self.project_yaml, "w", encoding="utf-8")` | Same pattern as read: writer accepts a `ProjectStateStore`. |
| Project state (org fetch) | `packages/darnit/src/darnit/context/dot_project_org.py` | 168-170, 182-183 | `(project_dir / "project.yaml").write_text(project_content, encoding="utf-8")` and similar for maintainers.yaml | Same rewrite; org-fetched YAML flows through the store's `write_project` / `write_maintainers` methods. |
| Report | (none today) | -- | Reports are returned by formatter functions; the CLI does not persist them to disk (per open issue #341). | ReportStore is aspirational in v0: no existing call site to rewrite. Filesystem default exists to enable #341 (CLI SARIF/Markdown emit) to write through the Protocol once that feature lands. |

**Rationale**: The count in the plan's Technical Context ("~10 rewrites") is close but slightly off. Actual count is 7 concrete rewrites plus 1 no-op-in-v0 artifact class (Report). The Report Protocol still needs to exist because future features (starting with #341) will consume it; shipping the Protocol + default now avoids a downstream feature having to introduce the abstraction retroactively.

**Alternatives considered**:
- **Defer the Report Protocol until #341 lands** (rejected). Would either force #341 to invent its own abstraction or later-migrate a hard-coded call site. Shipping the Protocol now costs ~50 LOC and blocks that class of retroactive migration.
- **Split project-state read and write into two Protocols** (rejected). Feature 027 established the convention that a Protocol maps to a single artifact class regardless of whether read + write live in the same call site; splitting doubles the surface for no gain.

**References**: audit-cache atomic-write pattern at `core/audit_cache.py:130-150`; dot_project.py YAML I/O at lines 384-425, 958-971.

---

### R-002: `close()` teardown ownership at the audit boundary

**Decision**: Ownership lives in `darnit.tools.audit._run_audit` (the current entry point for a complete audit run). Introduce a `_StoreBundle` dataclass in `darnit.stores.selection` that holds the resolved store instances and exposes `close_all()` which calls `close()` on every store that was actually instantiated (idempotent). `_run_audit` wraps the audit-scoped block in a `try/finally` that always calls `bundle.close_all()` on exit -- success, control failure, exception, or interrupt.

The pattern matches feature 031's `SieveOrchestrator.verify_batch` `finally` block around per-control MCP-pool teardown, but at a wider boundary. The store bundle covers the entire audit run because report and attestation writes happen AFTER the sieve loop (post-loop composition step), so a sieve-scoped `finally` is too narrow.

**Rationale**: Consolidating close-ownership in one place (a) keeps the invariant testable via a single test that spies on `close()` across all four Protocols, and (b) matches the reader's mental model of a store as an audit-run-scoped resource-holder.

**Alternatives considered**:
- **Per-Protocol context managers threaded through every consumer** (rejected). Fragments teardown across N call sites; one exception in a consumer that forgets the `with` statement leaks resources.
- **`atexit` handlers on individual stores** (rejected). Fires at process exit, not audit-run exit; misses the "close at audit boundary" contract; leaks resources across multiple audit runs in the same process (relevant for the MCP-server product path which runs many audits per server process).
- **`weakref.finalize` on the store instance** (rejected for the same reason as atexit -- runs at GC time, not at audit boundary).

**References**: feature 031's `verify_batch` finally block at `packages/darnit/src/darnit/sieve/orchestrator.py:730-750`.

---

### R-003: `importlib.metadata` entry-point discovery pattern (reuse from feature 027)

**Decision**: Copy the shape of `packages/darnit/src/darnit/harness/resolver_discovery.py` into `packages/darnit/src/darnit/stores/discovery.py`, adapted for four groups instead of one, with added name-collision detection (FR-009) that feature 027 did not need because `QuestionResolver` discovery was single-group and last-wins-by-priority.

The v0 shape:

```python
def discover_stores(group: str) -> dict[str, type[Store]]:
    """Load all entry points registered under `group`, return a name -> class map.

    Raises `StoreNameCollision` if two entry points register the same short name.
    Wraps each individual entry-point load in a try/except so one broken plugin
    does not blank the whole discovery result; broken plugins are logged and
    omitted from the map (per FR-009 name-collision detection is a hard error;
    per FR-002 Protocol-conformance is checked at selection time, not discovery
    time, so a plugin that loads-but-does-not-conform still appears in the map
    and fails later with a clearer error).
    """
```

**Rationale**: A single entry-point discovery convention across the codebase reduces cognitive load for plugin authors reading multiple extension surfaces (`darnit.frameworks`, `darnit.question_resolvers`, and now `darnit.stores.*`). Feature 027's pattern is battle-tested.

**Alternatives considered**:
- **Roll a fresh pattern** (rejected -- codebase should have one entry-point discovery convention).
- **Share a helper module between the two features** (rejected for v0 -- YAGNI. Factor after the third consumer if the copy-paste becomes a maintenance burden. Currently ~30 LOC of near-duplication is cheaper than a shared module).
- **Use `pkg_resources`** (rejected -- deprecated in favor of `importlib.metadata`; feature 027 already made this choice).

**References**: `packages/darnit/src/darnit/harness/resolver_discovery.py`.

---

### R-004: `$VAR` substitution helper -- extract or duplicate

**Decision**: Extract to a new module. The plan tentatively named `darnit.stores.env_subst`; on reflection, `darnit.core.env_subst` is the semantically better home because the helper predates and outscopes the stores subsystem (feature 025's `exec` handler is a sieve concern; feature 031's mcp `env` block is a handler concern; neither imports `darnit.stores`). Locate the helper at `packages/darnit/src/darnit/core/env_subst.py`.

Public API:

```python
def substitute_dollar_vars(
    template: str,
    env: Mapping[str, str] | None = None,
    *,
    missing_ok: bool = True,
) -> str:
    """Replace `$VAR` occurrences in `template` with values from `env`.

    `env` defaults to `os.environ`. If `missing_ok=True` (default, matches
    features 025/031 semantics), unset variables substitute as empty string.
    If `missing_ok=False`, unset variables raise `KeyError` naming the missing
    var (available for future callers that want strict semantics).

    `$$` is a literal `$` (escape). Non-alphanumeric-underscore chars after
    `$` terminate the variable name (so `$FOO/bar` -> value(FOO) + "/bar").
    """
```

Feature 025's existing helper (currently at `packages/darnit/src/darnit/sieve/builtin_handlers.py` in the `exec_handler`) and feature 031's helper (`packages/darnit/src/darnit/sieve/mcp_pool.py::_substitute_env`) both migrate to the shared implementation. Regression tests in `test_env_subst.py` reproduce the previous inputs from both call sites and assert identical output.

**Rationale**: Three copies is strictly worse than two. Extraction is a one-time cost; every future consumer of `$VAR` substitution (this feature's `[stores.*]` blocks, any future control-config surface) uses the shared helper. The regression tests catch the risk that the extraction changes behavior on either legacy call site.

**Alternatives considered**:
- **Leave the two existing copies alone and add a third for stores** (rejected -- see above).
- **Place under `darnit.stores.env_subst`** (rejected -- semantically wrong home; the helper is a config-substitution utility, not a stores utility).
- **Push to a separate package** (rejected -- overkill for ~30 LOC).

**Latent bug fix**: reading the two existing implementations closely, they DO disagree slightly. Feature 025's copy logs a debug line when a variable is unset; feature 031's does not. Both substitute empty string. The extracted helper preserves the substitute-empty-string behavior (the common case) and drops the debug log (feature 025 authors have not needed it in 6+ months). If the debug log turns out to matter, it can come back as an optional `debug_hook` callback.

---

### R-005: Config schema addition (`StoresConfig` / `StoreBlock`)

**Decision**: Mirror feature 031's `mcp_servers` shape.

```python
class StoreBlock(BaseModel):
    """One `[stores.<kind>]` block. `backend` is required; other keys pass
    through to the backend's __init__.
    """
    backend: str
    model_config = ConfigDict(extra="allow")

    # NOTE: model_extra fields are the backend-specific keys. String values
    # inside model_extra are passed through darnit.core.env_subst.substitute_dollar_vars
    # at load time; other types (int, bool, list) pass through unchanged.


class StoresConfig(BaseModel):
    """The four artifact-class-keyed store blocks. All optional; missing
    means filesystem default."""
    project: StoreBlock | None = None
    attestation: StoreBlock | None = None
    report: StoreBlock | None = None
    cache: StoreBlock | None = None
    model_config = ConfigDict(extra="forbid")


# On FrameworkConfig (framework_schema.py) and UserConfig (user_schema.py):
stores: StoresConfig = Field(default_factory=StoresConfig)
```

**Rationale**: `extra="forbid"` on `StoresConfig` locks the four-artifact-class invariant at the schema layer; a fifth key like `[stores.audit_log]` raises `ValidationError` at load time. `extra="allow"` on `StoreBlock` lets backend-specific keys pass through without the framework knowing what they are.

Merger addition is one line alongside feature 031's `mcp_servers` merger: `.baseline.toml`'s `[stores.<kind>]` block for a given kind fully replaces the framework TOML block for that kind (per-name replacement). Disjoint kinds coexist.

**Alternatives considered**:
- **One flat `stores: dict[str, StoreBlock]` at the top level** (rejected -- the four artifact classes are a schema invariant, not a runtime one; typed keys catch typos).
- **Require an explicit `backend = "filesystem"` in every default TOML** (rejected -- undermines User Story 2 zero-config path).

**References**: feature 031's `McpServerConfig` at `packages/darnit/src/darnit/config/framework_schema.py`.

---

### R-006: In-memory reference backend placement

**Decision**: Place under `packages/darnit-testchecks/src/darnit_testchecks/stores/`. `darnit-testchecks` is dev-only (not shipped in the runtime install of darnit-core), and its charter matches: "reference implementations useful for testing."

Four files, one per Protocol:

- `in_memory_project.py::InMemoryProjectStateStore`
- `in_memory_attestation.py::InMemoryAttestationStore`
- `in_memory_report.py::InMemoryReportStore`
- `in_memory_cache.py::InMemoryAuditCacheStore`

Each is a simple dict-backed implementation with `close()` as a no-op and a `_state` attribute that tests can inspect to assert on what was written.

**Rationale**: Placement under `darnit-testchecks` means any test suite in the workspace can import and use them without PYTHONPATH manipulation. If they lived under `tests/darnit/stores/fixtures/`, cross-test reuse would require test-collection-hook gymnastics.

**Alternatives considered**:
- **Under `tests/darnit/stores/fixtures/`** (rejected -- awkward cross-test reuse).
- **New `darnit-testkit` package** (rejected -- new package cost for what fits in existing `darnit-testchecks`).

---

### R-007: Fixture plugin package registration

**Decision**: The example plugin package under `tests/darnit/stores/fixtures/example_store_plugin_pkg/` is a real installable Python package with a real entry-point registration in its `pyproject.toml`. A session-scoped pytest fixture in `tests/darnit/stores/conftest.py` runs `pip install -e tests/darnit/stores/fixtures/example_store_plugin_pkg/` at session start and `pip uninstall -y example-store-plugin` at session end.

The example plugin's job is to register a no-op `AttestationStore` under `darnit.stores.attestation` so the discovery test can assert `discover_stores("darnit.stores.attestation")` finds it by name. The plugin's implementation is <20 LOC; the point is proving the entry-point mechanism works end-to-end.

**Rationale**: This mirrors feature 027's approach (`tests/darnit/harness/fixtures/mock_resolver_pkg/` with the same session-scoped install fixture). Both features prove the same property: entry-point discovery works against a real installable package, not against a stubbed-out fake.

**Alternatives considered**:
- **Statically add the fixture package to the workspace `pyproject.toml`** (rejected -- pollutes the runtime env for every test, not just discovery tests).
- **`sys.path` gymnastics to fake an entry point** (rejected -- the whole point of the test is proving discovery works against a REAL entry point, not a shim).
- **`pytest-mock` or similar to stub `importlib.metadata.entry_points`** (rejected -- see above).

**References**: feature 027's `tests/darnit/harness/fixtures/mock_resolver_pkg/` and its session-install fixture in `tests/darnit/harness/conftest.py`.

## Consolidated output

All NEEDS CLARIFICATION unknowns from Technical Context are resolved. Two decisions changed from the plan's tentative wording during Phase 0:

- Call-site count: 7 concrete rewrites + 1 no-op-in-v0 artifact class (Report). Plan said "~10" -- close enough that no plan revision needed, but tasks decomposition uses the exact table.
- `$VAR` helper placement: `darnit.core.env_subst` instead of `darnit.stores.env_subst` (semantic fit).

Proceeding to Phase 1.
