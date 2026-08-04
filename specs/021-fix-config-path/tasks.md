---

description: "Task list for feature 021: framework config loading works under wheel install"
---

# Tasks: Framework config loading works under wheel install

**Input**: Design documents from `/specs/021-fix-config-path/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/framework-config-resolution.md](contracts/framework-config-resolution.md), [quickstart.md](quickstart.md)

**Tests**: Required. Success Criterion SC-003 in `spec.md` explicitly requires an integration test that would have caught the pre-021 bug, running in CI on every PR. Test-first (write, watch fail, then fix).

**Organization**: One user story (US1). Phase 1 has a single environment check; Phase 2 (Foundational) is empty because no prerequisites exist within this feature. Phase 3 (US1) contains the failing test, the three parallel per-package fixes, and a verification checkpoint. Phase 4 (Polish) contains a docs note for plugin authors.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the local dev environment can build wheels and run isolated installs (the fix's test depends on `uv build` succeeding for each implementation package).

- [X] T001 Verify `uv build --package darnit-baseline` succeeds against the current tree (before-fix baseline). Discard `dist/`. Confirm `uv` and `python -m venv` are available. No file changes; environment sanity check only.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None. This feature does not add framework-level scaffolding; both the test and the fix are self-contained per package. Proceed directly to Phase 3.

---

## Phase 3: User Story 1 - darnit works after wheel install (Priority: P1) MVP

**Goal**: `get_framework_config_path()` resolves to a readable path for all three implementation packages when installed from a built wheel, without regressing editable installs.

**Independent Test**: Build the wheel for each of `darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility`, install into a fresh venv, call `get_framework_path()` on each; every call MUST return an existing, readable Path pointing to that implementation's framework TOML. Regression check: `uv sync` editable install continues to load framework configs.

### Tests for User Story 1 (write FIRST, ensure they FAIL, then implement)

- [X] T002 [P] [US1] Add an integration test at `tests/packaging/test_wheel_install_config.py` (create `tests/packaging/` and `tests/packaging/__init__.py`; the test parameterizes over all three implementations so it does NOT belong under any single `tests/darnit_*/` subtree) that:
  - Uses pytest's `tmp_path` fixture as the working directory for all build/install artifacts (do NOT let `uv build` write to the repo's `dist/`).
  - For each of `darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility` (parameterized via `@pytest.mark.parametrize`):
    - Builds the wheel: `subprocess.run(["uv", "build", "--package", "<name>", "--out-dir", str(tmp_path / "dist")], cwd=<repo root>, check=True)`. Compute repo root from `Path(__file__).parents[2]` (i.e., `tests/packaging/test_wheel_install_config.py` -> up to repo root).
    - Creates a temporary venv at `tmp_path / "venv"` via `venv.EnvBuilder(with_pip=True).create(...)`. Use `sys.executable` implicitly (the current interpreter, which the test suite runs under; project targets Python 3.11+).
    - Installs the built wheel plus `darnit-core` into that venv via the venv's `pip`: `subprocess.run([venv_python, "-m", "pip", "install", str(wheel_path), "darnit-core"], check=True, capture_output=True)`. Locate `venv_python` as `tmp_path / "venv" / "bin" / "python"` (POSIX) or the equivalent on Windows via `sysconfig.get_path("scripts")`.
    - **Path resolution check:** runs a subprocess in the venv's python that imports `<package>`, calls `get_framework_path()`, and prints the path. Asserts the printed path exists, is readable, and parses as valid TOML (`tomllib.load`).
    - **CLI check (closes SC-001):** invokes the `darnit` console script installed by `darnit-core` (path: `venv/bin/darnit` on POSIX; `python -m darnit` does NOT work because darnit has no `__main__.py`). Asserts exit code 0, that the framework key appears in stdout, and that the substring `error loading` does NOT appear anywhere in stdout or stderr. Catches the case where `get_framework_path()` returns a path but the loader can't read it.
  - Marks the test `@pytest.mark.slow` (registered in root `pyproject.toml:78`; `--strict-markers` is on, so this name is required).
  - Relies on `tmp_path` fixture cleanup for teardown; no manual `rmtree` needed.
  Run the test and confirm it FAILS on the current tree (all three cases fail: either path does not exist, or wheel does not contain the TOML, or `darnit list` prints "error loading"). Record the failure output in the PR description.

### Implementation for User Story 1

Each of T003-T005 fixes one implementation package. All three are file-disjoint and can run in parallel.

- [X] T003 [P] [US1] Fix `darnit-baseline`:
  - In `packages/darnit-baseline/pyproject.toml`, extend the existing `[tool.hatch.build.targets.wheel.force-include]` table with a new line: `"openssf-baseline.toml" = "darnit_baseline/openssf-baseline.toml"`. Keep the existing `templates` entry and the comment about `opengrep_rules` intact.
  - In `packages/darnit-baseline/src/darnit_baseline/implementation.py`, replace the body of `get_framework_config_path()` (currently `return Path(__file__).parent.parent.parent / "openssf-baseline.toml"` at line ~130) with an `importlib.resources`-based lookup:
    ```python
    from importlib.resources import files
    resource = files(__package__) / "openssf-baseline.toml"
    path = Path(str(resource))
    if not path.is_file():
        raise FileNotFoundError(
            f"openssf-baseline.toml not found in installed darnit_baseline package at {path}. "
            f"This indicates a broken build; check the wheel's force-include configuration."
        )
    return path
    ```
    Preserve the docstring; update the "Navigate from implementation.py to package root" comment to reflect the new mechanism (or delete it).
  - Do NOT change `packages/darnit-baseline/src/darnit_baseline/__init__.py`; `get_framework_path()` there already delegates to `implementation.get_framework_config_path()`, so it inherits the fix.

- [X] T004 [P] [US1] Fix `darnit-gittuf`:
  - In `packages/darnit-gittuf/pyproject.toml`, add a new `[tool.hatch.build.targets.wheel.force-include]` section (currently absent) with: `"gittuf.toml" = "darnit_gittuf/gittuf.toml"`.
  - In `packages/darnit-gittuf/src/darnit_gittuf/implementation.py`, replace the body of `get_framework_config_path()` at line ~76 (`return Path(__file__).parent.parent.parent / "gittuf.toml"`) with the same `importlib.resources` pattern used in T003, substituting `gittuf.toml` and the appropriate error message.

- [X] T005 [P] [US1] Fix `darnit-reproducibility`:
  - In `packages/darnit-reproducibility/pyproject.toml`, add a new `[tool.hatch.build.targets.wheel.force-include]` section (currently absent) with: `"reproducibility.toml" = "darnit_reproducibility/reproducibility.toml"`.
  - In `packages/darnit-reproducibility/src/darnit_reproducibility/implementation.py`, replace the body of `get_framework_config_path()` at line ~94 (`return Path(__file__).parent.parent.parent / "reproducibility.toml"`) with the same `importlib.resources` pattern, substituting `reproducibility.toml` and the appropriate error message.

### Verification for User Story 1

- [X] T006 [US1] Re-run the integration test from T002. All three parameterized cases MUST now PASS. If any case still fails, do NOT proceed; diagnose whether the wheel truly contains the TOML (`unzip -l dist/*.whl | grep '\.toml$'`) and whether the resolver returns the correct path (`python -c "from importlib.resources import files; print(files('<pkg>') / '<toml>')"`).

- [X] T007 [US1] Run the full existing test suite excluding slow tests (the new wheel-build test is `@pytest.mark.slow` and is already validated by T006): `uv run pytest tests/ --ignore=tests/integration/ -m "not slow" -q`. No pre-existing tests should fail. If any do, investigate whether the change affects editable-install path resolution (it should not).

- [X] T008 [US1] Run the quickstart.md manual verification steps for the editable install (`uv sync` + `get_framework_path()`) to confirm no regression. Optional: also run the wheel-install steps for all three packages as a hand check.

**Checkpoint**: All three implementation packages resolve their framework TOML correctly under both editable and wheel installs. Integration test in CI locks this in going forward.

---

## Phase 4: Polish

**Purpose**: A short docs note so downstream plugin authors do not copy the pre-021 buggy pattern into their own implementations.

- [X] T009 [P] Add a short "Framework config resolution" subsection to `CLAUDE.md` under the "Creating a New Implementation" section (near line 145) explaining that:
  - `get_framework_config_path()` MUST use `importlib.resources.files(__package__) / "<framework>.toml"`, not `Path(__file__).parent...`.
  - The framework TOML MUST be included in the built wheel via `[tool.hatch.build.targets.wheel.force-include]` (or the equivalent for the plugin's build backend).
  - Point to the three in-repo implementations as reference examples.
  Keep the subsection to under 15 lines. Do not create a new docs file.

- [X] T010 [P] Update the "Recent Changes" block in `CLAUDE.md` (line 367) to add a one-line entry: `021-fix-config-path: framework TOML now loaded via importlib.resources; wheel installs work.`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Sanity check; no code dependencies.
- **Foundational (Phase 2)**: Empty; skip.
- **User Story 1 (Phase 3)**: T002 (failing test) MUST land first. T003, T004, T005 can then run in parallel. T006 depends on all of T003-T005. T007 and T008 depend on T006.
- **Polish (Phase 4)**: Depends on US1 being complete and green.

### User Story Dependencies

- **US1**: only user story in this feature.

### Within Phase 3

- T002 (test) MUST fail before T003-T005 land.
- T003, T004, T005 touch disjoint files; parallel-safe.
- T006 MUST pass before merging.

### Parallel Opportunities

- T003, T004, T005 are the classic parallel triple in this feature (one per implementation).
- T009 and T010 are both `CLAUDE.md` edits — same file, so NOT parallel with each other. They can run parallel to Phase 3 work IF the Phase 3 fixes are already in place (T009 documents what T003-T005 established).

---

## Parallel Example: User Story 1 (after T002 lands)

```bash
# Launch the three per-package fixes together:
Task: "Fix darnit-baseline: force-include + importlib.resources in packages/darnit-baseline/{pyproject.toml,src/darnit_baseline/implementation.py}"
Task: "Fix darnit-gittuf: force-include + importlib.resources in packages/darnit-gittuf/{pyproject.toml,src/darnit_gittuf/implementation.py}"
Task: "Fix darnit-reproducibility: force-include + importlib.resources in packages/darnit-reproducibility/{pyproject.toml,src/darnit_reproducibility/implementation.py}"
```

---

## Implementation Strategy

### MVP (this is the MVP)

The whole feature is one user story delivered as one PR. There is no incremental slicing beyond "one package at a time" if a reviewer wants smaller diffs, but since all three fixes are identical in shape and the integration test parameterizes over all three, keeping them in a single PR is the right unit.

1. T001: env sanity.
2. T002: write the failing integration test; confirm it fails against `main`.
3. T003 + T004 + T005 in parallel: apply the fix to all three packages.
4. T006: rerun the integration test; expect green.
5. T007 + T008: regression sweep (existing tests, editable install).
6. T009 + T010: docs note.
7. PR review, merge.

### Not applicable

- **Parallel team strategy**: this is small enough for one person; parallelism is between file edits within a single session, not between developers.

---

## Notes

- [P] tasks = different files, no dependencies.
- No AI sign-off in commit or PR body per the project's OpenSSF-adjacent policy.
- Preserve ASCII-only style in all edited files; existing `packages/darnit-baseline/pyproject.toml` uses ASCII exclusively (the `templates` entry above the new one is a good style anchor).
- Do NOT rename or move the TOML files on disk; the fix preserves the current repo layout.
- The `hatch.build.targets.wheel.force-include` section in `packages/darnit-baseline/pyproject.toml` already exists (for `templates`). Add to it; do not create a duplicate table.
- Feature 021 is the first of two BLOCKING prereqs identified in the pre-Stage-1 architecture review. The second prereq (`audit_results` typing in `packages/darnit/src/darnit/agent/state.py`) is a separate feature and NOT part of this task list.
