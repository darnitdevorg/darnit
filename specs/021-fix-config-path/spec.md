# Feature Specification: Framework config loading works under wheel install

**Feature Branch**: `021-fix-config-path`

**Created**: 2026-08-04

**Status**: Draft

**Input**: User description: "config path fix"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - darnit works after `uv tool install` / wheel install (Priority: P1)

An operator installs darnit the way we tell them to in the packaging docs (`uv tool install darnit-baseline` or `pip install darnit-baseline`), then runs `darnit audit` or invokes the MCP server through a skill. Today, this fails because each implementation package resolves its framework TOML via `Path(__file__).parent.parent.parent`, which only works in an editable checkout. In a wheel install, either the TOML file is missing from the wheel or the relative path lands outside the site-packages layout.

**Why this priority**: This is the shipping story. Every install path other than `uv sync` from a git checkout produces a broken tool. The Stage 1 harness driver (RFC-0001) depends on framework config loading working correctly at runtime, regardless of how the package was installed. Until this is fixed, the audited product is not the product users install.

**Independent Test**: Build the wheel for `darnit-baseline` (`uv build --package darnit-baseline`), install it into a fresh virtualenv (`pip install dist/*.whl` or `uv tool install`), run `darnit list`. The command MUST exit 0 and print the framework name with a control count, with no "error loading" or `FileNotFoundError` text in stdout/stderr. Repeat for `darnit-gittuf` and `darnit-reproducibility`.

**Acceptance Scenarios**:

1. **Given** a fresh Python environment with `darnit-baseline` installed from its built wheel, **When** the operator runs any darnit command that loads the framework config (`darnit list`, `darnit audit`, `darnit serve`), **Then** the command loads the TOML successfully and does not raise a file-not-found error.
2. **Given** the same fresh environment, **When** the operator invokes an MCP tool through a skill that triggers framework config loading, **Then** the tool call returns a normal result (no "config not found" surfaced to the caller).
3. **Given** a developer working in an editable checkout (`uv sync` from repo root), **When** they run any darnit command, **Then** the framework config loads exactly as it does today (regression guard).
4. **Given** the wheel for `darnit-gittuf` or `darnit-reproducibility` installed into a fresh environment, **When** darnit resolves the framework config for that implementation, **Then** the TOML loads successfully (same behavior as darnit-baseline).

---

### Edge Cases

- What if the wheel is installed into a zipimport-style zipped location (rare for Python packages, but possible)? The mechanism MUST be resilient to non-filesystem package storage.
- What if the operator installs multiple implementation packages into the same environment? Each implementation MUST resolve ITS OWN framework TOML, not accidentally pick up a sibling's file.
- What if the operator installs an implementation from a non-`uv`, non-`pip` mechanism (system package, container image, `shiv` binary)? The mechanism MUST work as long as the wheel was built by the project's own build tooling.
- What if the framework TOML file is missing from an implementation package's wheel entirely (a build-tool misconfiguration)? The operator MUST see a clear, actionable error at load time, not a generic `FileNotFoundError` from deep in the loader.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When any implementation package is installed from its built wheel into a Python environment, calling `get_framework_config_path()` on the implementation MUST resolve to a readable path (or file-like resource) containing that implementation's framework TOML.
- **FR-002**: The build process for each implementation package (`darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility`) MUST include the framework TOML file inside the built wheel. A wheel produced by the project's build tooling and installed into a fresh environment MUST contain the TOML.
- **FR-003**: The three implementation packages MUST use the same resolution mechanism. Divergence between implementations is a maintainability risk and MUST be avoided.
- **FR-004**: Editable installs (`uv sync` from a git checkout) MUST continue to work without change. No developer workflow regresses.
- **FR-005**: When the TOML file is absent from the installed package (a broken build), the framework MUST surface a clear error identifying which implementation is missing its config, not a generic path or attribute error.
- **FR-006**: The fix MUST NOT introduce any new runtime dependencies. The mechanism should use Python standard library features available in the project's supported Python versions (3.11+).

### Key Entities

- **`get_framework_config_path()`** (protocol method on `ComplianceImplementation`, `packages/darnit/src/darnit/core/plugin.py`): the contract by which the framework asks an implementation "where is your TOML?". The return type today is `Path | None`. The mechanism change may extend the acceptable return shape (e.g., accept a `Path` OR a `Traversable`) but MUST preserve the semantics for callers.
- **Framework TOML files**: `openssf-baseline.toml`, `gittuf.toml`, `reproducibility.toml`. Each lives at the root of its implementation package today.
- **Wheel build configuration** (`pyproject.toml` in each implementation package): the build-tool configuration that determines what ends up in the built wheel. Today it packages `src/<module>/` but not the sibling TOML.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fresh `uv tool install darnit-baseline` (or the equivalent `pip install` into a fresh venv) followed by `darnit list` prints the framework name with a control count and no "error loading" text in stdout or stderr. Same for `darnit-gittuf` and `darnit-reproducibility`.
- **SC-002**: The full test suite (`uv run pytest tests/ -v`) continues to pass with the fix in place. No editable-install workflow regresses.
- **SC-003**: An integration test asserts that a wheel-installed implementation package can load its framework TOML. This test would have caught the current bug and MUST be part of the fix. It runs in CI on every PR.
- **SC-004**: The RFC-0001 Stage 1 harness driver (upcoming work) can rely on `get_framework_config_path()` returning a valid path regardless of install mode, without special-casing the wheel scenario.

## Assumptions

- Constitutional reference: this strengthens Principle I (Configurability: framework config is the source of truth) by making that source of truth reachable from every supported install path.
- The fix is packaging + a small code change in each implementation's `get_framework_config_path()`. No changes to the framework's core loader (`darnit/config/merger.py`) should be needed; the loader just needs a working path.
- The build tool for each implementation package (currently `hatchling`) supports declaring extra files to include in the wheel. If a build-tool-level mechanism is not sufficient, the packaging metadata for each implementation may need adjustment.
- `importlib.resources` (stdlib, Python 3.9+) is the standard way to locate package-adjacent data files in installed Python packages and works for both filesystem and zipped installs. This is a strong candidate for the resolution mechanism but is technically an implementation detail; the spec does not mandate it.
- All three implementations follow the same repo layout convention (`packages/<name>/<framework>.toml` at the package root, alongside `pyproject.toml`). The fix will preserve this convention on disk.
- Existing tests do not exercise the wheel install path today. Adding coverage for this is a required part of the fix, not an optional follow-up.
- Downstream plugin authors (not part of this repo's package set) will need to migrate their own `get_framework_config_path()` implementations to whatever mechanism this fix adopts. The fix should include a short docs note explaining the new pattern for plugin authors.
