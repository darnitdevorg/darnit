## REMOVED Requirements

### Requirement: Legacy config models compatibility shim
**Reason**: The `darnit.config.models` module existed solely to re-export types from `darnit.config.schema` with deprecated aliases (`ReferenceStatus`, `ResourceReference`, `ControlStatus`). All internal consumers have been migrated to import from `darnit.config.schema` directly. The module and its deprecated classes are no longer needed.
**Migration**: Import `ProjectConfig` and other types from `darnit.config.schema` instead of `darnit.config.models`.

### Requirement: Reference validation module
**Reason**: The `darnit.config.validation` module defined reference validation functions (`validate_local_reference`, `validate_url_reference`, `validate_repo_reference`) that were never integrated into any code path. No callers exist in the codebase.
**Migration**: None required — no code depends on this module.

### Requirement: Bash test repository creation script
**Reason**: `scripts/create-test-repo.sh` was replaced by `scripts/create-example-test-repo.py` which provides better integration with the darnit framework and is the version referenced in documentation and tests.
**Migration**: Use `scripts/create-example-test-repo.py` instead.
