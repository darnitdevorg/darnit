## Context

The OpenSSF Baseline TOML (`openssf-baseline.toml`) is 5,465 lines. ~40% (2,176 lines) are multi-line template strings embedded as TOML `"""` blocks. There are 52 named `[templates.*]` entries. The largest (`license_apache`) is 192 lines of verbatim license text.

The `TemplateConfig` model already has a `file: str | None` field (framework_schema.py:601), and the `RemediationExecutor._get_template_content()` already has partial resolution logic (executor.py:279-291). However, it resolves `file` relative to `local_path` (the audited repo), not the TOML file's directory. A detailed TODO at executor.py:220-270 documents the intended design.

The `ComplianceImplementation` protocol already exposes `get_framework_config_path() -> Path | None`, which returns the absolute path to the TOML file. This path is available in the orchestrator (which loads the TOML) but not threaded through to the executor.

## Goals / Non-Goals

**Goals:**
- External `.tmpl` files resolved relative to the framework TOML directory
- All 52 baseline templates migrated from inline `content` to `templates/*.tmpl`
- Validation that exactly one of `file` or `content` is set per template
- No behavior change for downstream consumers — `_get_template_content()` returns the same string regardless of source

**Non-Goals:**
- Remote template sources (HTTP/S, git, registries) — documented as future in executor.py
- Template inheritance or composition (`extends = "base"`)
- Splitting controls, context, or remediation into separate TOML files (deferred to separate change)
- A `templates_dir` metadata field — explicit `file` per template is sufficient

## Decisions

### Decision 1: Add `framework_path` parameter to `RemediationExecutor.__init__()`

**Choice:** Add an optional `framework_path: str | None` parameter to the executor constructor. When set, `file` references resolve relative to `Path(framework_path).parent`. When None, fall back to `local_path` for backward compatibility.

**Rationale:** The executor already has the resolution logic at line 279-291 — it just uses the wrong base path. Adding one parameter is the minimal change. The orchestrator already has the TOML path from `get_framework_path()` / `_get_framework_config()`, so threading it through is straightforward.

**Alternatives considered:**
- *Resolve at config load time (eagerly read all files into `content`):* Simpler consumer API, but would lose the ability to report which file failed to load, and would bloat memory for large template sets that may not all be used.
- *Store framework_path on FrameworkConfig:* Cleaner long-term but requires schema changes; the executor parameter is simpler and doesn't change the config model's serialization.

### Decision 2: Validate mutual exclusivity in `TemplateConfig`

**Choice:** Add a Pydantic `model_validator` to `TemplateConfig` that raises `ValueError` if both `file` and `content` are set, or if neither is set.

**Rationale:** Catches misconfiguration at TOML load time with a clear error message rather than silently ignoring one field. The validation runs once at startup, not per-template-use.

**Alternative considered:**
- *Precedence rule (content wins over file):* Less explicit, masks misconfiguration.

### Decision 3: `.tmpl` extension convention, not enforcement

**Choice:** Use `.tmpl` as the conventional extension for template files. The framework reads any text file — no extension check.

**Rationale:** `.tmpl` is visually distinct from `.md` (which might be confused with real project docs) and from `.toml`. But enforcing it adds no value and would break users who prefer `.txt` or `.md`.

### Decision 4: Migration script extracts templates programmatically

**Choice:** Write a one-time Python script (`scripts/extract_templates.py`) that reads `openssf-baseline.toml`, extracts each `[templates.*].content` to `templates/<name>.tmpl`, and rewrites the TOML entry to use `file = "templates/<name>.tmpl"`.

**Rationale:** 52 templates is too many to migrate by hand without errors. A script guarantees byte-identical content (no whitespace drift) and can be verified with a diff. The script is kept in `scripts/` for reference but is not part of the runtime.

### Decision 5: Templates directory lives alongside the TOML

**Choice:** `packages/darnit-baseline/src/darnit_baseline/templates/*.tmpl`, sibling to `openssf-baseline.toml`.

**Rationale:** This is the natural location — `get_framework_config_path()` returns the TOML path, and `Path(toml_path).parent / "templates"` resolves correctly both in development (editable install) and in installed packages (since the `templates/` directory will be included in the package via `pyproject.toml` package data).

**Impact on packaging:** Must add `templates/*.tmpl` to package data in `pyproject.toml` so pip installs include them.

### Decision 6: Thread framework_path through 3 call sites

**Choice:** Update the 3 `RemediationExecutor(...)` call sites:
1. `orchestrator.py:475` — has access to TOML path via `_get_framework_config()` / `get_framework_path()`
2. `tools.py:266` — same
3. `darnit-example/tools.py:183` — pass `None` (example plugin doesn't use file templates)

**Rationale:** Minimal blast radius. Each call site already loads the framework config, so the path is readily available.

## Risks / Trade-offs

**[Package data not included in wheel]** → Add explicit `[tool.setuptools.package-data]` or hatch equivalent in `pyproject.toml` for `*.tmpl` files. Verify with `pip install -e . && python -c "from darnit_baseline import get_framework_path; print(get_framework_path().parent / 'templates')"`.

**[Disk I/O per template lookup]** → Templates are read on demand (not eagerly). For a full remediation run touching ~30 templates, this adds ~30 small file reads. Acceptable — each file is <200 lines. Could add caching later if profiling shows it matters.

**[Migration script produces different TOML formatting]** → Use `tomli` to read and manual string manipulation to rewrite (not `tomli_w` which may reformat). Alternatively, use regex replacement on the raw TOML text to swap `content = """..."""` blocks with `file = "templates/name.tmpl"` while preserving all other formatting.

**[Backward compatibility for users referencing file relative to local_path]** → The current (broken) resolution resolves relative to `local_path`. After this change, `framework_path` takes priority. This is technically a behavior change, but no known users rely on the current broken behavior since no TOML configs currently use `file`.

## Open Questions

None — the scope is well-defined and the existing code already has the scaffolding (field, resolution stub, TODO documentation).
