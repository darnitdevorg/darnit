## 1. Package Skeleton

- [x] 1.1 Create `packages/darnit-example/pyproject.toml` with entry points for `darnit.implementations` and `darnit.frameworks`
- [x] 1.2 Create `src/darnit_example/__init__.py` with `register()` and `get_framework_path()` functions
- [x] 1.3 Create `src/darnit_example/implementation.py` with `ExampleHygieneImplementation` class satisfying `ComplianceImplementation` protocol
- [x] 1.4 Create empty `__init__.py` files for `controls/` and `remediation/` subpackages

## 2. TOML Configuration

- [x] 2.1 Create `example-hygiene.toml` with metadata section matching implementation properties
- [x] 2.2 Define templates for README and .gitignore remediation
- [x] 2.3 Define 6 TOML controls (PH-DOC-01, PH-DOC-02, PH-SEC-01, PH-CFG-01, PH-CFG-02, PH-QA-01) using `file_must_exist` deterministic passes
- [x] 2.4 Add multi-phase passes to PH-SEC-01 (deterministic + pattern + manual)
- [x] 2.5 Add context definition for project_name

## 3. Python Controls

- [x] 3.1 Create `controls/level1.py` with PH-DOC-03 (ReadmeHasDescription) using factory function pattern and custom pattern analyzer
- [x] 3.2 Create PH-CI-01 (CIConfigExists) with glob-based CI config detection
- [x] 3.3 Register both controls via `register_control()` with appropriate pass lists

## 4. Remediation

- [x] 4.1 Create `remediation/registry.py` with `REMEDIATION_REGISTRY` mapping controls to fix functions
- [x] 4.2 Create `remediation/actions.py` with `create_readme()` and `create_gitignore()` supporting dry_run mode

## 5. Handler Registration

- [x] 5.1 Create `tools.py` with stub `example_hygiene_check` async handler
- [x] 5.2 Implement `register_handlers()` in implementation class

## 6. Framework Integration

- [x] 6.1 Add `"darnit_example."` to `ALLOWED_MODULE_PREFIXES` in `packages/darnit/src/darnit/core/handlers.py`
- [x] 6.2 Add `darnit-example = { workspace = true }` to root `pyproject.toml` `[tool.uv.sources]`
- [x] 6.3 Add `"darnit_example"` to `tool.ruff.lint.isort.known-first-party`

## 7. Tests

- [x] 7.1 Create `tests/darnit_example/conftest.py` with `make_context`, `empty_project`, and `full_project` fixtures
- [x] 7.2 Create `test_implementation.py` with protocol compliance, property, control count, handler, and register() tests
- [x] 7.3 Create `test_controls.py` with pass/fail tests for PH-DOC-03 and PH-CI-01
- [x] 7.4 Create `test_remediation.py` with dry_run, create, skip, and content tests for both actions

## 8. Documentation

- [x] 8.1 Create `packages/darnit-example/README.md` with control table and guide-section mapping
- [x] 8.2 Update `docs/IMPLEMENTATION_GUIDE.md` Prerequisites section with callout to example package
- [x] 8.3 Add darnit-example entries to Key file paths table in IMPLEMENTATION_GUIDE.md

## 9. Validation

- [x] 9.1 Run `uv sync` to verify package installs successfully
- [x] 9.2 Run `uv run ruff check .` with zero errors
- [x] 9.3 Run `uv run pytest tests/darnit_example/ -v` with all tests passing
- [x] 9.4 Run `uv run pytest tests/ --ignore=tests/integration/ -q` to confirm no regressions
