# Implementation Plan: Framework config loading works under wheel install

**Branch**: `021-fix-config-path` | **Date**: 2026-08-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/021-fix-config-path/spec.md`

## Summary

Fix a packaging bug in all three implementation packages (`darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility`): `get_framework_config_path()` uses `Path(__file__).parent.parent.parent / "<framework>.toml"`, which only resolves correctly in an editable checkout. In a wheel install, the ascend-three-levels walk lands outside the package and, more fundamentally, the TOML file is not included in the wheel at all.

**Fix applied (revised during implementation):** move each framework TOML INTO its `src/<module>/` tree (`packages/darnit-baseline/openssf-baseline.toml` -> `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`, and the same for `gittuf.toml` and `reproducibility.toml`). Hatchling's default `packages = ["src/<module>"]` glob then includes the TOML in the wheel automatically. `get_framework_config_path()` uses `importlib.resources.files(__package__) / "<toml>"` to resolve it at runtime. This works for both editable installs (importlib.resources finds the TOML in the source tree) and wheel installs (finds it in `site-packages/<module>/`). Matches the pattern already used by `darnit-hello` (the plugin reference implementation).

**Revision from the original plan:** the plan initially chose Option B (force-include the TOML from the sibling location into the wheel, keeping the on-disk layout unchanged). Implementation revealed that `importlib.resources.files(__package__)` returns the src tree, not the sibling location, so the resolver could not find the TOML under editable installs. See `research.md` R3-revised for details. Option A (move) is what shipped.

A wheel-install integration test (`tests/packaging/test_wheel_install_config.py`) locks in the acceptance bar for all three packages, exercising both path resolution and the `darnit list` CLI. Marked `@pytest.mark.slow`.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets).

**Primary Dependencies**: stdlib only — `importlib.resources` (Python 3.9+) for resource resolution; `hatchling` (existing build backend) for wheel packaging. No new runtime deps in any darnit package.

**Storage**: Filesystem only. The TOML file location on disk (repo root of each implementation package) does not change; only the wheel packaging and the resolver change.

**Testing**: pytest (existing). Add one integration test that builds a wheel, installs it into an isolated environment, and asserts `get_framework_config_path()` returns a readable path. This test would have caught the bug and MUST run in CI.

**Target Platform**: Any Python 3.11+ install path (`uv sync` editable checkout, `uv tool install`, `pip install`, container image, `shiv` binary). Zipped-import installs are not a supported channel today; the fix does not preclude them but does not add coverage.

**Project Type**: Library + CLI (Python package workspace). The change touches three implementation packages (`packages/darnit-baseline/`, `packages/darnit-gittuf/`, `packages/darnit-reproducibility/`); no framework core changes.

**Performance Goals**: N/A. Config loading is not on a hot path.

**Constraints**: The fix MUST NOT change the on-disk file layout of the repo (TOMLs stay at each package root next to `pyproject.toml`, matching current convention and preserving discoverability). The `ComplianceImplementation.get_framework_config_path()` protocol return type stays `Path | None`.

**Scale/Scope**: Three implementations, three `get_framework_config_path()` method bodies, three `pyproject.toml` `force-include` entries, one new integration test. Estimated diff: ~30 lines production + ~60 lines test.

## Constitution Check

*Constitution v1.3.0.*

- **I. Plugin Separation.** PASS. The framework package (`packages/darnit/`) is not touched. Each implementation package is modified in isolation; no cross-package imports are added.
- **II. Conservative-by-Default.** PASS. This is a packaging fix; no verdict semantics change. Failure mode of the bug is a hard error at framework config load, not a false-pass — the fix eliminates the hard error without introducing any silent success.
- **III. TOML-First Architecture.** PASS. The TOML remains the source of truth for controls. This fix ensures the TOML is *reachable* from installed packages, which strengthens the principle (a TOML that can't be loaded isn't a source of truth).
- **IV. Never Guess User Values.** PASS. Not applicable to this fix.
- **V. Sieve Pipeline Integrity.** PASS. Not applicable to this fix.

No violations. Complexity Tracking section left empty.

## Project Structure

### Documentation (this feature)

```text
specs/021-fix-config-path/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (minimal - protocol touch only)
├── quickstart.md        # Phase 1 output (wheel-install verification path)
├── contracts/
│   └── framework-config-resolution.md
└── tasks.md             # Phase 2 output (created by /speckit-tasks)
```

### Source Code (repository root)

```text
packages/darnit-baseline/
├── openssf-baseline.toml            # Unchanged on disk; now force-included into wheel
├── pyproject.toml                   # + force-include entry for openssf-baseline.toml
└── src/darnit_baseline/
    └── implementation.py            # get_framework_config_path() uses importlib.resources

packages/darnit-gittuf/
├── gittuf.toml                      # Unchanged on disk; force-include added
├── pyproject.toml                   # + force-include entry for gittuf.toml
└── src/darnit_gittuf/
    └── implementation.py            # get_framework_config_path() uses importlib.resources

packages/darnit-reproducibility/
├── reproducibility.toml             # Unchanged on disk; force-include added
├── pyproject.toml                   # + force-include entry for reproducibility.toml
└── src/darnit_reproducibility/
    └── implementation.py            # get_framework_config_path() uses importlib.resources

tests/darnit_baseline/                 (or a shared location — decided in tasks)
└── test_wheel_install_config.py      # Build wheel, install into tmp env, load config
```

**Structure Decision**: No new directories. Changes are confined to three implementation packages and one integration test file. The TOMLs remain at each package root (existing convention; preserves discoverability for anyone browsing the repo). The wheel packaging places a *copy* of each TOML inside the installed package tree via hatchling `force-include`, which is the exact pattern already used for `darnit-baseline`'s `templates/` directory.

## Complexity Tracking

*No constitution violations. Table left empty.*
