# Phase 0 Research: Framework config loading works under wheel install

**Feature**: 021-fix-config-path
**Date**: 2026-08-04

## R1: Root cause of the bug

**Observation:** All three implementation packages resolve their framework TOML via:

```python
return Path(__file__).parent.parent.parent / "openssf-baseline.toml"
```

(`packages/darnit-baseline/src/darnit_baseline/implementation.py:130`; identical pattern at `packages/darnit-gittuf/src/darnit_gittuf/implementation.py:76` and `packages/darnit-reproducibility/src/darnit_reproducibility/implementation.py:94`).

**Editable install path resolution:**

- `__file__` = `<repo>/packages/darnit-baseline/src/darnit_baseline/implementation.py`
- `.parent` = `<repo>/packages/darnit-baseline/src/darnit_baseline/`
- `.parent.parent` = `<repo>/packages/darnit-baseline/src/`
- `.parent.parent.parent` = `<repo>/packages/darnit-baseline/`
- `+ "openssf-baseline.toml"` = `<repo>/packages/darnit-baseline/openssf-baseline.toml` (correct, file exists)

**Wheel install path resolution:**

- `__file__` = `<venv>/lib/python3.12/site-packages/darnit_baseline/implementation.py`
- `.parent.parent.parent` = `<venv>/lib/python3.12/` (outside site-packages)
- Resulting path: `<venv>/lib/python3.12/openssf-baseline.toml` (file does not exist)

Additionally, the current wheel packaging (`[tool.hatch.build.targets.wheel] packages = ["src/darnit_baseline"]`) does not include the TOML file *anywhere* in the wheel, since the TOML lives at the package repo root (`packages/darnit-baseline/openssf-baseline.toml`), sibling to `src/`, not inside it. So even a corrected relative-path walk would find no file in a wheel install.

**Conclusion:** Two bugs stack. The resolver walks to the wrong place, AND the wheel doesn't contain the TOML. Both must be fixed.

## R2: Resolution mechanism — `importlib.resources.files()`

**Decision:** Use `importlib.resources.files(__package__) / "<framework>.toml"` in each implementation's `get_framework_config_path()`.

**Rationale:**

- `importlib.resources.files()` is stdlib since Python 3.9; project targets 3.11+.
- Returns a `Traversable` that, for filesystem-backed installs (the common case), is a `MultiplexedPath` or `PosixPath` and can be converted to `pathlib.Path` via `str()` and `Path()`.
- Handles both editable installs (finds the file via the source-tree layout) and wheel installs (finds the file in `site-packages/<package>/`).
- Requires the TOML file to be present *inside* the installed package tree, not sibling to it.

**Alternatives considered:**

- `pkg_resources.resource_filename()` — legacy, part of `setuptools`; adds a runtime dep on `setuptools` for a stdlib-covered use case. Rejected.
- `importlib.util.find_spec(__package__).origin` and manual pathing — brittle and does not handle namespace packages. Rejected.
- Environment variable override — would work but pushes the problem to operators. Rejected as a primary mechanism (may be useful as a future escape hatch, out of scope for this fix).

**Zipped-import caveat:** `Traversable` is not always a real filesystem path. For zipped-wheel installs, `str(files(pkg) / name)` returns a synthetic path that `pathlib.Path` cannot open directly; the correct call in that case is `importlib.resources.as_file()` (context manager). The project does not ship or support zipped installs today. To keep the fix minimal, this plan converts `Traversable` -> `Path` via `str()` and documents the zipped-import limitation. If a zipped-install channel becomes real (e.g., `shiv` binary), a follow-up can move framework config loading to a `Traversable`-aware loader.

## R3-revised: Packaging mechanism — move TOML into `src/<module>/`

**Decision (as shipped):** move each framework TOML into its `src/<module>/` tree. Hatchling's default `packages = ["src/<module>"]` glob then includes it in the wheel automatically. `importlib.resources.files(__package__) / "<toml>"` resolves under both editable and wheel installs.

**Why the original decision (Option B, force-include) was reversed:** implementation discovered that `importlib.resources.files(__package__)` returns a `Traversable` rooted at the src tree — for `darnit_baseline`, `packages/darnit-baseline/src/darnit_baseline/`. Under editable installs, this is the actual source directory. Under wheel installs, this is `site-packages/darnit_baseline/`. Neither location sees a sibling `openssf-baseline.toml` at the package root; the file MUST be inside the src tree for the resolver to find it.

Option B (force-include) would have made the wheel work (the TOML lands inside the installed package tree), but editable installs would have been silently broken because the resolver would look inside `src/darnit_baseline/` and not find the TOML (which was still at the sibling location on disk). Editable-install regression is unacceptable per FR-004.

The corrected fix requires TWO changes together: (1) TOML on disk inside `src/<module>/`, (2) resolver via `importlib.resources`. Force-include is no longer needed.

**Followon:** `darnit-baseline`'s `templates/` directory was also at the package root (sibling to `src/`). The TOML references templates by relative path (`templates/foo.tmpl`, resolved relative to the TOML's location). Moving the TOML but not the templates broke that relative-path resolution. The templates directory was moved into `src/darnit_baseline/templates/` alongside the TOML. The force-include entry for templates was removed (default hatchling glob picks them up).

**Alternatives reconsidered:**

- **Original Option B (force-include, TOML stays at package root):** rejected during implementation (see above). Broke editable install.
- **Runtime dual-path fallback in the resolver** (try src, then sibling): fragile; drift risk between editable and wheel behavior. Rejected.

## R3-original: Packaging mechanism — hatchling `force-include` (not shipped)

**Decision:** Add `[tool.hatch.build.targets.wheel.force-include]` in each implementation's `pyproject.toml` to place the TOML inside the installed `<package>/` directory.

**Rationale:**

- `darnit-baseline` already uses this exact mechanism for its `templates/` directory:

  ```toml
  [tool.hatch.build.targets.wheel.force-include]
  "templates" = "darnit_baseline/templates"
  ```

  So this is the established convention in the codebase, not a new pattern.
- Preserves the current on-disk layout of the repo. The TOML stays at `packages/<pkg>/<framework>.toml` alongside `pyproject.toml`, which is where a maintainer browsing the repo expects to find it.
- Zero impact on other build tooling (`uv build`, CI publish workflows).
- Symmetric across all three implementations.

**Alternatives considered:**

- Move the TOML into `src/<module>/` so hatchling's default `packages = ["src/<module>"]` glob picks it up automatically. Cleaner from a Python-packaging purism standpoint, and eliminates the `force-include` line. Rejected because: (1) it changes on-disk layout, hurting discoverability; (2) references in `ARCHITECTURE.md`, `CLAUDE.md`, and prior spec artifacts (010, 011, 019) would go stale; (3) the codebase already has a working `force-include` pattern for exactly this problem.
- Ship the TOML as a separate data-only package. Overkill for three files; adds a release channel per implementation. Rejected.

## R4: Test coverage

**Decision:** Add one integration test that builds the wheel for `darnit-baseline`, installs it into an isolated environment, and asserts `get_framework_config_path()` returns a readable Path. Repeat (or parameterize) for `darnit-gittuf` and `darnit-reproducibility`.

**Rationale:**

- Unit tests cannot catch this bug — they run against the editable install where the buggy resolver happens to work.
- The test MUST spend an actual wheel build + install cycle to exercise the failure mode.
- Marked `slow` (or similar) so it does not run on every developer save; runs in CI on every PR.

**Alternatives considered:**

- Snapshot test of the built wheel's file listing (`unzip -l dist/*.whl`) asserting the TOML is present. Weaker: proves packaging but not that the resolver finds it. Rejected as sole coverage; may be added as a fast preflight.
- Skip integration coverage, rely on manual verification. Rejected — the whole reason this bug survived is that no automated coverage exists for the wheel install path.

## R5: Migration guidance for downstream plugin authors

**Decision:** Add a short docs note (README or CLAUDE.md snippet, TBD in tasks) telling plugin authors:

- Do NOT use `Path(__file__).parent...` to locate framework TOML.
- Use `importlib.resources.files(__package__) / "<your-framework>.toml"`.
- Add `[tool.hatch.build.targets.wheel.force-include]` (or the equivalent for your build tool) to ensure the TOML lands inside the installed package.

**Rationale:** Plugin authors outside this repo may have copied the buggy pattern from an implementation's source. A short migration note prevents perpetuating the bug in the plugin ecosystem.

**Alternatives considered:**

- Add a runtime warning in the framework if it detects a `Path(__file__)...` return. Too intrusive for a bug-fix release; framework doesn't know what path is "correct" for a downstream. Rejected.
