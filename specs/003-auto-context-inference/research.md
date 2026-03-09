# Research: Auto Context Inference

## R1: `os.path.isfile()` vs `os.path.exists()` safety

**Decision**: Change `file_exists_handler` line 72 from `os.path.isfile()` to `os.path.exists()`.

**Rationale**: The handler's docstring says "Check if any file from a list of paths exists" — the word "file" is used generically. The TOML `ci_provider` detect pipeline already passes `.github/workflows` (a directory). No caller depends on it being a regular file specifically. `os.path.exists()` returns `True` for files, directories, and symlinks — exactly what we need.

**Alternatives considered**:
- `os.path.isfile() or os.path.isdir()` — more explicit but verbose for no benefit
- Adding a separate `dir_exists` handler — unnecessary complexity for same result

## R2: TOML detect pipeline behavior for `has_releases`

**Decision**: Add 3 filesystem-based detect steps before the existing `gh release list` step, using existing handlers (`file_exists` for files, `exec` for git tags).

**Rationale**: The detect pipeline stops at the first PASS result (confirmed in `_run_detect_pipeline` code at context_storage.py:537+). Adding local steps before the API step means offline detection works and API is only called as a fallback.

**Detection steps**:
1. `file_exists` with glob `".github/workflows/release*"` → catches release workflows
2. `file_exists` with `["CHANGELOG.md", "CHANGELOG", "CHANGES.md", "CHANGES"]` → catches changelog files
3. `exec` with `git tag --list "v*"` + CEL `expr = 'output.stdout != ""'` → catches semver tags
4. Existing `gh release list` step (unchanged)

**Alternatives considered**:
- Pure Python detector in context sieve — violates spec's TOML-first principle
- Confidence scoring across signals — clarification Q2 settled this: single signal sufficient

## R3: Platform context definition in TOML

**Decision**: Add `[context.platform]` with `exec` handler using `git remote get-url origin` and shell grep/CEL to extract hostname.

**Rationale**: The `exec` handler supports CEL expressions via the orchestrator's `_apply_cel_expr()`. We can run `git remote get-url origin` and use `expr` to match `github.com` or `gitlab.com` in the output. The detect pipeline's `value_if_pass` provides the mapped value.

**Challenge**: The `exec` handler only evaluates exit codes and optional CEL — it doesn't do substring matching natively. But we can use CEL string functions: `output.stdout.contains("github.com")`.

**Pipeline**:
1. `exec` with `git remote get-url origin` + `expr = 'output.stdout.contains("github.com")'` + `value_if_pass = "github"`
2. `exec` with `git remote get-url origin` + `expr = 'output.stdout.contains("gitlab.com")'` + `value_if_pass = "gitlab"`
3. `file_exists` with `[".github"]` + `value_if_pass = "github"` (directory fallback, needs FR-1 fix)

**Failure behavior**: When `git remote get-url origin` exits non-zero (no remote), the exec handler returns FAIL, pipeline continues to next step. If all steps fail, `platform` appears in pending with `current_value: null` (per clarification Q1).

**Alternatives considered**:
- Using `detect_platform()` from auto_detect.py via sieve — works but adds Python dependency instead of TOML-declarative
- Parsing remote URL in Python — violates TOML-first, and sieve is out of scope per spec

## R4: Merging persisted context into `collect_auto_context()`

**Decision**: At the top of `collect_auto_context()`, load `.project/darnit.yaml` via `load_context()`, flatten the categorized dict to bare keys, and merge into the result dict. Persisted values take precedence.

**Rationale**: Per clarification Q3, all persisted keys should be merged. The function already returns a flat `dict[str, Any]` with bare keys. Loading the stored config and flattening `{category: {key: ContextValue}}` to `{key: value}` is straightforward.

**Implementation sketch**:
```python
def collect_auto_context(local_path: str) -> dict[str, Any]:
    context: dict[str, Any] = {}

    # Load persisted context first (takes precedence)
    try:
        from darnit.config.context_storage import load_context
        stored = load_context(local_path)
        for category_values in stored.values():
            for key, ctx_val in category_values.items():
                context[key] = ctx_val.value
    except Exception:
        pass  # Graceful degradation if no config exists

    # Auto-detect (only for keys not already persisted)
    if "platform" not in context:
        platform = detect_platform(local_path)
        if platform:
            context["platform"] = platform
    # ... same pattern for other keys
```

**Alternatives considered**:
- Separate function for persisted context — adds unnecessary API surface
- Only merging specific keys — clarification Q3 rejected this

## R5: CEL `contains()` availability in celpy

**Decision**: Use `output.stdout.contains("github.com")` in CEL expressions for platform detection.

**Rationale**: The celpy library supports the CEL string `.contains()` method. This is part of the CEL standard library. The project already uses CEL expressions extensively in the TOML controls (e.g., `output.json.two_factor_requirement_enabled == true`).

**Risk**: Need to verify celpy supports `.contains()` on string types. If not, fall back to a regex-based approach or use the `matches()` function.
