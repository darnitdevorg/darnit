# Troubleshooting

Common issues and solutions for darnit development.

## 1. Tests Fail with GitHub API Errors

**Symptom**: Tests fail with `gh: not logged in` or `HTTP 401 Unauthorized` errors.

**Cause**: The GitHub CLI is not authenticated. Many tests use `gh api` commands.

**Solution**:
```bash
gh auth login
gh auth status  # Verify authentication
```

If already logged in but still failing, your token may lack required scopes:
```bash
gh auth refresh -s read:org,repo
```

---

## 2. `uv sync` Fails

**Symptom**: `uv sync` fails with dependency resolution errors or Python version mismatch.

**Cause**: Wrong Python version or outdated uv.

**Solution**:

Check Python version (must be 3.11+):
```bash
python3 --version
```

Update uv:
```bash
uv self update
```

If you have multiple Python versions, specify the version:
```bash
uv sync --python 3.12
```

---

## 3. `validate_sync.py` Fails After Code Changes

**Symptom**: `uv run python scripts/validate_sync.py --verbose` reports sync errors after modifying framework behavior.

**Cause**: The framework-design spec (`openspec/specs/framework-design/spec.md`) is out of sync with the code. The validator checks that the spec contains sections matching the implementation.

**Solution**:

1. Update the spec first:
   ```bash
   # Edit the spec to reflect your changes
   $EDITOR openspec/specs/framework-design/spec.md
   ```

2. Re-run validation:
   ```bash
   uv run python scripts/validate_sync.py --verbose
   ```

3. Regenerate docs:
   ```bash
   uv run python scripts/generate_docs.py
   ```

The validator checks for three required sections: "TOML Schema", "Built-in Pass Types", and "Sieve Orchestrator".

---

## 4. Ruff Linting Errors

**Symptom**: `uv run ruff check .` reports style or formatting errors.

**Cause**: Code doesn't match the project's linting rules.

**Solution**:

Auto-fix most issues:
```bash
uv run ruff check --fix .
```

Format code:
```bash
uv run ruff format .
```

For errors that can't be auto-fixed, read the error message — ruff provides clear explanations and fix suggestions.

---

## 5. Import Errors or Missing Packages

**Symptom**: `ModuleNotFoundError: No module named 'darnit'` or similar import errors.

**Cause**: Packages not installed in development mode, or virtual environment not activated.

**Solution**:

Re-sync all packages:
```bash
uv sync
```

Verify packages are installed:
```bash
uv run python -c "import darnit; print(darnit.__file__)"
uv run python -c "import darnit_baseline; print(darnit_baseline.__file__)"
```

Both should print paths within the `packages/` directory (editable installs).

---

## 6. Fork Workflow Issues

### Upstream remote not configured

**Symptom**: `git fetch upstream` fails with `fatal: 'upstream' does not appear to be a git repository`.

**Solution**:
```bash
git remote add upstream https://github.com/kusari-oss/darnit.git
git fetch upstream
```

### Rebase conflicts

**Symptom**: `git rebase upstream/main` shows merge conflicts.

**Solution**:
```bash
# View conflicting files
git status

# Resolve conflicts in each file, then:
git add <resolved-file>
git rebase --continue

# If you want to abort and start over:
git rebase --abort
```

### Push rejected after rebase

**Symptom**: `git push` fails with `non-fast-forward` after rebasing.

**Solution**:
```bash
git push --force-with-lease origin my-branch
```

Use `--force-with-lease` (not `--force`) to safely update your fork's branch.

---

## 7. CEL Expression Errors

**Symptom**: Controls unexpectedly return WARN/INCONCLUSIVE instead of PASS or FAIL.

**Cause**: CEL expression syntax errors or TOML escaping issues.

**Common fixes**:

1. **Use `!` not `not`** — CEL is C-style, not Python:
   ```toml
   # WRONG
   expr = 'not output.any_match'

   # CORRECT
   expr = '!(output.any_match)'
   ```

2. **Use `\.` not `\\.`** in TOML literal strings for regex dots:
   ```toml
   # WRONG — over-escaped
   expr = 'output.stdout.matches("v\\d+\\.\\d+")'

   # CORRECT
   expr = 'output.stdout.matches("v\d+\.\d+")'
   ```

3. **Use `&&` and `||`** not `and` and `or`:
   ```toml
   # WRONG
   expr = 'output.exit_code == 0 and output.json.enabled'

   # CORRECT
   expr = 'output.exit_code == 0 && output.json.enabled'
   ```

See the [CEL Reference](cel-reference.md) for complete syntax documentation.

---

## 8. Generated Docs Are Stale

**Symptom**: `git diff docs/generated/` shows unexpected changes, or CI fails with "docs would change".

**Cause**: The generated documentation is out of sync with the spec.

**Solution**:
```bash
uv run python scripts/generate_docs.py
git add docs/generated/
git commit -m "docs: Regenerate docs from spec"
```

Always regenerate docs after spec changes and include them in your commit.

---

## Getting More Help

If you're stuck:
- Check the [Framework Development](framework-development.md) guide for architecture details
- Open a [GitHub Issue](https://github.com/kusari-oss/darnit/issues)
- Start a [Discussion](https://github.com/kusari-oss/darnit/discussions)
- Back to [Getting Started](README.md)
