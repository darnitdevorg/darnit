# Contract: Framework Config Resolution

**Feature**: 021-fix-config-path
**Status**: Enforced (was: broken under wheel install)

This contract governs how an implementation package tells the framework where to find its framework TOML file.

## Contract

Every implementation package registered under the `darnit.implementations` entry point MUST provide a `get_framework_config_path(self) -> Path | None` method on its `ComplianceImplementation` class such that:

1. **Install-mode independence.** The returned Path MUST resolve to an existing, readable file whether the package was installed via editable mode (`uv sync` from a git checkout) or via a built wheel (`uv tool install`, `pip install`, container image, or any other wheel-based channel).

2. **Package-scoped resolution.** The implementation MUST NOT compute the path by walking up from `__file__` in a way that assumes a particular relative source-tree layout. Instead, the implementation MUST use a mechanism that queries the installed package's own resource tree — the recommended and enforced mechanism is `importlib.resources.files(__package__) / "<framework>.toml"`.

3. **TOML packaging.** The implementation's build configuration MUST include the framework TOML file inside the built wheel. Under `hatchling`, this is achieved with a `[tool.hatch.build.targets.wheel.force-include]` entry that copies the TOML into the installed package directory. Any other build backend MUST achieve the equivalent effect: after `pip install <wheel>`, the file MUST be discoverable via `importlib.resources.files(__package__) / "<framework>.toml"`.

4. **Clear error on absence.** If the TOML is missing from the installed package (a build-tool misconfiguration or corrupted install), `get_framework_config_path()` SHOULD raise a `FileNotFoundError` (or return `None` and let the caller raise) with a message that names which implementation is missing its TOML, rather than returning a nonexistent Path.

5. **Return-type stability.** The method MUST return `pathlib.Path` (or `None`), not a `Traversable` or a `str`. Callers today rely on `Path` semantics (`.exists()`, `.read_text()`, being passed to `tomllib.load()` via an open file).

## Test obligations

A conforming implementation MUST include (or be covered by) an integration test that:

- Builds the package's wheel with the project's normal build tooling.
- Installs the wheel into an isolated environment (fresh venv, no editable link).
- Instantiates the implementation and calls `get_framework_config_path()`.
- Asserts the returned Path exists AND is readable AND parses as valid TOML.

This test would have caught the pre-021 bug.

## Applies to

- `darnit-baseline` (fixed by feature 021)
- `darnit-gittuf` (fixed by feature 021)
- `darnit-reproducibility` (fixed by feature 021)
- Any future implementation package registered under `darnit.implementations`
- Any third-party plugin package that opts into darnit's plugin system

## Non-goals

- Zipped-import support (`shiv`-style single-file archives): not required by this contract. If a downstream channel adds zipped imports, framework config loading may need to switch from `Path` to `Traversable` end-to-end, which is a separate change.
- Runtime override of the TOML path (e.g., via env var): not part of this contract. If needed later, add via `.baseline.toml` overrides, not by mutating `get_framework_config_path()`.
