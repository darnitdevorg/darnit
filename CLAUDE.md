# Darnit Project Guidelines

This document provides architectural guidelines and development rules for the darnit project.

## Architecture Overview

Darnit is an AI-powered compliance auditing framework with a plugin architecture that separates the core framework from compliance implementations.

### Package Structure

```
packages/
├── darnit/                  # Core framework (MUST NOT import implementations)
│   └── src/darnit/
│       ├── core/            # Plugin system, discovery, logging
│       ├── sieve/           # 4-phase verification pipeline
│       ├── config/          # Configuration loading and merging
│       ├── tools/           # MCP tool implementations
│       └── server/          # MCP server setup
│
├── darnit-baseline/         # OpenSSF Baseline implementation
│   └── src/darnit_baseline/
│       ├── attestation/     # In-toto attestation support
│       ├── config/          # Project context configuration
│       ├── formatters/      # Output formatting (Markdown, JSON, SARIF)
│       ├── remediation/     # Remediation orchestration
│       ├── rules/           # SARIF rule definitions (from TOML)
│       └── threat_model/    # Threat model generation
│
└── darnit-testchecks/       # Test implementation (for testing)
```

## Separation Rules

### Rule 1: Framework MUST NOT Import Implementations

The `darnit` package must never directly import implementation packages.

```python
# ❌ WRONG - Creates hard dependency
import darnit_baseline
from darnit_baseline.controls import level1

# ✅ CORRECT - Use plugin discovery
from darnit.core.discovery import get_implementation
impl = get_implementation("openssf-baseline")
if impl:
    controls = impl.get_all_controls()
```

### Rule 2: Implementations MAY Import Framework

Implementation packages can freely import from the framework.

```python
# ✅ OK - Implementation importing framework
from darnit.core.plugin import ComplianceImplementation, ControlSpec
from darnit.sieve import register_control
```

### Rule 3: Use Protocol Methods for Cross-Package Communication

All framework-to-implementation communication must go through the `ComplianceImplementation` protocol.

```python
# Protocol methods available:
impl.name                        # str: Implementation identifier
impl.display_name                # str: Human-readable name
impl.version                     # str: Implementation version
impl.spec_version                # str: Spec version implemented
impl.get_all_controls()          # List[ControlSpec]: All controls
impl.get_controls_by_level(n)    # List[ControlSpec]: Controls at level n
impl.get_rules_catalog()         # Dict: SARIF rule definitions
impl.get_remediation_registry()  # Dict: Auto-fix mappings
impl.get_framework_config_path() # Path | None: TOML config location
impl.register_controls()         # None: Register TOML controls
```

## Plugin System

### Entry Points

Implementations register via Python entry points in `pyproject.toml`:

```toml
[project.entry-points."darnit.implementations"]
openssf-baseline = "darnit_baseline:register"
```

### Creating a New Implementation

1. Create a new package with the implementation class:

```python
# my_framework/implementation.py
from pathlib import Path
from darnit.core.plugin import ComplianceImplementation, ControlSpec

class MyFrameworkImplementation:
    @property
    def name(self) -> str:
        return "my-framework"

    @property
    def display_name(self) -> str:
        return "My Compliance Framework"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def spec_version(self) -> str:
        return "MySpec v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        # Return your control definitions
        ...

    def get_framework_config_path(self) -> Path | None:
        return Path(__file__).parent / "my-framework.toml"

    def register_controls(self) -> None:
        pass  # Controls are defined in TOML; no Python registration needed
```

2. Add the registration function:

```python
# my_framework/__init__.py
def register():
    from .implementation import MyFrameworkImplementation
    return MyFrameworkImplementation()
```

3. Register via entry point:

```toml
[project.entry-points."darnit.implementations"]
my-framework = "my_framework:register"
```

### Framework config resolution (feature 021)

`get_framework_config_path()` MUST use `importlib.resources.files(__package__) / "<framework>.toml"` -- never `Path(__file__).parent.parent...`. The framework TOML MUST live INSIDE `src/<module>/` (alongside `implementation.py`), not sibling to `src/`, so hatchling's default `packages = ["src/<module>"]` includes it in the wheel and `importlib.resources` finds it under both editable and wheel installs. See `packages/darnit-baseline`, `packages/darnit-gittuf`, `packages/darnit-reproducibility` for reference layouts; `packages/darnit-hello` is the minimal template.

## Sieve Pattern

The verification pipeline follows a 4-phase pattern using built-in handlers:

```
file_must_exist → exec/regex → llm_eval → manual
       ↓              ↓           ↓         ↓
  File presence   Commands &   AI-based   Human
  checks          patterns     eval       review
```

Each control can define passes at each phase. The orchestrator stops at the first conclusive result.

## Conservative-by-Default Principles

This is a compliance auditing tool. Incorrect results are worse than incomplete results. Every design decision must follow these rules:

### Never Assume Compliance

- A control that has not been **explicitly verified as passing** is NOT compliant. Period.
- "Needs Verification" / WARN means "we don't know" — treat it the same as FAIL for compliance calculations.
- Never report a level as "Compliant" if any control at that level is unverified, errored, or pending.
- It is always better to report a false negative (say something fails when it passes) than a false positive (say something passes when it doesn't).

### Never Guess User-Specific Values

- Do NOT auto-apply values like maintainers, security contacts, or governance models. These require explicit user confirmation.
- The TOML `auto_detect = false` flag marks a **user-judgment key**. Detection MAY run for such a key to *propose* a candidate, but MUST NOT *conclude* the value. Producing a candidate is not applying it.
- A candidate must never be consumed as the key's value by control verification results, compliance calculations, remediation inputs, generated attestations, or persisted project context. Until confirmed, the key is unverified, and unverified counts as FAIL.
- A candidate shown to a person must be labelled as unconfirmed and carry its origin (how it was produced). Origin is not confidence: a high-confidence guess is still a guess.
- Human confirmation is the only thing that makes a value usable. Writing a candidate to disk does not confirm it, and a stored candidate must still read as a candidate later.
- When a tool returns "Context Confirmation Required," that is a hard stop — ask the user. Do not fill in values from git history, repo owner, or any heuristic source.
- Two flags, two axes: `auto_detect` governs whether a value may be concluded without a person; `allow_sieve_hints` governs whether a detected value may be proposed. Both default to false. The safety property comes from the pair, not from banning detection.
- Confidence thresholds apply only to keys that do NOT require user judgment. No threshold, at any value, authorizes concluding a user-judgment key.

### Err on the Side of Caution

- When in doubt about a control's status, return WARN (needs verification), not PASS.
- When in doubt about a user's intent, ask. Do not proceed with assumptions.
- When designing prompts that an LLM will see, assume the LLM will blindly execute any suggested command. Never put guessed values or unconfirmed candidates in executable code snippets.

## Development Guidelines

### Adding New Controls

1. Define the control in `openssf-baseline.toml` with passes and metadata
2. Optionally add plugin Python handlers for complex logic
3. Run `uv run python scripts/validate_sync.py --verbose` to verify sync

### Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run only framework tests
uv run pytest tests/darnit/ -v

# Run only implementation tests
uv run pytest tests/darnit_baseline/ -v
```

### Linting

```bash
# Check for issues
uv run ruff check .

# Auto-fix issues
uv run ruff check --fix .

# Format code
uv run ruff format .
```

## Spec-Implementation Synchronization

The framework design is governed by the authoritative specification at:
`docs/architecture/framework-design.md`

### Sync Enforcement Rules

1. **TOML is Source of Truth**: Control metadata (descriptions, severity, help URLs) should be defined in `openssf-baseline.toml`, not in Python code.

2. **Spec Changes Require Validation**: When modifying framework behavior:
   - Update the spec first
   - Run `uv run python scripts/validate_sync.py --verbose`
   - Ensure handler names in code match `docs/architecture/framework-design.md`

3. **CI Enforces Sync**: PRs are blocked if:
   - TOML configs don't validate against framework schema
   - Handler names in code don't match those documented in `docs/architecture/framework-design.md`
   - The SARIF formatter references the catalog (it should read from TOML only)

### Validation Commands

```bash
# Validate spec-implementation sync (TOML schema, handler-name registry, SARIF source)
uv run python scripts/validate_sync.py --verbose
```

### TOML-First Architecture

All controls are defined in `openssf-baseline.toml`. The `rules/catalog.py` file
is a deprecated fallback that remains for backward compatibility but is not
actively used. All new controls must be defined entirely in TOML.

## TOML Schema Features

### CEL Expressions

Controls can use CEL (Common Expression Language) for pass logic:

```toml
[[controls."OSPS-AC-01.01".passes]]
handler = "exec"
command = ["gh", "api", "/orgs/{org}/settings"]
output_format = "json"
expr = 'output.json.two_factor_requirement_enabled == true'
```

Available context variables:
- `output.stdout`, `output.stderr`, `output.exit_code`, `output.json` (for exec)
- `response.status_code`, `response.body`, `response.headers` (for API)
- `files`, `matches` (for pattern pass)
- `project.*` (from .project/ context)

Custom functions: `file_exists(path)`, `json_path(obj, path)`

### Context System

The framework supports project context from `.project/project.yaml`:

```yaml
# .project/project.yaml
name: my-project
security:
  policy:
    type: SECURITY.md
governance:
  maintainers:
    - "@alice"
    - "@bob"
```

Context is injected into sieve orchestrator and available to CEL expressions.

### Handler Registration

Plugins register handlers using the `register_handlers()` method:

```python
class MyImplementation:
    def register_handlers(self) -> None:
        from darnit.core.handlers import get_handler_registry
        from . import tools

        registry = get_handler_registry()
        registry.set_plugin_context(self.name)

        registry.register_handler("my_tool", tools.my_tool)

        registry.set_plugin_context(None)
```

Handlers can then be referenced by short name in TOML:

```toml
[mcp.tools.my_tool]
handler = "my_tool"  # Short name instead of full module path
```

### Plugin Security

Plugins support Sigstore verification:

```toml
# .baseline.toml
[plugins]
allow_unsigned = false
trusted_publishers = ["https://github.com/kusari-oss"]
```

Default trusted publishers: `kusari-oss`, `kusaridev`

## Common Patterns

### Checking for Protocol Methods

Use `hasattr()` for backward compatibility when adding new protocol methods:

```python
impl = get_implementation("openssf-baseline")
if impl and hasattr(impl, "new_method"):
    impl.new_method()
```

### Graceful Degradation

Always handle missing implementations gracefully:

```python
impl = get_implementation("openssf-baseline")
if impl:
    result = impl.get_all_controls()
else:
    logger.warning("No implementation found")
    result = []
```

## Technology Stack
- **Language**: Python 3.11+ (targets 3.11/3.12)
- **Core deps**: FastMCP (via `mcp>=1.23,<2`), Pydantic >=2.0, PyYAML, cel-python, pydantic-ai-slim[anthropic] (required runtime dep as of RFC-0001 Stage 1 / feature 025)
- **Threat model**: tree-sitter, tree-sitter-language-pack (Python/JS/Go/YAML grammars)
- **Attestation**: sigstore, in-toto (optional)
- **Config**: TOML framework configs, `.project/project.yaml` (YAML), `.baseline.toml` (user overrides)
- **Storage**: Filesystem only (Markdown, JSON, YAML output files; no database)

## Active Technologies
- Python 3.11/3.12 (workspace targets) plus bash for release scripts and GitHub Actions YAML + `shiv` (binary builder), `cosign` (image + binary signing), `syft` (SBOM generation), `docker buildx` (multi-arch images), `gh` CLI (release creation), Sigstore-action (PyPI wheel signing via `pypa/gh-action-pypi-publish`). No new runtime dependencies in any darnit Python package. (012-packaging-distribution)
- External release surfaces only — PyPI, TestPyPI, GHCR, GitHub Releases (binary assets + attestations), `kusari-oss/homebrew-tap` repo (formula). Repo itself stores only build configs and workflow definitions. (012-packaging-distribution)
- Python 3.11/3.12 (workspace targets — same as the rest of darnit) + `pydantic >= 2.0` (already used for `FrameworkConfig`); `packaging` (already a transitive dep via setuptools metadata) for PEP 440 `SpecifierSet`. `tomllib` from stdlib for TOML parsing. No new runtime dependencies. (013-plugin-composition)
- Filesystem only. Composition is resolved in-memory at framework-config load time; no new persistent state. (013-plugin-composition)

## Recent Changes
- 028-audit-parity-tests: two-tier parity test suite verifying the darnit audit's per-control output is consistent across consumers. Tier 1 (`tests/darnit/parity/tier1/`) runs on every PR: parametrized-per-fixture pytest that invokes both the direct `audit_openssf_baseline` MCP tool AND `HarnessRun` (with `MockLLMStep`) in-process, then diffs per-control status. Sole allowed drift is PENDING_LLM (MCP) -> non-PENDING_LLM (harness). Tier 2 (`tests/darnit/parity/tier2/`) is manual-dispatch only via `.github/workflows/parity-tier2.yml` -- Environment-gated with required reviewers, no repo-level `ANTHROPIC_API_KEY` exposure. Uses `claude-agent-sdk` (test-only dev dep) to invoke the `/darnit-audit` skill, parses its final assistant message, diffs against the raw MCP tool JSON. Fixture corpus at `tests/darnit/parity/fixtures/`; `parity.toml` per fixture declares expected shape + `control_ids` filter. Zero product-package changes (SC-006), enforced by a git-diff-based test. Closes #366. Follow-up issues: #368 (OpenAI SDK parity), #369 (scheduled cadence + governance-appropriate key sourcing).
- 027-interactive-resolvers: adds `--interactive` flag to `darnit harness` and a new `QuestionResolver` Protocol (async, `@runtime_checkable`) that sits downstream of feature 026's `AnswerSource` chain. `InteractiveTerminalResolver` reference implementation prompts on `/dev/tty` (isolated from stdout report / stderr progress streams). Third-party resolvers register via Python entry points under group `darnit.question_resolvers` (mirrors `darnit.frameworks` discovery). Every `Answer` carries `authority: "asserted"` enforced at the model layer via `Literal["asserted"]` with a fixed default. Per-question `resolution_trail` in the report captures which resolvers were offered a question and how each responded (`answered`/`skipped`/`errored`). Fail-fast (<2s) when stdin is not a TTY OR /dev/tty is not openable under `--interactive`. Feature 026's "no re-audit after collect" MVP policy preserved.
- 026-darnit-harness: adds `darnit harness` subcommand -- end-to-end audit driver with in-band LLM dispatch (fleet-operator + CI-integrated persona). Consumes `ANTHROPIC_API_KEY` from env; dispatches PENDING_LLM results via `PydanticAILLMStep`. Non-interactive by default; batch answers via pluggable `AnswerSource` Protocol with auto-discovery of `.project/project.yaml` + `--answers` override. Markdown + JSON reports. Four documented exit codes (0/1/2/3) plus grep-able stderr summary. New `darnit.harness` subpackage (`driver`, `answer_sources`, `report`, `exit_codes`).
- 025-rfc0001-stage1: RFC-0001 Stage 1. Adds `authority` (`dispositive`|`suggestive`|`asserted`) to every step + result; per-phase Check execution rule ensures only dispositive/asserted results conclude a control (LLM output alone cannot manufacture a PASS). New `darnit.core.action_plan` module exposes `next_action`/`submit_result` as a public typed protocol; `agent.graph.route()` becomes a thin adapter. MCP surface adds `run_next_action`/`submit_action_result` tools (client-owned state). Baseline attestation predicate gains a per-result `authority` field additively within v1. `pydantic-ai-slim[anthropic]` becomes a required runtime dep.
- 024-cmd-run-e2e-tests: E2E baseline for `darnit run` pinning header/footer/count/exit-code contract; used as the mechanical regression guarantee for Stage 1's `cmd_run` code path.
- 021-fix-config-path: framework TOMLs (openssf-baseline.toml, gittuf.toml, reproducibility.toml) moved into `src/<module>/`; `get_framework_config_path()` uses `importlib.resources`. Wheel installs now find the TOML; editable installs unchanged.
- 012-packaging-distribution: Added Python 3.11/3.12 (workspace targets) plus bash for release scripts and GitHub Actions YAML + `shiv` (binary builder), `cosign` (image + binary signing), `syft` (SBOM generation), `docker buildx` (multi-arch images), `gh` CLI (release creation), Sigstore-action (PyPI wheel signing via `pypa/gh-action-pypi-publish`). No new runtime dependencies in any darnit Python package.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
[`specs/028-audit-parity-tests/plan.md`](specs/028-audit-parity-tests/plan.md)
<!-- SPECKIT END -->
