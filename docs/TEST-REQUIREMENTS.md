# Test Requirements for Contributions

## Before Submitting a Pull Request

All contributions must include appropriate tests:

1. **New features**: Include unit tests covering the main functionality and edge cases
2. **Bug fixes**: Include a regression test that reproduces the bug and verifies the fix
3. **Refactoring**: Ensure existing tests still pass; add tests if coverage gaps are found

## Running Tests Locally

### Python

```bash
# Run tests
uv run pytest

# Run linting
uv run ruff check .
```

## CI Checks

All pull requests are tested in CI — see [`.github/workflows/`](../.github/workflows/)
for workflow configuration. Tests must pass before merge. Maintainers may request
additional test coverage during review.