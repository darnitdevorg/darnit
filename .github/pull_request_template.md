## Summary

<!-- Brief description of changes -->

## Type of Change

- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature causing existing functionality to change)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)

## Framework Changes Checklist

If this PR modifies the darnit framework (`packages/darnit/`):

- [ ] Updated framework spec (`openspec/specs/framework-design/spec.md`) if behavior changed
- [ ] Ran `uv run python scripts/validate_sync.py --verbose` and it passes
- [ ] Ran `uv run python scripts/generate_docs.py` and committed any doc changes

## Control/TOML Changes Checklist

If this PR modifies controls or TOML configuration:

- [ ] Control metadata defined in TOML (not Python code)
- [ ] SARIF fields (description, severity, help_url) included where appropriate
- [ ] Ran validation to confirm TOML schema compliance

## Testing

- [ ] Tests pass locally (`uv run pytest tests/ -v`)
- [ ] Added tests for new functionality (if applicable)
- [ ] Linting passes (`uv run ruff check .`)

## Additional Notes

<!-- Any additional context, screenshots, or information -->
