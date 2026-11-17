---
description: "Task list for feature 031-mcp-server-handler"
---

# Tasks: mcp handler for calling external MCP servers as observation sources

**Input**: Design documents in `specs/031-mcp-server-handler/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/mcp-handler-contract.md](./contracts/mcp-handler-contract.md), [quickstart.md](./quickstart.md).

**Tests**: Included. Spec SC-002 requires mechanical verification of "spawns == 1, terminations == 1 across 20 controls" via a mock server that counts its own lifecycle events. Every user story's Independent Test requires a fixture-driven behavior test. Tests are load-bearing.

**Organization**: One phase per user story after Setup + Foundational. Every user-story task carries a `[USn]` label. Cross-story files are only touched in Setup / Foundational / Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: `[US1]`, `[US2]`, `[US3]`, `[US4]` matching spec's user stories.
- File paths are absolute-from-repo-root.

## Path Conventions

Single workspace repo. All product code under `packages/darnit/src/darnit/sieve/` and `packages/darnit/src/darnit/config/`. Tests under `tests/darnit/sieve/`, `tests/darnit/config/`, and a new `tests/darnit/sieve/fixtures/mock_mcp_server/` package.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Introduce the two new module files the rest of the feature builds on, plus the mock MCP server fixture used across US1/US2/US4 tests.

- [X] T001 Create `packages/darnit/src/darnit/sieve/mcp_pool.py` with a module docstring naming its purpose (per-audit pool for MCP client sessions; spawn-lazy, teardown-in-finally), the constants `MCP_ENV_SAFE_KEYS = ("PATH", "HOME", "LANG", "SSL_CERT_FILE")`, `MCP_ENV_SAFE_PREFIXES = ("LC_", "XDG_")`, `MCP_PROGRESS_VERB = "dispatching_mcp"`, and stub declarations for `PooledSession` (dataclass) and `McpPool` (class) with method signatures only. No implementation body yet -- that lands in Phase 4.

- [X] T002 Create `packages/darnit/src/darnit/sieve/mcp_trust.py` with a module docstring naming its purpose (Sigstore sidecar verification for `trusted_publisher`; deliberately isolated so issue #375 sandbox work can extend the pre-spawn hooks without touching the pool). Stub the single public function `verify(binary_path: Path, trusted_publisher: str) -> tuple[bool, str]` returning `(True, "")` unconditionally as a placeholder. Real implementation lands in Phase 5.

- [X] T003 Create the mock MCP server package at `tests/darnit/sieve/fixtures/mock_mcp_server/__init__.py` and `tests/darnit/sieve/fixtures/mock_mcp_server/__main__.py`. Use `mcp.server.Server` primitives. Expose four tools: `echo(text: str) -> {"text": str}`, `get_score(repo_url: str) -> {"score": float}` (score parameterizable via env `DARNIT_MOCK_MCP_SCORE`, default 8.5), `raise_error(reason: str)` returning `isError=True`, `sleep_forever()` hanging indefinitely. Every spawn, teardown, and tool-call event MUST append one JSON line to the file named by env `DARNIT_MOCK_MCP_COUNTER_FILE` (if set).

- [X] T004 Add a pytest fixture `mock_mcp_server_command` in `tests/darnit/sieve/conftest.py` (create the file if it does not exist) that returns a `list[str]` command suitable for a `[mcp_servers.mock]` `command` field: `[sys.executable, "-m", "tests.darnit.sieve.fixtures.mock_mcp_server"]`. Also add a fixture `mcp_counter_file(tmp_path)` returning a fresh path per test so counter files never collide.

**Checkpoint**: Module skeletons and mock server exist. No behavior yet; nothing wires into the sieve. Phase 2 starts wiring.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The two schema and orchestrator edits every user story depends on. Nothing US1-through-US4 can be implemented until these land, because both the reader and the pool need to know how to find their config.

**CRITICAL**: No user story work begins until this phase completes.

- [X] T005 Add `McpServerConfig(BaseModel)` to `packages/darnit/src/darnit/config/framework_schema.py`. Fields per [data-model.md](./data-model.md): `command: list[str]` (required, min length 1), `env: dict[str, str] = Field(default_factory=dict)`, `trusted_publisher: str | None = None`, `optional: bool = True`, `install_hint: str = ""`. Add `model_config = ConfigDict(extra="forbid")` so unknown fields (e.g., a hypothetical future `transport = "http"` key that v0 does not support) raise `ValidationError` at load time rather than silently accepting. This locks spec FR-015 ("transport specification other than stdio MUST produce a clear ERROR") at the schema layer. Validator on `command` MUST reject empty list with a clear error message. Validator on `trusted_publisher` (when set) MUST accept `https://github.com/<owner>` or `https://github.com/<owner>/<repo>` shapes; other shapes are permitted but generate a Pydantic warning. Follow the file's existing docstring + field-comment conventions.

- [X] T006 Add the field `mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)` to the existing `FrameworkConfig` class in `packages/darnit/src/darnit/config/framework_schema.py`. Empty default preserves backward compatibility for every existing framework TOML (spec Backward Compatibility). Place the field next to `plugins` (line ~1421 pre-feature) so a maintainer diffing the schema sees the two extension surfaces together.

- [X] T007 Update `packages/darnit/src/darnit/config/merger.py` to merge `mcp_servers` blocks with the same precedence rule as other framework-vs-baseline blocks: `.baseline.toml` block for a given `<name>` fully replaces the framework TOML block for that `<name>` (spec FR-016). Do NOT deep-merge fields within a block; a `.baseline.toml` entry is authoritative for that server name.

- [X] T008 Add `_mcp_pool: McpPool | None = None` field on `SieveOrchestrator` in `packages/darnit/src/darnit/sieve/orchestrator.py`. Initialize as `None` in `__init__`; construct lazily inside the handler dispatch path when first needed (this keeps orchestrators that never call `mcp` handlers zero-cost). Extend `reset_caches()` to call `self._mcp_pool.teardown_all()` if the pool exists then set `self._mcp_pool = None` so a subsequent `verify_batch` starts fresh. Wrap the per-control loop inside `verify_batch()` in a `try / finally` that also calls `teardown_all()` and clears the field on exit (success, failure, or exception).

- [X] T008a Wire the `dispatching_mcp` progress log AND the pool handoff into the orchestrator's dispatch site (`_dispatch_handler_invocations` in `packages/darnit/src/darnit/sieve/orchestrator.py`). Two edits: **(a)** add `mcp_pool: McpPool | None = None` field to `HandlerContext` in `packages/darnit/src/darnit/sieve/handler_registry.py`; **(b)** in the dispatch loop, when `invocation.handler == "mcp"`, lazily construct `self._mcp_pool` if `None`, assign it into the built `HandlerContext.mcp_pool`, and emit `f"[{idx}/{total}] {control_spec.control_id} dispatching_mcp {invocation.server}.{invocation.tool}"` on the `darnit.harness` logger at INFO level BEFORE calling the handler function. `(idx, total)` are threaded from `verify_batch`'s enumeration loop; add a small `progress: tuple[int, int]` parameter to `_dispatch_handler_invocations` if it does not already receive equivalent state. Matches spec FR-019 emission-from-orchestrator posture; matches feature 026's `dispatching_llm` pattern.

**Checkpoint**: Framework config accepts `[mcp_servers.<name>]` blocks; orchestrator owns the pool slot; teardown is guaranteed on every exit path; the `dispatching_mcp` INFO log fires at the correct point in the sieve dispatch loop. No handler exists yet.

---

## Phase 3: User Story 1 - Control author writes an OSPS control that consults an external MCP server (Priority: P1) MVP

**Goal**: A TOML control with `handler = "mcp"` produces a working PASS/FAIL/ERROR against the mock server, with CEL `expr` evaluated over `result.*` and the mock response captured in evidence. This is the whole reason the feature exists; the other three stories layer on top.

**Independent Test**: Author a control whose only pass is `{ handler = "mcp", server = "mock", tool = "get_score", args = {}, expr = 'result.score >= 7.0' }` pointing at the T003/T004 mock. Run the audit. Control's status = PASS; evidence dict contains `result.score = 8.5`.

### Implementation for User Story 1

- [X] T009 [P] [US1] Implement `PooledSession` dataclass in `packages/darnit/src/darnit/sieve/mcp_pool.py`: fields per [data-model.md](./data-model.md) (`server_name`, `config`, `session`, `trust_label`, `spawn_ts`, `broken`). Add methods `mark_broken(self) -> None` and `is_healthy(self) -> bool`. No I/O in the dataclass; it's just runtime state.

- [X] T010 [P] [US1] Implement `McpPool.build_child_env(server_config: McpServerConfig) -> dict[str, str]` in `packages/darnit/src/darnit/sieve/mcp_pool.py`. Reads `os.environ`, filters by the predicate `k in MCP_ENV_SAFE_KEYS or any(k.startswith(p) for p in MCP_ENV_SAFE_PREFIXES)`, then overlays substituted values from `server_config.env`. `$VAR` substitution in values MUST look up `VAR` in `os.environ` and substitute empty string if unset (matching `exec` handler). On Windows, additionally allow-list `SYSTEMROOT` and `SYSTEMDRIVE` (guard with `sys.platform`).

- [X] T011 [US1] Implement `McpPool.acquire(self, server_name: str, config: McpServerConfig) -> PooledSession` in `packages/darnit/src/darnit/sieve/mcp_pool.py`. First lookup in `self._sessions: dict[str, PooledSession]`. If missing, call `self._spawn(server_name, config)`. If present but `broken`, call `self._spawn` once more and cache. If present, `broken`, AND already-respawned-and-broken again, raise `McpServerUnusable` with the reason. Return the session.

- [X] T012 [US1] Implement `McpPool._spawn(self, server_name: str, config: McpServerConfig) -> PooledSession` in `packages/darnit/src/darnit/sieve/mcp_pool.py`. Steps: (a) resolve `config.command[0]` on PATH via `shutil.which` (unless it's absolute); if missing, raise `McpServerBinaryMissing` with the resolved-name and `install_hint`. (b) If `config.trusted_publisher` is set, call `mcp_trust.verify(binary_path, config.trusted_publisher)`; on `False`, raise `McpServerVerificationFailed` with the reason. (c) Assemble the child env via `build_child_env`. (d) Construct `mcp.client.stdio.StdioServerParameters(command=config.command[0], args=config.command[1:], env=child_env)`. (e) Enter the `stdio_client` context and open a `ClientSession`, call `session.initialize()`. (f) Cache in `self._sessions[server_name]` and return the `PooledSession` with the correct `trust_label`. Any exception from steps (d)-(f) raises `McpServerHandshakeFailed` with the reason and does NOT cache.

- [X] T013 [US1] Implement `McpPool.call_tool(self, server_name: str, config: McpServerConfig, tool: str, args: dict, timeout: float) -> dict` in `packages/darnit/src/darnit/sieve/mcp_pool.py`. Acquire session via `acquire`. Call `asyncio.run(asyncio.wait_for(session.call_tool(tool, args), timeout=timeout))`. On timeout, mark session broken and raise `McpToolTimeout`. On MCP `CallToolResult` with `isError=True`, raise `McpToolError` with the tool-supplied message; do NOT mark the session broken (this is a tool-level error, not a session-level one). On non-text content, raise `McpToolResponseNotJson`. On success, parse the text content as JSON and return the dict.

- [X] T014 [US1] Implement `McpPool.teardown_all(self) -> None` in `packages/darnit/src/darnit/sieve/mcp_pool.py`. Iterates `self._sessions.values()`, closes each session with best-effort exception suppression (log a warning; do NOT re-raise), then clears the dict. This is what the orchestrator calls in `reset_caches()` and in `verify_batch`'s finally.

- [X] T015 [US1] Define the exception hierarchy in `packages/darnit/src/darnit/sieve/mcp_pool.py`: `McpPoolError` (base), `McpServerBinaryMissing`, `McpServerVerificationFailed`, `McpServerHandshakeFailed`, `McpServerUnusable`, `McpToolTimeout`, `McpToolError`, `McpToolResponseNotJson`. Each carries the specific reason string the failure-mode table in `contracts/mcp-handler-contract.md` names.

- [X] T016 [US1] Add `mcp_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult` in `packages/darnit/src/darnit/sieve/builtin_handlers.py`, alongside the other built-in handlers. Body: (a) read `server`, `tool`, `args`, `expr`, `timeout=MCP_DEFAULT_TIMEOUT_SECONDS` from `config`; validate `server` and `tool` are non-empty strings. (b) look up the `McpServerConfig` from the effective framework config; if missing, return `HandlerResult(status=ERROR, message="unknown MCP server: <name>", ...)`. (c) substitute `$OWNER`/`$REPO`/`$BRANCH`/`$PATH` in `args` values using `context`. (d) obtain the orchestrator's pool via `context.mcp_pool` (assigned by the orchestrator's dispatch site in T008a). If `context.mcp_pool is None`, return `HandlerResult(status=ERROR, message="mcp handler invoked without pool wiring (internal error)", ...)` -- this is a plumbing bug, not a user-facing failure. (e) call `pool.call_tool(...)`. Map exceptions to `HandlerResult` per the failure-mode table (ERROR/INCONCLUSIVE/FAIL). (f) evaluate `expr` (if set) against `{"result": <response>}`; PASS/FAIL accordingly. (g) attach a `McpInvocationRecord`-shaped dict into `HandlerResult.evidence["mcp_calls"]` (list append). NOTE: the handler does NOT emit the `dispatching_mcp` INFO log -- that belongs to the orchestrator (T008a) so `[N/M]` is available.

- [X] T017 [US1] Add `MCP_DEFAULT_TIMEOUT_SECONDS = 60` as a module-level constant in `packages/darnit/src/darnit/sieve/builtin_handlers.py` (spec FR-002, clarified 2026-08-16). Reference it as the default in the `mcp_handler` timeout read.

- [X] T018 [US1] Register `mcp_handler` in `register_builtin_handlers()` at `packages/darnit/src/darnit/sieve/builtin_handlers.py`. Call signature: `registry.register("mcp", phase="deterministic", handler_fn=mcp_handler, default_authority="dispositive")`. This makes it available to control authors alongside `exec`, `api_call`, `file_exists`, etc.

- [X] T019 [P] [US1] Write `tests/darnit/sieve/test_mcp_handler.py::test_pass_evaluates_expr_over_result` -- author a `ProjectConfig`-style TOML config with `[mcp_servers.mock] command = <mock_mcp_server_command>` and a control whose pass uses `handler = "mcp"`, `tool = "get_score"`, `expr = 'result.score >= 7.0'`. Run the sieve orchestrator against it. Assert (a) the control resolves PASS; (b) `evidence["mcp_calls"][0]["raw_response"] == {"score": 8.5}` (matching the mock's default); (c) `evidence["mcp_calls"][0]["trust_label"] == "operator-trusted-path"`.

- [X] T020 [P] [US1] Write `tests/darnit/sieve/test_mcp_handler.py::test_fail_when_expr_false` -- same fixture with `DARNIT_MOCK_MCP_SCORE=5.0` in the `env` block. Same `expr = 'result.score >= 7.0'`. Assert the control resolves FAIL (not ERROR); `evidence["mcp_calls"][0]["raw_response"]["score"] == 5.0`.

- [X] T021 [P] [US1] Write `tests/darnit/sieve/test_mcp_handler.py::test_arg_substitution` -- pass `args = { repo_url = "github.com/$OWNER/$REPO" }` and set `context.owner = "octo"`, `context.repo = "hello"`. Use the `echo` tool. Assert `evidence["mcp_calls"][0]["args_after_substitution"]["repo_url"] == "github.com/octo/hello"` and the mock's echoed response reflects the substituted value.

- [X] T022 [P] [US1] Write `tests/darnit/sieve/test_mcp_handler.py::test_progress_log_line_emitted` -- use `caplog` at INFO level on `darnit.harness`. Run the same config as T019. Assert exactly one log record matches the pattern `r"\[\d+/\d+\] \S+ dispatching_mcp mock\.get_score"`.

**Checkpoint**: A control author can now write a `handler = "mcp"` pass and have it resolve against the mock server. US1's Independent Test passes.

---

## Phase 4: User Story 2 - Operator adds a new MCP-backed capability without editing plugin code (Priority: P2)

**Goal**: An operator's edit to `.baseline.toml` is the whole delta needed to enable a new MCP-backed server. No plugin code, no framework fork.

**Independent Test**: On a fresh checkout with no plugin changes, add a `[mcp_servers.newthing]` block to `.baseline.toml`, place its binary on PATH, author a control that references it, run the audit, observe the control resolve.

### Implementation for User Story 2

- [X] T023 [P] [US2] Write `tests/darnit/config/test_framework_schema.py::test_mcp_servers_block_parses` -- author a small framework TOML with an `[mcp_servers.example]` block including all optional fields. Assert `FrameworkConfig.mcp_servers["example"].command == [...]`, `env == {...}`, `trusted_publisher == "..."`, `optional == False`, `install_hint == "..."`.

- [X] T024 [P] [US2] Write `tests/darnit/config/test_framework_schema.py::test_mcp_servers_command_required` -- author `[mcp_servers.example]` with only `env = {...}` (missing `command`). Assert `ValidationError` is raised at load time with a message naming `command`.

- [X] T025 [P] [US2] Write `tests/darnit/config/test_framework_schema.py::test_mcp_servers_command_nonempty` -- author `[mcp_servers.example].command = []`. Assert `ValidationError` with a message noting the empty list.

- [X] T026 [P] [US2] Write `tests/darnit/config/test_merger.py::test_mcp_servers_baseline_wins` -- author a framework TOML with `[mcp_servers.foo].command = ["fw-cmd"]` and a `.baseline.toml` with `[mcp_servers.foo].command = ["bl-cmd"]`. Merge. Assert the merged config's `mcp_servers["foo"].command == ["bl-cmd"]` (baseline replaces, not deep-merges).

- [X] T027 [P] [US2] Write `tests/darnit/config/test_merger.py::test_mcp_servers_disjoint_names_coexist` -- framework declares `[mcp_servers.a]`, baseline declares `[mcp_servers.b]`. Assert both keys present in merged config.

- [X] T028 [P] [US2] Write `tests/darnit/sieve/test_mcp_handler.py::test_env_curation_drops_credentials` -- monkeypatch `os.environ` with `AWS_SECRET_ACCESS_KEY="secret"`, `GITHUB_TOKEN="ghp_x"`, `HOME="/h"`, `PATH="/usr/bin"`, `XDG_CONFIG_HOME="/xdg"`, `LC_ALL="en_US.UTF-8"`. Call `McpPool.build_child_env(McpServerConfig(command=["true"], env={}))`. Assert the result contains `HOME`, `PATH`, `XDG_CONFIG_HOME`, `LC_ALL`; does NOT contain `AWS_SECRET_ACCESS_KEY` or `GITHUB_TOKEN`.

- [X] T029 [P] [US2] Write `tests/darnit/sieve/test_mcp_handler.py::test_env_toml_block_substitutes_from_parent` -- monkeypatch `os.environ["GH_TOKEN"] = "ghp_realtoken"`. Config `env = {"GITHUB_TOKEN": "$GH_TOKEN", "STATIC_VAL": "literal"}`. Assert `build_child_env` output contains `GITHUB_TOKEN=ghp_realtoken` and `STATIC_VAL=literal`.

- [X] T030 [P] [US2] Write `tests/darnit/sieve/test_mcp_handler.py::test_env_unset_var_substitutes_empty` -- monkeypatch `os.environ` to NOT contain `UNSET_VAR`. Config `env = {"X": "$UNSET_VAR"}`. Assert `build_child_env` output contains `X=""` (empty string), NOT that the key is missing.

- [X] T031 [P] [US2] Write `tests/darnit/sieve/test_mcp_handler.py::test_unknown_server_produces_error` -- author a control with `handler = "mcp"`, `server = "rogue"`, no `[mcp_servers.rogue]` block anywhere. Run the sieve. Assert the control resolves ERROR with a message matching `unknown MCP server: rogue`; assert NO subprocess was spawned (verify by asserting the mock server's counter file was never written).

- [X] T031a [P] [US2] Write `tests/darnit/config/test_framework_schema.py::test_mcp_servers_rejects_unknown_field` -- author a framework TOML with `[mcp_servers.foo] command = ["cmd"], transport = "http"`. Assert loading raises `ValidationError` with a message naming the `transport` key. Locks spec FR-015 ("transport specification other than stdio MUST produce a clear ERROR rather than silent hang") at the schema-load boundary. Pairs with the `extra="forbid"` addition on `McpServerConfig` in T005.

**Checkpoint**: Operator-facing configuration surface is fully covered by schema, merge-precedence, env-curation, and unknown-field rejection tests. US2's Independent Test passes.

---

## Phase 5: User Story 3 - Trust boundary is respected regardless of the operator's PATH state (Priority: P2)

**Goal**: An allowlist entry is necessary; when `trusted_publisher` is set, Sigstore verification is additionally required; verification failure never contributes evidence.

**Independent Test**: Two shell tests. (a) Reference a server without `[mcp_servers.*]` entry -> ERROR without spawn. (b) `trusted_publisher = "..."` with a binary whose sidecar mismatches -> ERROR with verification-failed message; no evidence contribution.

### Implementation for User Story 3

- [X] T032 [US3] Implement `mcp_trust.verify(binary_path: Path, trusted_publisher: str) -> tuple[bool, str]` in `packages/darnit/src/darnit/sieve/mcp_trust.py`. Steps: (a) look for `binary_path.with_suffix(".sigstore")` OR `binary_path.with_suffix(".sigstore.json")` sidecar; if neither exists, return `(False, "no Sigstore sidecar found next to <binary_path>")`. (b) Read the sidecar bytes; parse as `sigstore.models.Bundle` via `Bundle.from_json`. (c) Construct `policy = AllOf([OIDCIssuer("https://token.actions.githubusercontent.com"), GitHubWorkflowRepository(<owner/repo from trusted_publisher>)])`. (d) Call `Verifier.production().verify_dsse(bundle, policy)`; on success return `(True, "verified against <trusted_publisher>")`; on exception return `(False, "Sigstore verification failed: <exception str>")`. (e) Guard the whole function with `try/except ImportError` on sigstore; if unavailable, return `(False, "sigstore not installed - install darnit-core[attestation]")`.

- [X] T033 [P] [US3] Write `tests/darnit/sieve/test_mcp_trust.py::test_no_sidecar_returns_false_with_reason` -- create a temp binary file, no sidecar. Call `verify(binary_path, "https://github.com/example/example")`. Assert `(False, msg)` where `msg` names the missing sidecar.

- [X] T034 [P] [US3] Write `tests/darnit/sieve/test_mcp_trust.py::test_malformed_sidecar_returns_false` -- create a temp binary file and a `<binary>.sigstore` file containing `{"not": "a bundle"}`. Assert `(False, msg)` where `msg` includes the phrase `Sigstore verification failed` or `not a valid bundle` (mirror whatever the SDK raises).

- [X] T035 [P] [US3] Write `tests/darnit/sieve/test_mcp_trust.py::test_sigstore_unavailable_returns_false` -- monkeypatch `sigstore` to `None` via `sys.modules`. Call `verify(...)`. Assert `(False, msg)` naming `darnit-core[attestation]`.

- [X] T036 [US3] Write `tests/darnit/sieve/test_mcp_handler.py::test_verification_failure_produces_error_no_evidence` -- monkeypatch `mcp_trust.verify` to return `(False, "TEST verification failed")`. Config `[mcp_servers.pinned].command = [<mock>], trusted_publisher = "https://github.com/example"`. Run a control that uses `server = "pinned"`. Assert the control resolves ERROR with message containing `Sigstore verification failed`; assert `evidence["mcp_calls"]` list is EMPTY or contains only the failure record (no `raw_response`); assert the mock's counter file shows ZERO tool-call events (server was never spawned OR was terminated before a tool call).

- [X] T037 [US3] Write `tests/darnit/sieve/test_mcp_handler.py::test_verification_success_trust_label` -- monkeypatch `mcp_trust.verify` to return `(True, "verified against https://github.com/example")`. Same fixture. Assert the control resolves PASS (using `expr = 'result.score >= 7.0'`); `evidence["mcp_calls"][0]["trust_label"] == "sigstore-verified"`.

- [X] T038 [US3] Write `tests/darnit/sieve/test_mcp_handler.py::test_trusted_publisher_absent_label_is_operator_trusted_path` -- config omits `trusted_publisher`. Same PASS assertion as T037 but `trust_label == "operator-trusted-path"`. Assert `mcp_trust.verify` was NOT called (spy via monkeypatch or `unittest.mock`).

**Checkpoint**: Trust boundary tests all pass. A malicious binary swapped onto PATH under a `trusted_publisher`-declared server name cannot contribute evidence. US3's Independent Test passes.

---

## Phase 6: User Story 4 - Missing binary is a knowable, non-fatal outcome by default (Priority: P3)

**Goal**: An absent binary defaults to INCONCLUSIVE (not ERROR, not silent PASS) with actionable install-hint text; `optional = false` promotes absence to FAIL. Session-crash/hang/tool-error paths all distinguish INCONCLUSIVE/ERROR/FAIL cleanly.

**Independent Test**: `[mcp_servers.absent].command = ["absentbin"]` with no `absentbin` on PATH. Control resolves INCONCLUSIVE with `absentbin` and install-hint in the message. Flip `optional = false`; same absence produces FAIL. Then present-but-error paths (raise_error, sleep_forever) exercise their respective statuses.

### Implementation for User Story 4

- [X] T039 [P] [US4] Write `tests/darnit/sieve/test_mcp_handler.py::test_binary_absent_optional_true_inconclusive` -- config `command = ["definitelynotarealthing_xyzq"]`. Run the control. Assert status INCONCLUSIVE; message contains `MCP server binary not found: definitelynotarealthing_xyzq` and any `install_hint`. Assert the mock's counter file is empty.

- [X] T040 [P] [US4] Write `tests/darnit/sieve/test_mcp_handler.py::test_binary_absent_optional_false_fails` -- same config plus `optional = false`. Assert status FAIL with same message shape.

- [X] T041 [P] [US4] Write `tests/darnit/sieve/test_mcp_handler.py::test_tool_timeout_produces_error_marks_broken` -- config points at mock; control uses `tool = "sleep_forever"` and `timeout = 1`. Assert control resolves ERROR with message containing `timed out after 1s`. Then run a SECOND control that uses `tool = "get_score"` on the same server. Assert the second control succeeds because the pool respawned after the broken session. Verify the mock's counter file shows exactly TWO spawn events (initial + one respawn); do NOT confuse this with SC-002's spawn-once property, which applies only to the no-crash path (see T044).

- [X] T042 [P] [US4] Write `tests/darnit/sieve/test_mcp_handler.py::test_tool_side_error_produces_error_no_broken` -- control uses `tool = "raise_error", args = {"reason": "test"}`. Assert control resolves ERROR with message containing `MCP tool error` and the reason string. Then run a SECOND control against the same server using `tool = "echo"`. Assert the second succeeds AND the pool did NOT respawn (session was not marked broken because tool-side error is not a session-level failure). Verify by asserting the mock's counter file shows exactly ONE spawn event.

- [X] T043 [P] [US4] Write `tests/darnit/sieve/test_mcp_handler.py::test_handshake_failure_produces_inconclusive_no_evidence` -- point the config at a `command = ["python", "-c", "import sys; sys.exit(0)"]` binary that exits immediately after spawn (no MCP handshake). Assert control resolves INCONCLUSIVE with message containing `MCP handshake failed`. Assert `evidence["mcp_calls"]` list is empty of successful invocations.

- [X] T044 [P] [US4] Write `tests/darnit/sieve/test_mcp_pool.py::test_teardown_on_success_path` -- construct an orchestrator, run a `verify_batch` with two controls that both use the mock server, assert the mock's counter file shows exactly one spawn AND exactly one teardown event (SC-002 property).

- [X] T045 [P] [US4] Write `tests/darnit/sieve/test_mcp_pool.py::test_teardown_on_exception_path` -- inject an exception at the second control's dispatch (monkeypatch one of its handler chains to raise `RuntimeError`). Assert the exception propagates out of `verify_batch` AND the mock's counter file shows a teardown event (finally-block guarantee).

**Checkpoint**: All four spec user stories are covered by tests. Every failure mode from `contracts/mcp-handler-contract.md`'s table has a corresponding regression test.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Full workspace verification, scope guard, lint clean, spec-sync validation, product-scope invariant.

- [X] T046 Run the full workspace test sweep from repo root: `uv run pytest tests/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged`. Confirm exit code 0. (The deselect matches the pattern used by feature 030 to avoid the CNCF-drift test.)

- [X] T047 [P] Two sub-steps, both MUST pass. **(a) Structure Decision**: verify no file outside `packages/darnit/src/darnit/sieve/`, `packages/darnit/src/darnit/config/framework_schema.py`, `packages/darnit/src/darnit/config/merger.py`, and `tests/darnit/` was modified under `packages/*/src/`: `git diff --name-only main..HEAD | grep -E 'packages/(darnit-baseline|darnit-gittuf|darnit-amber)/src/'` MUST produce zero lines. **(b) FR-017 no-new-runtime-dep guard**: any change to `pyproject.toml` at the repo root or any `packages/*/pyproject.toml` MUST NOT add a new entry to `[project.dependencies]` or `[project.optional-dependencies]` for a published product package. `git diff main..HEAD -- pyproject.toml packages/*/pyproject.toml` MUST either be empty OR be reviewed against FR-017 (`mcp>=1.23,<2` and `sigstore` were both already runtime deps pre-feature; no new package should appear).

- [X] T048 [P] Run `uv run ruff check .` on repo root; MUST exit 0. Fix any lint issues in the files this feature touched; do NOT auto-format unrelated files.

- [X] T049 [P] Run `uv run python scripts/validate_sync.py --verbose` if that script exists; MUST exit 0. This is darnit's spec-implementation sync check per constitution's Development Workflow section. It validates that the new `mcp` handler name in TOML schemas matches the code registration.

- [X] T050 Confirm the module docstring on `packages/darnit/src/darnit/sieve/mcp_pool.py` and `mcp_trust.py` accurately describes the final implementation (specifically the exception hierarchy from T015 and the sidecar-lookup path from T032). Fix any docstring/code drift. Also confirm the `contracts/mcp-handler-contract.md` failure-mode table matches every exception the handler emits (cross-read against T016's exception-to-HandlerResult mapping).

---

## Dependencies

```
Phase 1 (T001..T004) ──> Phase 2 (T005..T008) ──> Phase 3 (US1: T009..T022)
                                                        │
                                                        ├──> Phase 4 (US2: T023..T031) [all [P] within phase]
                                                        │
                                                        ├──> Phase 5 (US3: T032..T038)
                                                        │
                                                        ├──> Phase 6 (US4: T039..T045) [all [P] within phase]
                                                        │
                                                        └──> Phase 7 (Polish: T046..T050)
```

Phase 1 tasks T001, T002 touch different files, T003 and T004 touch different files (mock server package vs conftest.py) — all four are `[P]` in principle but marked sequential in the outline because reviewer readability improves when the four setup steps land in order.

Within Phase 3 (US1), tasks T009 and T010 touch different regions of `mcp_pool.py` and can be authored `[P]`. Tasks T011–T015 all touch `mcp_pool.py` and MUST serialize on it. T016–T018 touch `builtin_handlers.py` and MUST serialize on it. T019–T022 write independent tests in the same test file — mark `[P]` because pytest itself handles concurrent additions cleanly at review time; commit ordering does not matter.

Within Phase 5 (US3), T032 must land before T036–T038 (which monkeypatch the real function). T033–T035 test the real function directly and can be authored parallel to T036–T038 as long as T032 lands first.

## Parallel execution examples

After Phase 3 (US1) completes, US2/US3/US4 test files are disjoint from each other AND from `mcp_pool.py` — Phase 4, Phase 5, and Phase 6 can be authored concurrently:

```sh
# Fire the US2 config tests, US3 trust tests, and US4 failure-mode tests concurrently.
# All touch distinct test files; no serialization needed.
uv run pytest tests/darnit/config/test_framework_schema.py tests/darnit/config/test_merger.py -q &   # US2 configs
uv run pytest tests/darnit/sieve/test_mcp_trust.py -q &                                              # US3 trust
uv run pytest tests/darnit/sieve/test_mcp_pool.py -q &                                               # US4 lifecycle
wait
```

Within Phase 7:

```sh
uv run pytest tests/ -q --deselect ...              # T046 (long-running; start it first)
git diff --name-only main..HEAD | grep -E ...       # T047 (fast, [P])
uv run ruff check .                                 # T048 (fast, [P])
uv run python scripts/validate_sync.py --verbose    # T049 (fast, [P])
# T050 runs last, requires final state
```

## Implementation strategy

MVP scope = Phase 1 + Phase 2 + Phase 3 (User Story 1 alone). Landing US1 gets the machinery working end-to-end against the mock server and delivers the P1 goal. Everything after that layers additional guarantees onto the same code path.

Incremental delivery order:

1. Land T001..T022 (Setup + Foundational + US1) as the MVP PR. At this point a control author can write `handler = "mcp"` and consult the mock. Failure modes are covered by unit tests for T016's exception mapping.
2. Land T023..T031 (US2 config + env curation) as a follow-up commit or separate PR. Independent of US1 code but layered onto its config path.
3. Land T032..T038 (US3 trust boundary) as a follow-up commit. Adds Sigstore verification behind a small new module.
4. Land T039..T045 (US4 failure-mode regressions) as a follow-up commit. Locks the failure-mode table against silent regression.
5. Land T046..T050 (Polish) as the last commit or squash into the MVP.

All commits belong to the same PR against `main`. If piecewise review is preferred, reviewer order is (foundational + US1 code, US2 tests, US3 tests, US4 tests, polish) so each commit's contract-level effect is legible independently.
