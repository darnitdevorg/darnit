# Quickstart: Composing your own compliance implementation

**Feature**: 013-plugin-composition · **Audience**: composite-implementation authors · **Date**: 2026-05-13

This walks through the canonical Story 1 scenario from the spec: building an `acme-baseline` implementation that pulls slices from `openssf-baseline` and `darnit-gittuf`, adds an internal control inline, overrides one inherited control's remediation, and registers like any other implementation. No Python composition code needed.

## Prerequisites

- darnit installed in your environment (any of the v0.1.0+ distribution channels — PyPI, container, binary).
- The source implementations you want to compose are installed alongside (`darnit-baseline`, `darnit-gittuf` in this example).
- You can already author a non-composite implementation. (If you can't, work through the `darnit-hello` template first — composition is purely additive on top of it.)

## Step 1 — Create the package skeleton

```text
acme-baseline/
├── pyproject.toml
├── README.md
└── src/
    └── acme_baseline/
        ├── __init__.py
        ├── implementation.py
        └── acme-baseline.toml
```

`pyproject.toml` (key fragment):

```toml
[project]
name = "acme-baseline"
version = "1.0.0"

[project.entry-points."darnit.implementations"]
acme-baseline = "acme_baseline:register"
```

`src/acme_baseline/__init__.py`:

```python
def register():
    from .implementation import AcmeBaselineImplementation
    return AcmeBaselineImplementation()
```

`src/acme_baseline/implementation.py` — note this is the **same `ComplianceImplementation` stub** any non-composite uses. No composition awareness needed.

```python
from pathlib import Path
from darnit.core.plugin import ComplianceImplementation, ControlSpec

class AcmeBaselineImplementation:
    @property
    def name(self) -> str: return "acme-baseline"
    @property
    def display_name(self) -> str: return "Acme Baseline"
    @property
    def version(self) -> str: return "1.0.0"
    @property
    def spec_version(self) -> str: return "Acme v1"

    def get_framework_config_path(self) -> Path:
        return Path(__file__).parent / "acme-baseline.toml"

    def get_all_controls(self) -> list[ControlSpec]:
        # Standard pattern: load via the framework loader and return controls.
        # Composition resolution happens transparently inside load_framework_config.
        from darnit.config.merger import load_framework_config
        cfg = load_framework_config(self.get_framework_config_path())
        return [ControlSpec(...) for cid, c in cfg.controls.items()]

    def register_controls(self) -> None:
        pass  # TOML-only; nothing to register in Python.
```

## Step 2 — Author the composite TOML

`src/acme_baseline/acme-baseline.toml`:

```toml
[metadata]
name = "acme-baseline"
display_name = "Acme Baseline"
version = "1.0.0"
spec_version = "Acme v1"

# Strict-by-default conflict resolution. Leave at default unless you need
# the last-wins escape hatch.
# allow_conflicts = false

# Pull OpenSSF Baseline levels 1 and 2, but drop a control Acme doesn't
# care about. Pin to the 1.x line so an upstream major bump fails loudly.
[[compose]]
source = "openssf-baseline"
include_levels = [1, 2]
exclude_controls = ["OSPS-AC-02.01"]
version_constraint = ">=1.0,<2.0"

# Pull every gittuf control, default-floating on the source's version.
[[compose]]
source = "darnit-gittuf"
include_all = true

# Cherry-pick three specific level-3 OSPS controls.
[[compose]]
source = "openssf-baseline"
include_controls = [
    "OSPS-AC-03.01",
    "OSPS-VM-03.01",
    "OSPS-QA-07.01",
]
version_constraint = ">=1.0,<2.0"

# An inline control of Acme's own. Exactly the same shape as in any non-
# composite implementation.
[controls."ACME-DEPLOY-01.01"]
name = "DeployWindowEnforced"
level = 1
domain = "AC"
description = "Production deploys happen only during the published window."

[[controls."ACME-DEPLOY-01.01".passes]]
handler = "exec"
command = ["gh", "api", "/repos/{owner}/{repo}/actions/variables/DEPLOY_WINDOW"]
output_format = "json"
expr = 'output.json.value != ""'

# Override the remediation on an inherited control to point at Acme's
# internal SSO console, without touching its pass logic.
[overrides."OSPS-AC-01.01"]
remediation = """
1. Open https://sso.acme.example/admin → Policies → Authentication.
2. Set "Require multi-factor for all sign-ins" → ON.
3. Save and refresh the user audit log to confirm enforcement is active.
"""
```

## Step 3 — Install and verify

```bash
# In the acme-baseline package directory:
uv pip install -e .

# Confirm the framework loads. The composition resolver runs at load time;
# any of the error classes from contracts/resolver-api.md surface here.
darnit validate src/acme_baseline/acme-baseline.toml

# List the resolved control set — should be:
#   openssf-baseline L1+L2 (minus OSPS-AC-02.01) +
#   all darnit-gittuf controls +
#   3 OSPS L3 controls +
#   1 inline ACME control
darnit list-controls --implementation acme-baseline

# Run an audit. The output shape is identical to a non-composite audit.
darnit audit --implementation acme-baseline /path/to/repo
```

## Step 4 — Sanity-check provenance

Every control in the resolved set carries two framework-stamped tags:

```bash
darnit list-controls --implementation acme-baseline --output json \
  | jq '.controls[0].tags | {_composed_from, _original_control_id}'

# Example output for a control inherited from openssf-baseline:
# {
#   "_composed_from": "openssf-baseline",
#   "_original_control_id": "OSPS-AC-03.01"
# }

# Example output for the inline ACME control:
# {
#   "_composed_from": "acme-baseline",
#   "_original_control_id": "ACME-DEPLOY-01.01"
# }
```

These tags are how audit reviewers trace any finding back to its source implementation.

## Common errors

**`CompositionMissingSourceError`** — A `[[compose]]` block names a source not installed on the host. Install the source package (e.g., `uv pip install darnit-baseline`) and retry.

**`CompositionConflictError`** — Two `[[compose]]` blocks contributed the same control ID. The error lists both source slugs and the conflicting ID. Resolve by either:
- Adding `allow_conflicts = true` at the top level (later compose block wins; INFO log emitted), OR
- Adding `[overrides."<ID>"]` to pin the conflict resolution explicitly (always wins, even in strict mode).

**`CompositionOrphanOverrideError`** — An `[overrides."ID"]` block targets a control ID not present in the resolved set (maybe a typo, maybe the source was filtered out). Either remove the override or adjust the compose block to include the ID.

**`CompositionUnknownFieldError`** — An override names a field not on `ControlConfig`. Check the field name; v1 supports `passes`, `remediation`, `security_severity`, `description`, `docs_url`, and `tags`. (The override-able names match the real schema — `severity` and `help_url` are rejected. There are no friendly aliases in v1.)

**`CompositionCycleError`** — A composition graph has a cycle. The error names the chain (`acme-baseline → other-composite → acme-baseline`). Composites cannot transitively include themselves.

**`CompositionVersionMismatchError`** — A `[[compose]]` block's `version_constraint` is not satisfied by the installed source's version. Either install a compatible source version or relax the constraint.

## When to use composition vs. forking

- **Use composition** when your posture is "the upstream framework + a few named slices and overrides." Composition keeps you upgrade-current on the source's pass logic and remediation.
- **Use a fork** only if you need to fundamentally re-author a source's pass logic, restructure its control IDs, or maintain divergent semantics. Forking is heavyweight; composition is the additive default.

## Performance budget

Resolution runs once at framework-config load time (effectively once per process). The target (SC-002) is **<200 ms for 50 composed + 5 inline controls** on a developer laptop. Larger composites still resolve in linear time relative to unique source count thanks to memoization. If you observe surprisingly long load times, file an issue with your composite's TOML and the resolution time — the resolver should not be a noticeable cost.
