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

A result concludes only if its outcome is in the step's effective set (feature 041): each step type has a ceiling (`file_exists`/`regex` FAIL only unless `existence = true`; `exec`/`gh_api` PASS or FAIL; `llm_eval`/`manual` nothing), narrowed by `concludes` and widened only by a corpus-backed `promotion`. Other outcomes are evidence and evaluation continues; no conclusion is WARN. ERROR (with `error.class`/`cause`) is a broken measurement, never FAIL. A positive model judgment is at most a PASS candidate (`PENDING`, `pending.kind = "confirmation"`), non-compliant until the operator confirms it; confirmed, it is PASS with `authority: asserted`. See `docs/architecture/framework-design.md` sections 3.0.1-3.0.2, 3.5, 5.2.

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
- A damaging change is worse than no change. Remediation never weakens a platform setting, never writes over a user's uncommitted changes, never commits files it did not write, and reports `fixed` only when a re-check passes.

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

Context values are read only through `resolve_context` (`darnit.config.context_resolve`), which gives each key a standing: `confirmed` (a confirmation record matches the value), `concluded` (an `auto_detect = true` key detected this run; never persisted), `candidate`, or `unknown`. Consumers read only `usable()` (confirmed plus concluded); a stored value without a matching record is a candidate. Reads never write. `darnit.config.context_writes` is the only writer: a person's confirmation (`confirm_project_data`, or `darnit run` answers) records who, when, basis, `last_validated`, and optional `expires_at`, in `.project/darnit.yaml` for a trusted repository, else operator-side; `.project/project.yaml` is never written with context values. A remediation template that reads an unusable key stops with `confirmation required: <key>` (feature 042; framework-design.md 7.4-7.11).

Project claims live in `.project/darnit.yaml` (`controls.<id>: {status, reason, asserted_by}`). A not-applicable claim, explicit or implied by a `.project/` context value, counts only when its outcome is `honored` (trusted repository and uncontradicted, or operator-confirmed); `pending` counts as non-compliant and `contradicted` has no effect (feature 040).

Tool configuration comes only from operator configuration (`--operator-config PATH`, else `$XDG_CONFIG_HOME/darnit/config.toml` / `~/.config/darnit/config.toml`, else built-in defaults), never from the audited repository. It holds plugins, MCP servers, pass overrides, custom controls, stores, LLM settings, `[trust].repos`, CI trust rules, and policy. `darnit config show|trust|migrate` inspect it, edit the trust list, and move a deprecated `.baseline.toml` (during the deprecation release only per-control `status`/`reason`, read as claims, and `extends` by registered name are honored, with a warning per setting; switch `BASELINE_TOML_DEPRECATION_ACTIVE` in `config/merger.py`).

Remediation plans, then applies only what it planned (feature 043; framework-design.md 4, 15). Handlers get `HandlerContext.mode` (`plan`/`apply`), return `FileChange`s in `evidence["file_changes"]`, and never write; the executor is the single writer, skips files with uncommitted user changes (`user_changes_present`, in the preview too), and records every write in an operator-side run manifest. A handler without `supports_plan=True` is not previewable. Platform settings change only through `platform_setting` and the platform engine (also behind `enable_branch_protection`): it reads first (unreadable means no write), plans the minimal change, never weakens an existing setting, writes nothing when already satisfied or met by a ruleset, uses the default branch, and reads back. `api_call`, `requires_confirmation`, `dry_run_supported`, and `dry_run_command` are removed; an exec remediation never touches the platform. The `[remediation]` policy (`platform`, `high_impact`: `prompt` default, `manual`, `auto`) comes from operator configuration only. Approval is by digest (`approve`), bound to the observed state; `dry_run=False` alone approves nothing, a batch never covers a high-impact change, and `safe = false` or non-previewable items need their own digest under every policy. Git tools take `run_id`, commit only manifest files with a `Darnit-Remediation-Run` trailer, never stash, and refuse unsafe repository states. Outcomes (`fixed`, `changed_not_passing`, `changed_not_verified`, `unchanged`, `needs_approval`, `needs_confirmation`, `manual`, `error`) come from a cache-neutral re-check, and summaries and commit/PR gates read outcomes, never report text. Every entry point previews by default; `darnit run` writes only with `--apply`.

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
# operator configuration (~/.config/darnit/config.toml)
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
- **Config**: TOML framework configs, operator configuration TOML (user-level, tool settings), `.project/project.yaml` + `.project/darnit.yaml` (YAML, project data and claims)
- **Storage**: Filesystem only (Markdown, JSON, YAML output files; no database)

## Active Technologies
- Python 3.11/3.12 (workspace targets) plus bash for release scripts and GitHub Actions YAML + `shiv` (binary builder), `cosign` (image + binary signing), `syft` (SBOM generation), `docker buildx` (multi-arch images), `gh` CLI (release creation), Sigstore-action (PyPI wheel signing via `pypa/gh-action-pypi-publish`). No new runtime dependencies in any darnit Python package. (012-packaging-distribution)
- External release surfaces only — PyPI, TestPyPI, GHCR, GitHub Releases (binary assets + attestations), `kusari-oss/homebrew-tap` repo (formula). Repo itself stores only build configs and workflow definitions. (012-packaging-distribution)
- Python 3.11/3.12 (workspace targets — same as the rest of darnit) + `pydantic >= 2.0` (already used for `FrameworkConfig`); `packaging` for PEP 440 `SpecifierSet` (declared by `darnit-reproducibility` as of feature 037; darnit-core imports it at runtime without declaring it, which is tracked separately). `tomllib` from stdlib for TOML parsing. No new runtime dependencies. (013-plugin-composition)
- Filesystem only. Composition is resolved in-memory at framework-config load time; no new persistent state. (013-plugin-composition)
- Python 3.11/3.12 (workspace targets) + `tomllib` (stdlib), `pydantic >= 2` (existing; `extra="forbid"` for the new models). No new runtime dependencies: per-user config location extends the existing `darnit/stores/defaults/platform_paths.py`; repository-identity normalization is a small in-tree helper. (040-operator-config-trust)
- Filesystem only. Operator configuration: one TOML file per user (research R1). Confirmations: a file under the existing darnit data root, keyed by canonical repository identity (research R6). Project assertions: `.project/darnit.yaml` in the audited repository (read-only input). (040-operator-config-trust)
- Python 3.11/3.12 (workspace targets) + existing only -- `pydantic >= 2` (models, `extra="forbid"`), `cel-python` (CEL), `pydantic-ai-slim[anthropic]` behind the `LLMStep` protocol, `gh` CLI for platform calls. No new runtime dependencies. (041-result-authority-contract)
- Filesystem. PASS candidates and confirmations use the feature 040 operator-side store. Corpus fixtures are files under `tests/darnit_baseline/corpus/`. (041-result-authority-contract)
- Python 3.11/3.12 (workspace targets) + existing only -- `pydantic >= 2`, `ruamel.yaml` (already a darnit-core dependency, for round-trip writes), `PyYAML`, `jinja2` (remediation templates), `cel-python` (detect filters). No new runtime dependencies. (042-candidate-integrity)
- Filesystem. Context values and in-repository confirmation records in `.project/darnit.yaml`; the project's `.project/project.yaml` is read and, only by applied remediation, patched in place; operator-side records in the feature 040 store (`trust/confirmations.json`, claim `context_value`). (042-candidate-integrity)
- Python 3.11/3.12 (workspace targets) + existing only -- `pydantic >= 2` (`extra="forbid"` models), `gh` CLI for platform calls (JSON bodies via `--input -`), `git` CLI, `jinja2` (templates), `ruamel.yaml` (round-trip `.project/` writes, feature 042). No new runtime dependencies; run ids use a small in-tree ULID helper or `uuid4`. (043-remediation-safety)
- Filesystem. Remediation policy in the feature 040 operator configuration. Run manifests operator-side under the darnit data root (`remediation/<repository-identity>/<run_id>.json`, 0600, never in the checkout). No new repository files; commit messages carry a `Darnit-Remediation-Run` trailer. (043-remediation-safety)

## Recent Changes
- 029-openai-parity-adapter: adds OpenAI as a second Tier 2 backend to feature 028's parity test suite. Introduces `SkillInvocationBackend` Protocol in `tests/darnit/parity/tier2/backends/base.py` (test-only seam; `@runtime_checkable`); refactors feature 028's `claude_agent_sdk_client.py` into `backends/claude_agent_sdk.py` (backwards-compat shim preserves old import path); adds `OpenAIBackend` using Chat Completions API with `tools=[...]` function-calling, `temperature=0.0`, and pinned version-suffixed model default (`gpt-4o-2024-08-06`). Runner gains `--backend`, `--model`, `--max-turns` flags; new outcome `turn_cap_exhausted` (exit code 5) distinguishes runaway tool-loops from unparseable output. Separate `parity-tier2-openai.yml` workflow with `environment: parity-tier2-openai` (its own reviewer list + `OPENAI_API_KEY` at Environment scope, no repo-level exposure); mechanically enforced by workflow-config test. Zero product-package changes. Closes #368.
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
[`specs/041-result-authority-contract/plan.md`](specs/041-result-authority-contract/plan.md)
<!-- SPECKIT END -->
