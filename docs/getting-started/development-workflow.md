# Development Workflow

This guide covers the day-to-day development workflow: branching, validation, committing, and submitting pull requests.

## Branch Naming

Create a branch with a descriptive name using these prefixes:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feat/` | New features | `feat/add-sarif-output` |
| `fix/` | Bug fixes | `fix/pattern-handler-escaping` |
| `docs/` | Documentation updates | `docs/getting-started-guide` |
| `refactor/` | Code refactoring | `refactor/simplify-sieve-pipeline` |
| `test/` | Test additions/fixes | `test/cel-expression-coverage` |

```bash
git checkout -b feat/my-feature
```

## Pre-Commit Validation Checklist

**Run all of these before every commit.** They match the checks that CI will run on your pull request.

### 1. Lint

```bash
uv run ruff check .
```

To auto-fix issues:

```bash
uv run ruff check --fix .
```

To format code:

```bash
uv run ruff format .
```

### 2. Run tests

```bash
uv run pytest tests/ --ignore=tests/integration/ -q
```

To run only framework tests:

```bash
uv run pytest tests/darnit/ -v
```

To run only implementation tests:

```bash
uv run pytest tests/darnit_baseline/ -v
```

### 3. Validate spec sync

```bash
uv run python scripts/validate_sync.py --verbose
```

This checks that the framework-design spec matches the implementation. If you've changed framework behavior, update the spec first.

### 4. Regenerate docs

```bash
uv run python scripts/generate_docs.py
```

Check if docs changed:

```bash
git diff docs/generated/
```

If they did, include the changes in your commit.

### 5. Rebase from upstream

```bash
git fetch upstream
git rebase upstream/main
```

Always rebase before pushing to keep history clean.

## Commit Messages

Write clear, concise commit messages:

```
type: short description

Longer description if needed explaining the what and why.
```

**Types**: `feat`, `fix`, `docs`, `test`, `refactor`, `ci`, `chore`

**Examples**:
```
feat: Add SARIF output formatter for audit results

fix: Correct CEL expression escaping in TOML literal strings

docs: Add getting started guide for contributors
```

## Pull Request Process

1. Push your branch to your fork:
   ```bash
   git push origin feat/my-feature
   ```

2. Open a Pull Request against the `main` branch on the upstream repository.

3. Fill out the PR template with:
   - What changed and why
   - How to test the changes
   - Any breaking changes

4. Wait for CI checks to pass and address review feedback.

## Spec Change Workflow

If you're modifying framework behavior (sieve pipeline, plugin protocol, configuration), follow this order:

1. **Update the spec first**: Edit `openspec/specs/framework-design/spec.md`
2. **Validate sync**: `uv run python scripts/validate_sync.py --verbose`
3. **Implement the change**: Modify the code to match the spec
4. **Regenerate docs**: `uv run python scripts/generate_docs.py`
5. **Commit spec, code, and docs together**

## Code Style

- Follow existing code patterns and conventions
- Write clear, self-documenting code
- Add comments only where necessary to explain complex logic
- All public APIs should have type annotations

## Next Steps

- [Testing Guide](testing.md) — How to run and write tests
- [Troubleshooting Guide](troubleshooting.md) — Common issues and solutions
- Back to [Getting Started](README.md)
