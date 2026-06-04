# Packaging a third-party darnit plugin

This guide is for teams who want to ship their own compliance framework on top of darnit — your org's internal policy, a regulator's framework, a CIS benchmark, a SLSA-style supply-chain checklist, anything that can be expressed as a set of controls with pass logic.

> **Worked example**: every code block below has a working twin at [`packages/darnit-hello/`](../packages/darnit-hello/). Copy that whole directory if you'd rather start from a known-good baseline than build piece-by-piece.

## What you'll build

A Python package that:

1. Declares an entry point on the `darnit.implementations` group.
2. Exposes a `register()` callable that returns an instance of a class conforming to the `darnit.core.plugin.ComplianceImplementation` protocol.
3. Ships a `<name>.toml` config file that defines the controls themselves (TOML-First Architecture — see the project constitution).
4. Optionally publishes to PyPI (or a private index, or a git URL) so users can `pip install <your-plugin>` and have darnit auto-discover it.

That's it. There's no plugin manifest beyond `pyproject.toml`, no service to register with, no callback to wire up. The framework's discovery layer walks Python entry points at startup.

---

## Layout

```
your-plugin/
├── pyproject.toml                       # Package metadata + entry point
├── README.md                            # User-facing docs
└── src/your_plugin/
    ├── __init__.py                      # register() + get_framework_path()
    ├── implementation.py                # YourImplementation class
    └── your_framework.toml              # Source of truth for controls
```

> **Important**: place the TOML config **inside** the Python package directory (`src/your_plugin/your_framework.toml`), not at the package root. Hatchling auto-includes everything inside the package source in the wheel, so the file ships with `pip install` automatically. Putting the TOML at the package root (next to `pyproject.toml`) and using `[tool.hatch.build.targets.wheel.force-include]` to copy it is fragile — easy to miss, easy to misconfigure. Co-locating it with the Python files also lets `get_framework_path()` use a simple `Path(__file__).parent / "your_framework.toml"` instead of climbing up the directory tree.

---

## Step 1 — `pyproject.toml`

The two entry-point blocks are the only darnit-specific bits. Everything else is standard Python packaging metadata.

```toml
[project]
name = "darnit-your-framework"
version = "0.1.0"
description = "Brief description of what your framework checks"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "darnit>=0.1.0",
]

# The framework discovers your plugin via these entry points.
[project.entry-points."darnit.implementations"]
your-framework = "your_plugin:register"            # slug = module:callable

[project.entry-points."darnit.frameworks"]
your-framework = "your_plugin:get_framework_path"  # optional, for TOML discovery

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/your_plugin"]

# Note: because your_framework.toml lives INSIDE src/your_plugin/, hatchling
# bundles it automatically — no [tool.hatch.build.targets.wheel.force-include]
# block needed.
```

**Important**: the slug on the left side of `darnit.implementations` (`your-framework`) is what `darnit list-controls --implementation <slug>` and similar tools key off. Pick something stable and human-readable.

---

## Step 2 — `__init__.py`

Two callables. `register()` is required; `get_framework_path()` is optional but recommended.

```python
"""your-framework — plugin for darnit."""

from pathlib import Path

from .implementation import YourImplementation


def register() -> YourImplementation:
    """Entry point called by darnit plugin discovery.

    Return an INSTANCE (not the class) of your implementation.
    """
    return YourImplementation()


def get_framework_path() -> Path:
    """Entry point for framework TOML config discovery."""
    return Path(__file__).parent / "your_framework.toml"
```

---

## Step 3 — `implementation.py`

The class needs to satisfy the [`ComplianceImplementation` protocol](../packages/darnit/src/darnit/core/plugin.py). For a TOML-only plugin (no Python-defined controls), most methods are stubs.

```python
from __future__ import annotations
from pathlib import Path
from typing import Any


class YourImplementation:
    @property
    def name(self) -> str:
        return "your-framework"

    @property
    def display_name(self) -> str:
        return "Your Framework — Human-Readable Name"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "Your Spec v1.0"  # e.g., "OSPS v2025.10.10"

    def get_framework_config_path(self) -> Path | None:
        return Path(__file__).parent / "your_framework.toml"

    def register_controls(self) -> None:
        # No-op for TOML-only plugins. If you write Python control handlers,
        # import them here to trigger registration.
        return None

    def get_all_controls(self) -> list[Any]:
        # TOML-defined controls are loaded by the framework via the TOML path.
        return []

    def get_controls_by_level(self, level: int) -> list[Any]:
        return []

    def get_rules_catalog(self) -> dict[str, Any]:
        # The framework derives SARIF rules from TOML automatically.
        return {}

    def get_remediation_registry(self) -> dict[str, Any]:
        return {}
```

The protocol is `@runtime_checkable`, so you can self-test:

```python
from darnit.core.plugin import ComplianceImplementation
assert isinstance(YourImplementation(), ComplianceImplementation)
```

---

## Step 4 — `your_framework.toml`

This is where the work happens. Each control declares its identity, its pass logic (the 4-phase sieve pipeline), and optionally its remediation.

```toml
[framework]
name = "your-framework"
display_name = "Your Framework — Human-Readable Name"
version = "0.1.0"
spec_version = "Your Spec v1.0"
description = "What this framework checks for."

# Optional MCP integration. Each [mcp.tools.<name>] block creates an MCP
# tool the calling agent can invoke. `builtin = "audit"` aliases the
# framework-provided audit tool for your plugin's namespace.
[mcp]
name = "your-framework"
description = "Run your-framework's compliance checks."

[mcp.tools.audit_your_framework]
builtin = "audit"
description = "Run your-framework's compliance audit."

# A control. The ID is any string; convention is <DOMAIN>-<NN>.<NN>.
[controls."YF-01.01"]
name = "ReadmeExists"
description = "Repository must have a top-level README."
tags = { level = 1, domain = "YF" }

# Pass logic. Each [[controls.X.passes]] entry is one phase of the sieve.
# The framework tries them in order; the first conclusive result wins.
# Built-in handlers: file_must_exist, exec, pattern, manual. Plugin handlers
# can be registered in implementation.py via register_handlers().
[[controls."YF-01.01".passes]]
handler = "file_must_exist"
paths = ["README.md", "README.rst", "README"]
description = "A README file exists at the repo root."

# Manual fallback — surfaces steps for a reviewer, never auto-passes.
[[controls."YF-01.01".passes]]
handler = "manual"
steps = [
    "Confirm a README file exists at the repository root.",
    "If missing, create one summarising the project.",
]

# Optional remediation. `safe = true` lets darnit auto-apply without
# prompting; `dry_run_supported = true` enables preview mode.
[controls."YF-01.01".remediation]
safe = true
dry_run_supported = true

[[controls."YF-01.01".remediation.handlers]]
handler = "file_create"
path = "README.md"
content = "# My Project\n\n(Auto-created stub. Replace with real content.)\n"
description = "Create a minimal README stub."
```

### Sieve handlers reference

| Handler | What it does | Required fields |
|---|---|---|
| `file_must_exist` | PASS if any listed path exists; FAIL otherwise | `paths: list[str]` |
| `exec` | Run a command; PASS/FAIL by exit code (or CEL expression) | `command: list[str]`, `pass_exit_codes`, optional `expr` |
| `pattern` | Grep one or more files for a regex | `paths`, `pattern`, optional `must_match` |
| `manual` | Human review required; never auto-PASSES | `steps: list[str]` |

Built-in remediation handlers: `file_create`, `exec`, `api_call`, `project_update`, `yaml_inject`. Custom Python handlers can be registered via `register_handlers()` — see [`packages/darnit-baseline/`](../packages/darnit-baseline/) for examples.

### CEL expressions

Both `exec` and `api_call` passes can use [CEL](https://github.com/google/cel-spec) for richer pass logic:

```toml
[[controls."YF-02.01".passes]]
handler = "exec"
command = ["gh", "api", "/repos/{owner}/{repo}"]
output_format = "json"
expr = 'output.json.private == false && output.json.archived == false'
```

CEL syntax is C/Java-style (`&&`, `||`, `!`, NOT Python's `and`/`or`/`not`). Backslashes in TOML literal strings are literal: `\\.` matches a literal dot, not `\\\\.` (over-escaping is a common gotcha).

---

## Step 5 — install and test locally

```bash
# Editable install
pip install -e .

# Confirm darnit discovers your plugin
darnit list-controls --implementation your-framework
# → YF-01.01 ReadmeExists ...

# Run the audit against a sample repo
darnit audit --implementation your-framework /path/to/sample/repo
```

For a programmatic smoke test:

```python
from importlib.metadata import entry_points

eps = [ep for ep in entry_points(group="darnit.implementations") if ep.name == "your-framework"]
assert len(eps) == 1, f"Expected exactly one 'your-framework' implementation, got {len(eps)}"

impl = eps[0].load()()  # call register()
assert impl.name == "your-framework"
assert impl.get_framework_config_path().exists()
```

---

## Step 6 — publish

### To PyPI (public)

The Trusted Publishing + Sigstore signing recipe in [`docs/install/pypi.md`](install/pypi.md) applies one-to-one. Configure Trusted Publishing for your project on `pypi.org/manage/account/publishing/`, then run a release workflow that calls `pypa/gh-action-pypi-publish` with `attestations: true`. Same chain of trust darnit's own packages use.

### To a private index

Standard Python packaging — `twine upload --repository <name>` or your platform's equivalent. Tell users to add the index in their `pip` config; darnit doesn't care where the package came from, only that the entry point resolves.

### Via git (no index)

```bash
pip install git+https://github.com/your-org/darnit-your-framework@v0.1.0
```

This works but bypasses the signing chain. Fine for development; not recommended for production deployment.

---

## Signing and the `[plugins]` trust config

darnit's plugin discovery has an optional verification step backed by Sigstore. By default it allows unsigned plugins (for backward compatibility), but production deployments can flip the switch.

Configure trust in your project's `.baseline.toml`:

```toml
[plugins]
allow_unsigned = false
trusted_publishers = [
    "https://github.com/your-org",
    "https://github.com/kusari-oss",
]
```

If your plugin is published to PyPI with Sigstore attestations enabled (the default for new projects since 2024), the signing identity will be a GitHub OIDC URL like `https://github.com/your-org/your-repo/.github/workflows/release.yml@refs/tags/v0.1.0`. The default trusted publishers list (`kusari-oss`, `kusaridev`) covers darnit's own plugins; add your org's URL prefix to extend the list.

For the full verification API, see [`packages/darnit/src/darnit/core/verification.py`](../packages/darnit/src/darnit/core/verification.py).

---

## Testing

The darnit test scaffolding in [`packages/darnit-testchecks/`](../packages/darnit-testchecks/) demonstrates the patterns. The two most useful for a third-party plugin:

1. **Smoke discovery test** — `pip install -e .` your plugin in CI, then assert the entry point resolves and `register()` returns a protocol-conforming instance.
2. **End-to-end audit test** — fixture a small repo (a real one if you want, or a `tmp_path` skeleton), run `darnit audit --implementation your-framework`, assert specific controls produce the expected status.

---

## The three-layer architecture

When your plugin grows beyond TOML-only checks, you may want to add Python handlers. darnit follows a three-layer architecture; understand which layer your custom code lives in before reaching for an abstraction.

| Layer | What it does | Built-in handlers | Plugin extension |
|---|---|---|---|
| **1. Checking** (sieve passes) | Determines if a control passes/fails | `file_must_exist`, `exec`, `pattern`, `manual` | Register Python functions via `register_handlers()` |
| **2. Remediation** | Auto-fixes failing controls | `file_create`, `exec`, `api_call`, `project_update`, `yaml_inject` | Register Python functions for complex remediation |
| **3. MCP tools** | Exposes functionality to calling agents | `audit`, `remediate`, `list_controls` | Register custom Python handlers via `register_handlers()` |

"Built-in" means different things at each layer. Don't conflate them.

See `CLAUDE.md` "Three-Layer Architecture" for the canonical reference.

---

## Common gotchas

- **`register()` must return an INSTANCE**, not the class. `return YourImplementation()`, not `return YourImplementation`.
- **TOML control IDs must be unique within your plugin** (the framework deduplicates by ID, with TOML overriding Python registrations).
- **CEL backslashes in TOML literal strings are literal.** Use `'\.'` to match a literal dot in a CEL regex, NOT `'\\.'` (the latter produces `\\` + `.` in CEL, which matches "backslash + any char").
- **The framework imports your `register()` lazily** — don't do heavy work at module import time. If you need expensive setup, do it inside `register()` or lazily inside the methods that need it.
- **The plugin slug (entry-point key) and the `name` property in your implementation must match** — both should equal your framework's slug. If they diverge, some framework tools will see one and some will see the other.

---

## Reference plugins in this repo

| Plugin | Purpose | Read it for |
|---|---|---|
| [`packages/darnit-hello/`](../packages/darnit-hello/) | Single-control toy plugin | The minimum viable shape — copy this to bootstrap |
| [`packages/darnit-baseline/`](../packages/darnit-baseline/) | OpenSSF Baseline (production) | TOML+Python handlers, multi-level scoring, custom MCP tools, remediation suite |
| [`packages/darnit-gittuf/`](../packages/darnit-gittuf/) | Gittuf policy checks | Compact real-world plugin (3 controls), Python handlers |
| [`packages/darnit-example/`](../packages/darnit-example/) | Example/teaching framework | Custom controls, custom tools, remediation patterns |

---

## Composition vs forking

If your goal is "OpenSSF Baseline + a few of our own controls + an override or two" rather than a wholly new compliance standard, **don't build a plugin from scratch — compose one in TOML**. A composite implementation declares which controls it pulls from already-installed sources (levels, named IDs, or tag-based slices), adds inline controls of its own, and optionally overrides specific fields without forking. The framework resolves all of that at registration time and the rest of the framework sees a normal flat control set.

- [Composition quickstart](../specs/013-plugin-composition/quickstart.md) — the canonical end-to-end walkthrough
- [Composition spec](../specs/013-plugin-composition/spec.md) — full requirements (FR-001..FR-018, user stories, edge cases)
- [TOML schema contract](../specs/013-plugin-composition/contracts/toml-schema.md) — `[[compose]]`, `[overrides."ID"]`, `allow_conflicts`, field-by-field semantics
- [Implementation Guide §12](IMPLEMENTATION_GUIDE.md#12-composition-assembling-implementations-from-other-implementations) — when-to-compose-vs-fork, conflict-resolution escape hatches, provenance contract

Composition keeps you upgrade-current on upstream changes (their pass logic and remediation flow through automatically); a fork takes upstream code captive. Reach for a fork only if you need to fundamentally re-author pass logic or maintain semantically divergent behavior.

---

## See also

- [Project constitution](../.specify/memory/constitution.md) — TOML-First Architecture, Plugin Separation rules
- [`CLAUDE.md`](../CLAUDE.md) — project-wide development guidelines
- [`docs/install/pypi.md`](install/pypi.md) — Trusted Publishing + Sigstore signing setup
- [Agent Skills standard](https://agentskills.io) — the open standard for skills (separate from darnit plugins, but related when packaging skills that interact with darnit)
