## 1. Schema & Validation

- [x] 1.1 Add `model_validator` to `TemplateConfig` in `packages/darnit/src/darnit/config/framework_schema.py` enforcing exactly one of `file` or `content` is set (raise `ValueError` if both or neither)
- [x] 1.2 Add unit tests for the validator: both-set raises, neither-set raises, file-only valid, content-only valid

## 2. Framework Path Propagation

- [x] 2.1 Add `framework_path: str | None = None` parameter to `RemediationExecutor.__init__()` in `packages/darnit/src/darnit/remediation/executor.py`; store as `self._framework_path`
- [x] 2.2 Update `_get_template_content()` to resolve `template.file` relative to `Path(self._framework_path).parent` when `self._framework_path` is set, falling back to `self.local_path` when None
- [x] 2.3 Thread `framework_path` through the 3 call sites: `orchestrator.py:475` (use `get_framework_path()`), `tools.py:266` (same), `darnit-example/tools.py:183` (pass `None`)
- [x] 2.4 Add unit tests: file resolved relative to framework dir, absolute path used as-is, missing file returns None with warning, fallback to local_path when framework_path is None

## 3. Migration Script

- [x] 3.1 Create `scripts/extract_templates.py` that reads `openssf-baseline.toml`, extracts each `[templates.*].content` to `templates/<name>.tmpl`, and rewrites the TOML entry to `file = "templates/<name>.tmpl"` (preserving `description` and other fields)
- [x] 3.2 Run the script and verify: 52 `.tmpl` files created, TOML entries rewritten, `diff` shows no content drift between old inline and new file contents

## 4. Package Data

- [x] 4.1 Update `packages/darnit-baseline/pyproject.toml` to include `templates/*.tmpl` in package data so `pip install` bundles them
- [x] 4.2 Verify with: `pip install -e packages/darnit-baseline && python -c "from darnit_baseline import get_framework_path; p = get_framework_path(); print(list((p.parent / 'templates').glob('*.tmpl'))[:3])"`

## 5. Migrate Templates

- [x] 5.1 Run `scripts/extract_templates.py` against `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`
- [x] 5.2 Verify the TOML still loads: `python -c "from darnit_baseline import get_framework_path; import tomllib; tomllib.load(open(get_framework_path(), 'rb'))"`
- [x] 5.3 Verify template resolution end-to-end: run `uv run pytest tests/darnit_baseline/ -q` — all existing remediation tests pass with file-sourced templates

## 6. Update Spec & Docs

- [x] 6.1 Update `openspec/specs/framework-design/spec.md` section 4.5 to document the `file` field on `[templates.*]`
- [x] 6.2 Run `uv run python scripts/generate_docs.py` and commit any changes to `docs/generated/`

## 7. Validation

- [x] 7.1 `uv run ruff check .` passes
- [x] 7.2 `uv run pytest tests/ --ignore=tests/integration/ -q` — all tests pass
- [x] 7.3 `uv run python scripts/validate_sync.py --verbose` — spec sync passes
- [x] 7.4 Verify TOML line count dropped by ~2,000 lines: `wc -l packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`
